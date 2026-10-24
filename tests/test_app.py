"""End-to-end API tests for the scenarios in the project brief.

Run with:  .venv\\Scripts\\python -m pytest
"""
import io
import json
import sqlite3

import pytest

from app import create_app
from app.rules import ability_mod, alignment_for, apply_damage, proficiency_bonus


def find(state, name):
    return next(c for c in state["combatants"] if c["name"] == name)


# 1. Campaign with multiple characters ---------------------------------------

def test_campaign_with_characters(api):
    camp = api.campaign("Curse of the Moon")
    for n in ("Aria", "Borin", "Cass"):
        api.character(camp["id"], name=n, max_hp=20)
    chars = api.get(f"/api/campaigns/{camp['id']}/characters")["characters"]
    assert [c["name"] for c in chars] == ["Aria", "Borin", "Cass"]
    assert all(c["current_hp"] == 20 for c in chars), "new characters start at full HP"


def test_character_saves_with_only_a_name(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Nameless")
    assert ch["level"] == 1 and ch["abilities"]["str"] == 10


def test_campaign_rename_and_archive_keeps_data(api):
    camp = api.campaign("Old Name")
    ch = api.character(camp["id"], name="Keeper")
    camp = api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"name": {"from": "Old Name", "to": "New Name"}}})["campaign"]
    assert camp["name"] == "New Name"
    camp = api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"archived": {"from": False, "to": True}}})["campaign"]
    assert camp["archived"] and camp["archived_at"]
    assert api.get(f"/api/characters/{ch['id']}")["character"]["name"] == "Keeper"


# 2. Derived calculations --------------------------------------------------------

def test_derived_values(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Wiz")
    ch = api.set_char(ch, level=5, spellcasting_ability="int",
                      abilities={"str": 8, "dex": 14, "con": 13, "int": 18, "wis": 12, "cha": 10},
                      save_profs=["int", "wis"], skill_profs={"arcana": 2, "perception": 1})
    d = ch["derived"]
    assert d["mods"] == {"str": -1, "dex": 2, "con": 1, "int": 4, "wis": 1, "cha": 0}
    assert d["prof"] == 3
    assert d["saves"]["int"] == 7 and d["saves"]["str"] == -1
    assert d["skills"]["arcana"] == 4 + 6, "expertise doubles proficiency"
    assert d["passive_perception"] == 10 + 1 + 3
    assert d["initiative"] == 2
    assert d["spell"] == {"dc": 15, "attack": 7, "ability": "int"}
    # homebrew overrides
    ch = api.set_char(ch, prof_override=4, initiative_override=9)
    assert ch["derived"]["prof"] == 4 and ch["derived"]["initiative"] == 9


@pytest.mark.parametrize("score,mod", [(1, -5), (3, -4), (9, -1), (10, 0), (11, 0), (15, 2), (20, 5), (30, 10)])
def test_ability_mod(score, mod):
    assert ability_mod(score) == mod


def test_proficiency_by_level():
    assert [proficiency_bonus(l) for l in (1, 4, 5, 8, 9, 13, 17, 20)] == [2, 2, 3, 3, 4, 5, 6, 6]


# 3. Morality events -----------------------------------------------------------

def test_morality_record_edit_delete_reverse(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Paladin")
    url = f"/api/characters/{ch['id']}/morality"
    s = api.post(url, {"title": "Spared the bandit", "law_delta": 0, "good_delta": 20, "tags": ["Mercy"]}, 201)
    assert (s["law"], s["good"]) == (0, 20)
    assert s["events"][0]["tags"] == ["mercy"]
    s = api.post(url, {"title": "Broke the oath", "law_delta": -40, "good_delta": -5}, 201)
    assert (s["law"], s["good"]) == (-40, 15)
    assert s["computed_alignment"] == "Chaotic Neutral"
    assert s["alignment_change"] == {"from": "True Neutral", "to": "Chaotic Neutral"}
    ev_id = s["events"][1]["id"]
    # edit: recalculated from history
    s = api.patch(f"/api/morality/{ev_id}", {"changes": {"law_delta": {"from": -40, "to": -10}}})
    assert (s["law"], s["good"]) == (-10, 15)
    assert s["character"]["alignment"] == "True Neutral"
    # reverse: offsetting event, history kept
    s = api.post(f"/api/morality/{ev_id}/reverse")
    assert (s["law"], s["good"]) == (0, 20)
    assert len(s["events"]) == 3 and s["events"][2]["reverses_id"] == ev_id
    api.post(f"/api/morality/{ev_id}/reverse", expect=400)
    # delete: totals move by exactly that event
    s = api.delete(f"/api/morality/{s['events'][0]['id']}")
    assert (s["law"], s["good"]) == (0, 0)
    assert [p["law"] for p in s["timeline"]] == [0, -10, 0]


def test_morality_manual_override_and_auto_off(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Rogue")
    api.post(f"/api/characters/{ch['id']}/morality/settings", {"auto_alignment": False, "alignment": "Lawful Good"})
    s = api.post(f"/api/characters/{ch['id']}/morality", {"title": "Murder", "law_delta": -80, "good_delta": -80}, 201)
    assert s["character"]["alignment"] == "Lawful Good", "auto off must never change alignment"
    assert s["computed_alignment"] == "Chaotic Evil"
    assert s["alignment_change"] is None


def test_alignment_thresholds_configurable(api):
    cfg = {"scale": 100, "law_threshold": 34, "good_threshold": 34}
    assert alignment_for(33, -33, cfg) == "True Neutral"
    assert alignment_for(34, -34, cfg) == "Lawful Evil"
    camp = api.campaign()
    settings = camp["settings"]
    settings["morality"]["good_threshold"] = 10
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": settings}}})
    ch = api.character(camp["id"], name="T")
    s = api.post(f"/api/characters/{ch['id']}/morality", {"title": "Kindness", "good_delta": 10}, 201)
    assert s["computed_alignment"] == "Neutral Good"
    settings["morality"]["law_threshold"] = 500
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": settings}}}, expect=400)


def test_morality_duplicate_submit_is_ignored(api):
    camp = api.campaign()
    ch = api.character(camp["id"])
    body = {"title": "Once", "good_delta": 5, "op_id": "abc123"}
    api.post(f"/api/characters/{ch['id']}/morality", body, 201)
    s = api.post(f"/api/characters/{ch['id']}/morality", body, 200)
    assert len(s["events"]) == 1


# 4–8. Combat ----------------------------------------------------------------------

@pytest.fixture
def battle(api):
    camp = api.campaign()
    hero = api.character(camp["id"], name="Hero", max_hp=30, ac=16,
                         abilities={"str": 10, "dex": 14, "con": 10, "int": 10, "wis": 10, "cha": 10})
    goblin = api.post("/api/creatures", {"name": "Goblin", "max_hp": 7, "ac": 15, "initiative_mod": 2}, 201)["creature"]
    enc = api.encounter(camp["id"])
    eid = enc["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]]})
    s = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": goblin["id"], "count": 3})
    return {"camp": camp, "hero": hero, "goblin": goblin, "eid": eid, "state": s}


def test_add_multiple_enemies(api, battle):
    names = [c["name"] for c in battle["state"]["combatants"]]
    assert names == ["Hero", "Goblin 1", "Goblin 2", "Goblin 3"]
    hero = find(battle["state"], "Hero")
    assert hero["linked"] and hero["init_mod"] == 2
    s = api.post(f"/api/encounters/{battle['eid']}/combatants",
                 {"quick": {"name": "Bandit Captain", "max_hp": 65, "ac": 15, "init_mod": 3}})
    assert find(s, "Bandit Captain")["hp"] == 65


def test_initiative_and_rounds(api, battle):
    eid = battle["eid"]
    s = battle["state"]
    rolls = {"Hero": 12, "Goblin 1": 18, "Goblin 2": 12, "Goblin 3": 5}
    for name, roll in rolls.items():
        c = find(s, name)
        s = api.patch(f"/api/combatants/{c['id']}", {"changes": {"init_roll": {"from": None, "to": roll}}})
    # tie at 12 broken by modifier: both +2, so earlier-added Hero keeps place
    assert [c["name"] for c in s["combatants"]] == ["Goblin 1", "Hero", "Goblin 2", "Goblin 3"]
    s = api.post(f"/api/encounters/{eid}/start")
    assert s["encounter"]["round"] == 1 and s["encounter"]["current_id"] == find(s, "Goblin 1")["id"]
    for _ in range(4):
        s = api.post(f"/api/encounters/{eid}/next")
    assert s["encounter"]["round"] == 2 and s["encounter"]["current_id"] == find(s, "Goblin 1")["id"]
    for _ in range(8):
        s = api.post(f"/api/encounters/{eid}/next")
    assert s["encounter"]["round"] == 4
    s = api.post(f"/api/encounters/{eid}/prev")
    assert s["encounter"]["round"] == 3 and s["encounter"]["current_id"] == find(s, "Goblin 3")["id"]
    assert any(l["kind"] == "round" and l["message"] == "Round 4 begins" for l in s["log"])


def test_skip_defeated_and_manual_order(api, battle):
    eid = battle["eid"]
    s = battle["state"]
    ids = [c["id"] for c in s["combatants"]]
    reordered = [ids[3], ids[0], ids[1], ids[2]]
    s = api.post(f"/api/encounters/{eid}/reorder", {"ids": reordered})
    assert [c["id"] for c in s["combatants"]] == reordered
    g1 = find(s, "Goblin 1")
    api.patch(f"/api/combatants/{g1['id']}", {"changes": {"status": {"to": "dead"}}})
    s = api.post(f"/api/encounters/{eid}/start")
    order = []
    for _ in range(3):
        order.append(next(c["name"] for c in s["combatants"] if c["id"] == s["encounter"]["current_id"]))
        s = api.post(f"/api/encounters/{eid}/next")
    assert "Goblin 1" not in order


def test_enemy_instances_have_independent_hp(api, battle):
    s = battle["state"]
    g2 = find(s, "Goblin 2")
    s = api.post(f"/api/combatants/{g2['id']}/hp", {"op": "damage", "amount": 5})
    assert find(s, "Goblin 2")["hp"] == 2
    assert find(s, "Goblin 1")["hp"] == 7 and find(s, "Goblin 3")["hp"] == 7
    s = api.post(f"/api/combatants/{g2['id']}/hp", {"op": "damage", "amount": 10})
    assert find(s, "Goblin 2")["hp"] == 0 and find(s, "Goblin 2")["status"] == "defeated"


def test_pc_damage_updates_character_sheet(api, battle):
    hero = find(battle["state"], "Hero")
    api.post(f"/api/combatants/{hero['id']}/hp", {"op": "temp", "amount": 5})
    s = api.post(f"/api/combatants/{hero['id']}/hp", {"op": "damage", "amount": 8})
    assert find(s, "Hero")["hp"] == 27 and find(s, "Hero")["temp_hp"] == 0
    sheet = api.get(f"/api/characters/{battle['hero']['id']}")["character"]
    assert sheet["current_hp"] == 27 and sheet["temp_hp"] == 0
    # and the other direction: sheet edit shows in combat
    api.set_char(sheet, current_hp=20)
    s = api.get(f"/api/encounters/{battle['eid']}")
    assert find(s, "Hero")["hp"] == 20


def test_pc_drop_to_zero_and_heal(api, battle):
    hero = find(battle["state"], "Hero")
    s = api.post(f"/api/combatants/{hero['id']}/hp", {"op": "damage", "amount": 40})
    h = find(s, "Hero")
    assert h["hp"] == 0 and h["status"] == "unconscious"
    api.patch(f"/api/combatants/{hero['id']}", {"changes": {"death_failures": {"from": 0, "to": 1}}})
    s = api.post(f"/api/combatants/{hero['id']}/hp", {"op": "heal", "amount": 4})
    h = find(s, "Hero")
    assert h["hp"] == 4 and h["status"] == "ok" and h["death_failures"] == 0


def test_temp_hp_rules():
    assert apply_damage(10, 5, 3) == (10, 2, 3, 0)
    assert apply_damage(10, 5, 8) == (7, 0, 5, 0)
    assert apply_damage(4, 0, 10) == (0, 0, 0, 6)


def test_temp_hp_does_not_stack_by_default(api, battle):
    g = find(battle["state"], "Goblin 1")
    api.post(f"/api/combatants/{g['id']}/hp", {"op": "temp", "amount": 5})
    s = api.post(f"/api/combatants/{g['id']}/hp", {"op": "temp", "amount": 3})
    assert find(s, "Goblin 1")["temp_hp"] == 5


def test_undo_restores_only_matching_state(api, battle):
    eid = battle["eid"]
    g1, g2 = find(battle["state"], "Goblin 1"), find(battle["state"], "Goblin 2")
    api.post(f"/api/combatants/{g1['id']}/hp", {"op": "damage", "amount": 3})
    s = api.post(f"/api/combatants/{g2['id']}/hp", {"op": "damage", "amount": 4})
    s = api.post(f"/api/encounters/{eid}/undo")
    assert find(s, "Goblin 2")["hp"] == 7 and find(s, "Goblin 1")["hp"] == 4, "undo touches only the last change"
    # a later manual edit blocks a blind undo
    api.post(f"/api/combatants/{g1['id']}/hp", {"op": "damage", "amount": 1})
    hero = find(s, "Hero")
    api.set_char(api.get(f"/api/characters/{battle['hero']['id']}")["character"], current_hp=30)
    s = api.post(f"/api/encounters/{eid}/undo")
    assert find(s, "Goblin 1")["hp"] == 4
    assert hero["hp"] == 30


def test_undo_conflict_when_changed_after(api, battle):
    hero = find(battle["state"], "Hero")
    api.post(f"/api/combatants/{hero['id']}/hp", {"op": "damage", "amount": 5})
    sheet = api.get(f"/api/characters/{battle['hero']['id']}")["character"]
    api.set_char(sheet, current_hp=10)  # changed outside combat
    r = api.post(f"/api/encounters/{battle['eid']}/undo", expect=409)
    assert r["needs_force"]
    s = api.post(f"/api/encounters/{battle['eid']}/undo", {"force": True})
    assert find(s, "Hero")["hp"] == 30


def test_hp_op_retry_is_not_applied_twice(api, battle):
    g = find(battle["state"], "Goblin 3")
    body = {"op": "damage", "amount": 2, "op_id": "retry-1"}
    api.post(f"/api/combatants/{g['id']}/hp", body)
    s = api.post(f"/api/combatants/{g['id']}/hp", body)
    assert find(s, "Goblin 3")["hp"] == 5


def test_conditions_apply_tick_and_remove(api, battle):
    eid = battle["eid"]
    s = battle["state"]
    g1, hero = find(s, "Goblin 1"), find(s, "Hero")
    s = api.post(f"/api/combatants/{g1['id']}/conditions", {"name": "Frightened", "rounds": 1, "tick": "end"})
    s = api.post(f"/api/combatants/{hero['id']}/conditions", {"name": "Blessed", "rounds": 1, "tick": "end", "auto_expire": True})
    s = api.post(f"/api/combatants/{hero['id']}/conditions", {"name": "Prone"})
    sheet = api.get(f"/api/characters/{battle['hero']['id']}")["character"]
    assert {c["name"] for c in sheet["conditions"]} == {"Blessed", "Prone"}, "PC conditions live on the sheet"
    s = api.post(f"/api/encounters/{eid}/start")
    for _ in range(4):
        s = api.post(f"/api/encounters/{eid}/next")
    g1c = find(s, "Goblin 1")["conditions"]
    assert g1c[0]["expired"] and g1c[0]["rounds_left"] == 0, "expired effect is flagged, not silently removed"
    assert [c["name"] for c in find(s, "Hero")["conditions"]] == ["Prone"], "auto-expire effect removed (and logged)"
    assert any("Blessed on Hero expired and was removed" in l["message"] for l in s["log"])
    prone = find(s, "Hero")["conditions"][0]
    s = api.delete(f"/api/combatants/{hero['id']}/conditions/{prone['id']}")
    assert find(s, "Hero")["conditions"] == []
    api.delete(f"/api/combatants/{hero['id']}/conditions/{prone['id']}", expect=409)


def test_template_edit_does_not_change_existing_enemies(api, battle):
    gob = battle["goblin"]
    api.patch(f"/api/creatures/{gob['id']}", {"changes": {"max_hp": {"from": 7, "to": 50}, "ac": {"from": 15, "to": 20}}})
    s = api.get(f"/api/encounters/{battle['eid']}")
    g = find(s, "Goblin 1")
    assert (g["max_hp"], g["ac"]) == (7, 15) and g["statblock"]["max_hp"] == 7
    api.delete(f"/api/creatures/{gob['id']}")
    s = api.get(f"/api/encounters/{battle['eid']}")
    assert find(s, "Goblin 2")["hp"] == 7


def test_end_and_reopen(api, battle):
    eid = battle["eid"]
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/next")
    s = api.post(f"/api/encounters/{eid}/end")
    assert s["encounter"]["status"] == "ended"
    api.delete(f"/api/encounters/{eid}", expect=400)
    s = api.post(f"/api/encounters/{eid}/reopen")
    assert s["encounter"]["status"] == "active" and s["encounter"]["round"] == 1


# 9–10. Persistence across restarts --------------------------------------------------

def test_unfinished_encounter_survives_restart(data_dir):
    app1 = create_app({"DATA_DIR": data_dir})
    from tests.conftest import Api
    a = Api(app1.test_client())
    camp = a.campaign("Persistent")
    hero = a.character(camp["id"], name="Hero", max_hp=20)
    eid = a.encounter(camp["id"])["encounter"]["id"]
    a.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]], "quick": {"name": "Orc", "max_hp": 15, "count": 2}})
    s = a.post(f"/api/encounters/{eid}/start")
    s = a.post(f"/api/encounters/{eid}/next")
    s = a.post(f"/api/encounters/{eid}/next")
    s = a.post(f"/api/encounters/{eid}/next")
    orc = find(s, "Orc 2")
    s = a.post(f"/api/combatants/{orc['id']}/hp", {"op": "damage", "amount": 6})
    s = a.post(f"/api/combatants/{orc['id']}/conditions", {"name": "Poisoned", "rounds": 3})
    a.post(f"/api/encounters/{eid}/log", {"message": "The orc drinks something foul"})
    a.post(f"/api/characters/{hero['id']}/morality", {"title": "Saved a child", "good_delta": 10}, 201)
    a.post(f"/api/campaigns/{camp['id']}/journal", {"kind": "session", "body": "We met in a tavern"}, 201)
    before = a.get(f"/api/encounters/{eid}")

    # "Restart": a brand new app object reading the same database file.
    app2 = create_app({"DATA_DIR": data_dir})
    b = Api(app2.test_client())
    after = b.get(f"/api/encounters/{eid}")
    assert after["encounter"]["round"] == before["encounter"]["round"] == 2
    assert after["encounter"]["current_id"] == before["encounter"]["current_id"]
    assert [c["id"] for c in after["combatants"]] == [c["id"] for c in before["combatants"]]
    assert find(after, "Orc 2")["hp"] == 9 and find(after, "Orc 1")["hp"] == 15
    assert find(after, "Orc 2")["conditions"][0]["name"] == "Poisoned"
    assert after["log"] == before["log"]
    assert b.get(f"/api/characters/{hero['id']}/morality")["good"] == 10
    assert b.get(f"/api/campaigns/{camp['id']}/journal")["entries"][0]["body"] == "We met in a tavern"
    # and the restarted app can keep running the fight
    s = b.post(f"/api/encounters/{eid}/next")
    assert s["encounter"]["current_id"] != before["encounter"]["current_id"]


def test_theme_preference_persists(data_dir):
    from tests.conftest import Api
    Api(create_app({"DATA_DIR": data_dir}).test_client()).patch("/api/settings", {"theme": "light"})
    assert Api(create_app({"DATA_DIR": data_dir}).test_client()).get("/api/settings")["theme"] == "light"


# 11. Backup export / restore into an isolated environment ----------------------------

def _populated(api):
    camp = api.campaign("Exported")
    hero = api.character(camp["id"], name="Hero", max_hp=20)
    ev = api.post(f"/api/characters/{hero['id']}/morality", {"title": "Lied", "law_delta": -5}, 201)["events"][0]
    api.post(f"/api/morality/{ev['id']}/reverse")
    eid = api.encounter(camp["id"])["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]], "quick": {"name": "Wolf", "max_hp": 11, "count": 2}})
    hero_c = find(s, "Hero")
    api.post(f"/api/combatants/{hero_c['id']}/conditions", {"name": "Prone", "rounds": 2})
    api.post(f"/api/encounters/{eid}/start")
    s = api.post(f"/api/encounters/{eid}/next")
    api.post(f"/api/combatants/{find(s, 'Wolf 1')['id']}/hp", {"op": "damage", "amount": 4})
    j = api.post(f"/api/campaigns/{camp['id']}/journal",
                 {"kind": "npc", "title": "Old Marta", "links": [{"type": "character", "id": hero["id"]},
                                                                  {"type": "encounter", "id": eid}]}, 201)
    return camp, hero, eid, j


def test_backup_roundtrip_isolated(api, client, tmp_path):
    camp, hero, eid, _ = _populated(api)
    exported = client.get(f"/api/backup/export?campaign_id={camp['id']}")
    assert exported.status_code == 200
    raw = exported.data

    other = create_app({"DATA_DIR": str(tmp_path / "isolated"), "TESTING": True}).test_client()
    from tests.conftest import Api
    b = Api(other)
    untouched = b.campaign("Already here")
    rep = other.post("/api/backup/inspect", data={"file": (io.BytesIO(raw), "b.json")}, content_type="multipart/form-data")
    assert rep.status_code == 200, rep.get_data(as_text=True)
    rep = rep.get_json()
    assert rep["campaigns"][0]["counts"]["characters"] == 1 and not rep["campaigns"][0]["exists"]
    res = b.post("/api/backup/import", {"token": rep["token"], "decisions": {rep["campaigns"][0]["uid"]: "add"}})
    new_id = res["imported"][0]["id"]
    assert res["snapshot"].startswith("before-import")

    chars = b.get(f"/api/campaigns/{new_id}/characters")["characters"]
    assert chars[0]["name"] == "Hero" and chars[0]["uid"] == hero["uid"]
    m = b.get(f"/api/characters/{chars[0]['id']}/morality")
    assert len(m["events"]) == 2 and m["events"][1]["reverses_id"] == m["events"][0]["id"]
    enc = b.get(f"/api/campaigns/{new_id}/encounters")["encounters"][0]
    st = b.get(f"/api/encounters/{enc['id']}")
    assert st["encounter"]["round"] == 1 and find(st, "Wolf 1")["hp"] == 7
    cur = next(c for c in st["combatants"] if c["id"] == st["encounter"]["current_id"])
    orig = api.get(f"/api/encounters/{eid}")
    assert cur["name"] == next(c["name"] for c in orig["combatants"] if c["id"] == orig["encounter"]["current_id"])
    prone = find(st, "Hero")["conditions"][0]
    assert prone["encounter_id"] == enc["id"] and prone["tick_on"] == find(st, "Hero")["id"]
    entry = b.get(f"/api/campaigns/{new_id}/journal")["entries"][0]
    assert {l["type"] for l in entry["links"]} == {"character", "encounter"}
    assert b.get(f"/api/campaigns/{untouched['id']}/characters")["characters"] == []

    # Importing the same campaign again must not silently duplicate or replace.
    rep2 = other.post("/api/backup/inspect", data={"file": (io.BytesIO(raw), "b.json")},
                      content_type="multipart/form-data").get_json()
    assert rep2["campaigns"][0]["exists"]
    b.post("/api/backup/import", {"token": rep2["token"], "decisions": {rep2["campaigns"][0]["uid"]: "add"}}, expect=400)
    res = b.post("/api/backup/import", {"token": rep2["token"], "decisions": {rep2["campaigns"][0]["uid"]: "replace"}})
    camps = b.get("/api/campaigns")["campaigns"]
    assert sorted(c["name"] for c in camps) == ["Already here", "Exported"]


def test_corrupt_backups_rejected(api, client):
    _populated(api)
    raw = json.loads(client.get("/api/backup/export").data)
    raw["data"]["campaigns"][0]["name"] = "tampered"
    r = client.post("/api/backup/inspect", data={"file": (io.BytesIO(json.dumps(raw).encode()), "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and "checksum" in r.get_json()["error"]
    r = client.post("/api/backup/inspect", data={"file": (io.BytesIO(b"{not json"), "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/api/backup/inspect", data={"file": (io.BytesIO(b'{"format": "other"}'), "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


# 12. Save failures and conflicts -----------------------------------------------------

def test_stale_write_is_refused(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Shared", max_hp=20)
    api.set_char(ch, current_hp=12)            # another tab
    r = api.patch(f"/api/characters/{ch['id']}", {"changes": {"current_hp": {"from": 20, "to": 15}}}, expect=409)
    assert r["conflicts"] == {"current_hp": 12}
    assert api.get(f"/api/characters/{ch['id']}")["character"]["current_hp"] == 12
    # unrelated field from the same stale page still saves
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"notes": {"from": "", "to": "hi"}}})
    # retrying an already-applied change is harmless
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"notes": {"from": "", "to": "hi"}}})


def test_validation_errors_do_not_write(api):
    camp = api.campaign()
    ch = api.character(camp["id"])
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"level": {"from": 1, "to": 99}}}, expect=400)
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"level": {"from": 1, "to": "abc"}}}, expect=400)
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"nope": {"to": 1}}}, expect=400)
    # a batch with one bad field writes nothing
    api.patch(f"/api/characters/{ch['id']}", {"changes": {"name": {"from": "Hero", "to": "X"}, "ac": {"from": 10, "to": -4}}}, expect=400)
    assert api.get(f"/api/characters/{ch['id']}")["character"]["name"] == "Hero"


def test_database_error_rolls_back(api, app, monkeypatch):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Victim", max_hp=10)
    eid = api.encounter(camp["id"])["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"characters": [ch["id"]]})
    from app import combat

    real = combat.Ctx.log

    def boom(self, kind, message):
        if kind == "hp":
            raise sqlite3.OperationalError("disk I/O error")
        return real(self, kind, message)
    monkeypatch.setattr(combat.Ctx, "log", boom)
    r = api.post(f"/api/combatants/{s['combatants'][0]['id']}/hp", {"op": "damage", "amount": 5}, expect=500)
    assert "nothing was saved" in r["error"].lower()
    assert api.get(f"/api/characters/{ch['id']}")["character"]["current_hp"] == 10, "HP write rolled back with the log"


# 13. Campaign isolation ---------------------------------------------------------------

def test_campaigns_are_isolated(api):
    a, b = api.campaign("A"), api.campaign("B")
    ha = api.character(a["id"], name="Alice")
    api.character(b["id"], name="Bob")
    assert [c["name"] for c in api.get(f"/api/campaigns/{a['id']}/characters")["characters"]] == ["Alice"]
    enc_b = api.encounter(b["id"])["encounter"]["id"]
    api.post(f"/api/encounters/{enc_b}/combatants", {"characters": [ha["id"]]}, expect=400)
    api.post(f"/api/campaigns/{a['id']}/journal", {"title": "A note"}, 201)
    assert api.get(f"/api/campaigns/{b['id']}/journal")["entries"] == []
    jb = api.post(f"/api/campaigns/{b['id']}/journal", {"title": "B note"}, 201)["entry"]
    r = api.c.put(f"/api/journal/{jb['id']}/links", json={"links": [{"type": "character", "id": ha["id"]}]})
    assert r.status_code == 400
    assert api.get(f"/api/campaigns/{a['id']}/encounters")["encounters"] == []


def test_journal_search(api):
    camp = api.campaign()
    api.post(f"/api/campaigns/{camp['id']}/journal", {"kind": "location", "title": "Thornwall Keep", "body": "A ruined fort"}, 201)
    api.post(f"/api/campaigns/{camp['id']}/journal", {"kind": "npc", "title": "Brother Aldous", "body": "Lives near Thornwall"}, 201)
    s = api.post(f"/api/campaigns/{camp['id']}/journal", {"kind": "session"}, 201)["entry"]
    assert s["session_number"] == 1 and s["title"] == "Session 1"
    hits = api.get(f"/api/campaigns/{camp['id']}/journal?q=thornwall")["entries"]
    assert len(hits) == 2
    hits = api.get(f"/api/campaigns/{camp['id']}/journal?q=thornwall&kind=npc")["entries"]
    assert [h["title"] for h in hits] == ["Brother Aldous"]


def test_pages_render(api, client):
    assert client.get("/").status_code == 200  # welcome screen
    camp = api.campaign()
    ch = api.character(camp["id"], name="Hero")
    eid = api.encounter(camp["id"])["encounter"]["id"]
    for url in ("/", "/campaigns", "/characters", f"/characters/{ch['id']}", f"/characters/{ch['id']}/morality",
                "/morality", "/combat", f"/combat/{eid}", "/journal", "/creatures", "/settings"):
        r = client.get(url, follow_redirects=True)
        assert r.status_code == 200, url
    assert client.get("/characters/9999").status_code == 404
