"""Moves with a cooldown (Wide Slash: 3 turn cool down) and attacking only on your turn."""
import pytest

from tests.test_dice_map_players import remote


@pytest.fixture
def fight(app, api):
    camp = api.campaign()
    yam = api.character(camp["id"], name="Yamato", max_hp=25)
    yam = api.set_char(yam, attacks=[{"name": "Wide Slash", "bonus": "0", "damage": "2d12", "notes": "10ft 3 turn cool down"},
                                     {"name": "Parry", "bonus": "0", "damage": "1d4", "notes": ""}])
    eid = api.encounter(camp["id"], "Duel")["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"characters": [yam["id"]], "quick": {"name": "Ogre", "max_hp": 50, "count": 1}})
    by = {c["name"]: c for c in st["combatants"]}
    # Yamato goes first
    api.patch(f"/api/combatants/{by['Yamato']['id']}", {"changes": {"init_roll": {"from": None, "to": 20}}})
    api.patch(f"/api/combatants/{by['Ogre']['id']}", {"changes": {"init_roll": {"from": None, "to": 5}}})
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.81")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": yam["id"]})
    return {"eid": eid, "yam": yam, "by": by, "p": p}


def attack(p, char_id, key, expect=201):
    return p.post("/api/rolls", {"check": {"type": "attack", "key": key, "character_id": char_id}}, expect)


def test_cooldown_comes_from_the_notes_or_the_box(api, fight):
    st = api.get(f"/api/encounters/{fight['eid']}")
    atk = {a["name"]: a for a in next(c for c in st["combatants"] if c["name"] == "Yamato")["attacks"]}
    assert atk["Wide Slash"]["cooldown"] == 3 and atk["Parry"]["cooldown"] == 0
    me = fight["p"].get("/api/play/state")["character"]
    assert [a["cooldown"] for a in me["attacks"]] == [3, 0]


def test_players_attack_only_on_their_turn_and_moves_recharge(api, fight):
    eid, p, yid = fight["eid"], fight["p"], fight["yam"]["id"]
    attack(p, yid, 0)  # no fight running yet: anything goes, and no cooldown starts
    assert p.get("/api/play/state")["character"]["attacks"][0]["recharging"] == 0
    api.post(f"/api/encounters/{eid}/start")
    assert p.get("/api/play/state")["character"]["my_turn"] is True
    attack(p, yid, 0)  # Wide Slash on Yamato's turn: starts recharging
    me = p.get("/api/play/state")["character"]
    assert me["attacks"][0]["recharging"] == 4 and "Wide Slash recharging" in me["conditions"]
    r = attack(p, yid, 0, 400)
    assert "recharging" in r["error"]
    attack(p, yid, 1)  # other moves still work
    p.post("/api/rolls", {"check": {"type": "damage", "key": 0, "character_id": yid}}, 201)  # its damage after the hit is fine
    api.post(f"/api/encounters/{eid}/next")  # the Ogre's turn
    assert p.get("/api/play/state")["character"]["my_turn"] is False
    r = attack(p, yid, 1, 403)
    assert "not your turn" in r["error"]
    p.post("/api/rolls", {"check": {"type": "save", "key": "dex", "character_id": yid}}, 201)  # saves are any time
    # three more of Yamato's turns, then it's ready
    for turn in range(3):
        api.post(f"/api/encounters/{eid}/next")  # Yamato's turn
        attack(p, yid, 0, 400)
        api.post(f"/api/encounters/{eid}/next")  # the Ogre's turn
    api.post(f"/api/encounters/{eid}/next")  # Yamato's 4th turn since: ready
    assert p.get("/api/play/state")["character"]["attacks"][0]["recharging"] == 0
    attack(p, yid, 0)


def test_dm_starts_a_cooldown_from_the_map_or_combat(api, fight):
    eid, ogre = fight["eid"], fight["by"]["Ogre"]
    api.post(f"/api/encounters/{eid}/start")
    st = api.post(f"/api/combatants/{ogre['id']}/cooldown", {"name": "Boulder toss", "turns": 2})
    o = next(c for c in st["combatants"] if c["name"] == "Ogre")
    cd = next(x for x in o["conditions"] if x.get("cooldown") == "Boulder toss")
    assert cd["rounds_left"] == 3 and cd["auto_expire"] and cd["tick_on"] == ogre["id"]
    api.post(f"/api/combatants/{ogre['id']}/cooldown", {"name": "Boulder toss", "turns": 2}, 400)
    assert any("Ogre used Boulder toss" in e["message"] for e in st["log"])
