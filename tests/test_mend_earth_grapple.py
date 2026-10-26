"""Moni's moves: Mend Earth (raise solid rock / mend the ground on the battle map),
Punch, and Grapple (damage, and Grappled: can't move until a Strength save breaks it)."""
from app import dice
from app.spell_book import find
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded


def square(x, y, n=4):
    return [[x + i, y + j] for i in range(n) for j in range(n)]


def setup(api, battlemap):
    aria = battlemap["a"]
    api.set_char(api.get(f"/api/characters/{aria['id']}")["character"], level=4,
                 abilities={"str": 16, "dex": 12, "con": 15, "int": 10, "wis": 15, "cha": 7},
                 attacks=[{"name": "Punch", "bonus": "+5", "damage": "1d6+3 bludgeoning"},
                          {"name": "Grapple", "bonus": "+5", "damage": "1d6+3 bludgeoning", "condition": "Grappled"}],
                 spells=[find("Mend Earth: Raise Rocks"), find("Mend Earth: Mend")])
    st = api.get(f"/api/encounters/{battlemap['eid']}")
    return {c["name"]: c for c in st["combatants"]}


def test_grapple_row_reaches_combat_as_a_move(api, battlemap):
    by = setup(api, battlemap)
    atk = {a["name"]: a for a in by["Aria"]["attacks"]}
    assert atk["Punch"]["cast"] is None, "a plain punch is an ordinary attack"
    g = atk["Grapple"]["cast"]
    assert g["condition"] == "Grappled" and g["dice"] == "1d6+3" and g["attack_bonus"] == 5
    assert g["escape"] == "str" and g["dc"] == 13 and g["damage_type"] == "bludgeoning"


def test_grapple_hits_for_damage_and_holds_until_a_save(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    by = setup(api, battlemap)
    eid = battlemap["eid"]
    spec = next(a for a in by["Aria"]["attacks"] if a["name"] == "Grapple")["cast"]
    loaded.next(15, 4)  # 15 + 5 = 20 vs AC 10; 1d6 = 4 -> 7
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    b1 = next(c for c in st["combatants"] if c["name"] == "Bandit 1")
    assert b1["hp"] == 4, "7 damage"
    assert st["cast"]["move"] and st["cast"]["summary"].startswith("Aria uses Grapple")
    held = next(x for x in b1["conditions"] if x["name"] == "Grappled")
    assert held["save"] == {"ability": "str", "dc": 13} and "can't move" in held["note"]
    # a miss leaves no grapple
    loaded.next(1)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 2"]["id"]]})
    assert not any(x["name"] == "Grappled" for x in next(c for c in st["combatants"] if c["name"] == "Bandit 2")["conditions"])
    # at the end of its turn the bandit tries to break free: 5 fails, then 20 succeeds
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    loaded.next(5)
    st = api.post(f"/api/encounters/{eid}/next")
    assert any(x["name"] == "Grappled" for x in next(c for c in st["combatants"] if c["name"] == "Bandit 1")["conditions"])
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    loaded.next(20)
    st = api.post(f"/api/encounters/{eid}/next")
    assert not any(x["name"] == "Grappled" for x in next(c for c in st["combatants"] if c["name"] == "Bandit 1")["conditions"])
    assert any("Bandit 1 shakes off Grappled" in e["message"] for e in st["log"])


def test_grapple_damage_can_be_changed_on_the_sheet(api, battlemap):
    setup(api, battlemap)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    rows = [dict(r) for r in aria["attacks"]]
    rows[1]["damage"] = "2d8+1 bludgeoning"
    api.set_char(aria, attacks=rows)
    st = api.get(f"/api/encounters/{battlemap['eid']}")
    g = next(a for a in next(c for c in st["combatants"] if c["name"] == "Aria")["attacks"] if a["name"] == "Grapple")
    assert g["cast"]["dice"] == "2d8+1"


def test_mend_earth_raises_rock_but_not_under_anyone_then_mends_it(api, battlemap):
    by = setup(api, battlemap)
    eid, mid = battlemap["eid"], battlemap["mid"]
    m = api.get(f"/api/maps/{mid}")
    for i, t in enumerate(m["tokens"]):  # everyone off to the bottom row, then Bandit 1 into the middle
        api.post(f"/api/tokens/{t['id']}/move", {"x": 9 - i, "y": 7})
    b1 = tok(m, "Bandit 1")
    api.post(f"/api/tokens/{b1['id']}/move", {"x": 3, "y": 3})
    x0, y0 = 3, 3
    cells = square(2, 2)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [], "map_id": mid, "cells": cells})
    assert "raises solid rock over 15 squares" in st["cast"]["summary"], st["cast"]["summary"]
    terrain = api.get(f"/api/maps/{mid}")["map"]["terrain"]
    assert f"{x0},{y0}" not in terrain, "no rock under the bandit"
    assert sum(v == "rock" for v in terrain.values()) == 15
    # put some rubble down too, then Mend clears both
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[0, 0]], "value": "rubble"})
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[1, 0]], "value": "water"})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 1, "targets": [], "map_id": mid,
                                                  "cells": cells + [[0, 0], [1, 0]]})
    assert "mends 16 squares" in st["cast"]["summary"]
    terrain = api.get(f"/api/maps/{mid}")["map"]["terrain"]
    assert terrain == {"1,0": "water"}, "water isn't broken ground"


def test_mend_earth_needs_the_map(api, battlemap):
    by = setup(api, battlemap)
    err = api.post(f"/api/encounters/{battlemap['eid']}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []}, 400)
    assert "battle map" in err["error"]


def test_players_cant_walk_into_or_through_rock_or_move_while_grappled(api, battlemap):
    by = setup(api, battlemap)
    mid, camp, pa = battlemap["mid"], battlemap["camp"], battlemap["pa"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    me = tok(api.get(f"/api/maps/{mid}"), "Aria")
    api.post(f"/api/tokens/{me['id']}/move", {"x": 0, "y": 0})
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[2, 0], [2, 1], [2, 2]], "value": "rock"})
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 2, "y": 0}, 403)
    assert "rock" in r["error"].lower()
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 4, "y": 0}, 403)  # through it
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 0, "y": 3})        # around is fine
    api.post(f"/api/combatants/{by['Aria']['id']}/conditions", {"name": "Grappled"})
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 0, "y": 4}, 403)
    assert "Grappled" in r["error"]
