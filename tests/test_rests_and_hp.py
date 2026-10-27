"""Rests, hit dice, HP corrections, and players updating their own character."""
import pytest

from app.rules import long_rest_changes, parse_hit_dice
from tests.test_dice_map_players import remote


def test_parse_hit_dice():
    assert parse_hit_dice("5d10") == [(5, 10)]
    assert parse_hit_dice("3d8 + 2d10") == [(3, 8), (2, 10)]
    assert parse_hit_dice("") == [] and parse_hit_dice("lots") == []


def test_long_rest_rules():
    ch = {"max_hp": 40, "current_hp": 3, "temp_hp": 5, "hit_dice": "5d10", "hit_dice_used": 5, "exhaustion": 2,
          "death_successes": 1, "death_failures": 2, "status": "stable",
          "spell_slots": {"1": {"max": 4, "used": 3}, "2": {"max": 2, "used": 2}}}
    c = long_rest_changes(ch)
    assert c["current_hp"] == 40 and c["temp_hp"] == 0
    assert c["hit_dice_used"] == 3, "regain half of 5 (rounded down) = 2"
    assert c["spell_slots"] == {"1": {"max": 4, "used": 0}, "2": {"max": 2, "used": 0}}
    assert c["exhaustion"] == 1 and c["death_failures"] == 0 and c["status"] == "ok"
    assert long_rest_changes(dict(ch, hit_dice="1d8", hit_dice_used=1))["hit_dice_used"] == 0, "always at least one"


@pytest.fixture
def hero(api):
    camp = api.campaign()
    h = api.character(camp["id"], name="Brom", max_hp=40, hit_dice="5d10",
                      abilities={"str": 10, "dex": 10, "con": 14, "int": 10, "wis": 10, "cha": 10})
    h = api.set_char(h, current_hp=10)
    return camp, h


def test_hp_corrections_from_sheet(api, hero):
    _, h = hero
    url = f"/api/characters/{h['id']}/hp"
    assert api.post(url, {"op": "heal", "amount": 5})["character"]["current_hp"] == 15
    assert api.post(url, {"op": "damage", "amount": 1})["character"]["current_hp"] == 14
    c = api.post(url, {"op": "set", "hp": 22, "max_hp": 45})["character"]
    assert (c["current_hp"], c["max_hp"]) == (22, 45)
    assert api.post(url, {"op": "set", "hp": 99})["character"]["current_hp"] == 45, "capped at max"
    api.post(url, {"op": "heal", "amount": -3}, expect=400)
    api.post(url, {"op": "explode"}, expect=400)


def test_hit_die_heals_by_roll_plus_con(api, hero):
    _, h = hero
    r = api.post(f"/api/characters/{h['id']}/hit-die", {"op_id": "hd1"})
    roll, c = r["roll"], r["character"]
    d10 = roll["result"]["terms"][0]["rolls"][0]["value"]
    assert roll["expression"] == "1d10+2" and roll["kind"] == "heal"
    assert c["current_hp"] == 10 + d10 + 2 and c["hit_dice_used"] == 1
    again = api.post(f"/api/characters/{h['id']}/hit-die", {"op_id": "hd1"})
    assert again["roll"]["id"] == roll["id"] and again["character"]["hit_dice_used"] == 1, "retry doesn't spend twice"
    for i in range(4):
        api.post(f"/api/characters/{h['id']}/hit-die", {"op_id": f"x{i}"})
    assert "No hit dice left" in api.post(f"/api/characters/{h['id']}/hit-die", {}, expect=400)["error"]
    api.post(f"/api/characters/{h['id']}/hit-die", {"sides": 6}, expect=400)


def test_long_rest_and_party_rest(api, hero):
    camp, h = hero
    other = api.character(camp["id"], name="Ash", max_hp=20, current_hp=1)
    npc = api.character(camp["id"], name="Meepo", kind="npc", max_hp=9, current_hp=2)
    c = api.post(f"/api/characters/{h['id']}/long-rest")["character"]
    assert c["current_hp"] == 40
    r = api.post(f"/api/campaigns/{camp['id']}/long-rest")
    assert sorted(r["rested"]) == ["Ash", "Brom"]
    assert api.get(f"/api/characters/{other['id']}")["character"]["current_hp"] == 20
    assert api.get(f"/api/characters/{npc['id']}")["character"]["current_hp"] == 2, "NPCs aren't rested with the party"


def test_change_in_running_fight_is_logged_and_undoable(api, hero):
    camp, h = hero
    eid = api.encounter(camp["id"])["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [h["id"]], "quick": {"name": "Rat", "max_hp": 2}})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/characters/{h['id']}/hp", {"op": "heal", "amount": 7})
    s = api.get(f"/api/encounters/{eid}")
    assert any("Brom heals 7 (sheet)" in l["message"] for l in s["log"])
    assert s["undo"]["label"].startswith("Brom heals 7")
    s = api.post(f"/api/encounters/{eid}/undo")
    assert api.get(f"/api/characters/{h['id']}")["character"]["current_hp"] == 10


@pytest.fixture
def player(app, api, hero):
    camp, h = hero
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.60")
    p.post("/api/join", {"code": code, "name": "Kit", "character_id": h["id"]})
    return camp, h, p


def test_players_update_their_own_character(api, player):
    camp, h, p = player
    p.post("/api/play/me/hp", {"op": "heal", "amount": 4}, 403)                 # off unless the DM allows it
    settings = camp["settings"]
    settings["players"]["edit_hp"] = True
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": settings}}})
    assert p.post("/api/play/me/hp", {"op": "heal", "amount": 4})["character"]["current_hp"] == 14
    assert p.post("/api/play/me/hp", {"op": "set", "hp": 12, "max_hp": 999})["character"]["max_hp"] == 40, "players can't change max HP"
    assert api.get(f"/api/characters/{h['id']}")["character"]["current_hp"] == 12
    api.set_char(api.get(f"/api/characters/{h['id']}")["character"], spell_slots={"1": {"max": 3, "used": 0}})
    assert p.post("/api/play/me/slot", {"level": 1, "used": 2})["character"]["spell_slots"]["1"]["used"] == 2
    assert p.post("/api/play/me/slot", {"level": 1, "used": 9})["character"]["spell_slots"]["1"]["used"] == 3
    p.post("/api/play/me/slot", {"level": 4, "used": 1}, expect=400)
    assert p.post("/api/play/me/death", {"field": "death_failures", "value": 1})["character"]["death_failures"] == 1
    r = p.post("/api/play/me/hit-die", {"op_id": "p-hd"})
    assert r["roll"]["roller_name"] == "Kit" and r["character"]["hit_dice_used"] == 1
    # the DM can see it happened
    assert any(x["label"] == "Hit die (short rest)" for x in api.get(f"/api/rolls?campaign_id={camp['id']}")["rolls"])


def test_dm_can_turn_player_editing_off(api, player):
    camp, h, p = player
    settings = api.get("/api/campaigns")["campaigns"][0]["settings"]
    settings["players"]["edit_hp"] = False
    settings["players"]["hit_dice"] = False
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": settings}}})
    assert "turned this off" in p.post("/api/play/me/hp", {"op": "heal", "amount": 1}, expect=403)["error"]
    p.post("/api/play/me/hit-die", {}, expect=403)
    p.post("/api/play/me/death", {"field": "death_failures", "value": 1}, expect=403)
    assert p.get("/api/play/state")["character"]["can"]["edit_hp"] is False


def test_players_without_character_or_dm_endpoints_blocked(app, api, player):
    camp, h, p = player
    assert p.c.post(f"/api/characters/{h['id']}/hp", json={"op": "heal", "amount": 5}).status_code == 403
    assert p.c.post(f"/api/characters/{h['id']}/long-rest").status_code == 403
    assert p.c.post(f"/api/campaigns/{camp['id']}/long-rest").status_code == 403
    code = api.get(f"/api/campaigns/{camp['id']}/players")["join_code"]
    watcher = remote(app, "192.168.1.61")
    watcher.post("/api/join", {"code": code, "name": "Viewer"})
    watcher.post("/api/play/me/hp", {"op": "heal", "amount": 1}, expect=403)
