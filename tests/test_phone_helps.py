"""From the phone, like the DM's map: healing and AC boosts from the sheet's attack rows (Lux's
Mend and Sheild of faith) go on your own side, and Mend Earth changes the squares you aim at."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

ATTACKS = [{"name": "Mend", "damage": "1d8", "notes": "Heal", "cooldown": 1},
           {"name": "Sheild of faith", "damage": "", "notes": "+2 ac to target", "cooldown": 3},
           {"name": "Bite", "damage": "1d8", "notes": "Damage"}]
SPELLS = [{"name": "Mend Earth: Raise Rocks", "effect": "buff", "terrain": "rock", "area": "20 ft square, range 30"}]


def setup(api, bm):
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, attacks=ATTACKS, spells=SPELLS, current_hp=10, max_hp=20)
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 30}}})
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    eid = bm["eid"]
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, by


def test_mend_and_shield_go_on_your_side(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    st = pa.get("/api/play/state")["character"]
    assert [a["ac"] for a in st["attacks"]] == [0, 2, 0] and st["attacks"][0]["heal"]
    # not on an enemy
    err = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]}, 403)
    assert "your side" in err["error"]
    r = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Aria"]["id"]]})   # on yourself
    assert r["cast"]["spell"] == "Mend" and api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"] > 10
    r = pa.post("/api/play/me/use", {"what": "attack", "index": 1, "targets": [by["Aria"]["id"]]})
    a = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    assert a["ac_bonus"] == 2
    # two actions used: no more
    pa.post("/api/play/me/use", {"what": "attack", "index": 2, "targets": [by["Bandit 1"]["id"]]}, 403)


def test_mend_earth_from_the_phone(api, battlemap):
    eid, by = setup(api, battlemap)
    pa, mid = battlemap["pa"], battlemap["mid"]
    me = tok(api.get(f"/api/maps/{mid}"), "Aria")
    api.post(f"/api/tokens/{me['id']}/move", {"x": 2, "y": 2, "free": True})
    pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": []}, 400)                       # aim it first
    err = pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": [], "cells": [[29, 7]]}, 400)  # too far
    assert "out of range" in err["error"]
    pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": [], "cells": [[5, 2], [6, 2], [5, 3], [6, 3]]})
    terrain = api.get(f"/api/maps/{mid}")["map"]["terrain"]
    assert {k for k, v in terrain.items() if v == "rock"} == {"5,2", "6,2", "5,3", "6,3"}
