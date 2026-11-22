"""2026-11-09: Steven Voss (Harlan's father, a level 18 artificer boss) and his relay drones:
a boss's summons fight on the boss's side; the drones cast his spells again on anyone it hit within
30 ft of them; and a spell someone else casts near a drone can be cast back by Steven once."""
from app import voss
from tests.test_clone_parry import setup
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

DRONES = {"name": "Deploy Drones", "effect": "buff", "level": 0, "summon": "Voss Drone", "summon_count": 2, "relay": True}
ZAP = {"name": "Arc Pulse", "effect": "damage", "level": 1, "dice": "5", "damage_type": "lightning"}  # always lands, 5 damage


def _fight(api, bm):
    eid, by = setup(api, bm)
    api.post("/api/creatures", {"name": "Voss Drone", "max_hp": 12, "ac": 15, "attacks": "Zap: +5 to hit, 1d6 lightning damage"}, 201)
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 20}}})
    api.post(f"/api/encounters/{eid}/start")
    steven = by["Bandit 1"]
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": steven["id"], "spell": DRONES, "targets": []})
    drones = [c for c in st["combatants"] if c["name"].startswith("Voss Drone")]
    m = api.get(f"/api/maps/{bm['mid']}")
    for name, x, y in (("Aria", 2, 2), ("Bandit 2", 12, 2), ("Bandit 1", 16, 6), ("Voss Drone 1", 3, 3), ("Voss Drone 2", 19, 7)):
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    return eid, by, steven, drones


def test_boss_drones_fight_on_his_side(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    assert len(drones) == 2
    for d in drones:
        assert d["kind"] == "enemy" and d["follows"] == steven["id"] and d["statblock"]["relay"] is True
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert tok(m, "Voss Drone 1")["kind"] == "enemy"


def test_drone_near_the_target_echoes_his_spell(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": steven["id"], "spell": ZAP, "targets": [by["Aria"]["id"]]})
    aria = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert aria["hp"] == 10, "5 from Steven and 5 from the drone next to her; the far drone is out of reach"
    summary = st["cast"]["summary"]
    assert "Voss Drone 1 echoes it" in summary and "Voss Drone 2" not in summary
    assert any(t.get("echo") for t in st["cast"]["targets"])
    # one take-back undoes the echo too
    api.post(f"/api/encounters/{eid}/casts/{st['cast']['cast_id']}/undo", {})
    aria = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    assert aria["hp"] == 20


def test_a_dead_drone_echoes_nothing(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    api.post(f"/api/combatants/{drones[0]['id']}/hp", {"op": "damage", "amount": 50})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": steven["id"], "spell": ZAP, "targets": [by["Aria"]["id"]]})
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == 15


def test_spell_cast_near_a_drone_can_be_cast_back_once(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    frost = {"name": "Frost Spit", "effect": "damage", "level": 0, "dice": "3", "damage_type": "cold"}
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": frost, "targets": [by["Bandit 2"]["id"]]})
    assert "Steven" not in st["cast"]["summary"] and "records Frost Spit" in st["cast"]["summary"]
    me = next(c for c in st["combatants"] if c["id"] == steven["id"])
    copied = me["statblock"]["copied"]
    assert [c["name"] for c in copied] == ["Frost Spit (copied)"] and copied[0]["copied"] is True
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": steven["id"], "spell": copied[0], "targets": [by["Aria"]["id"]]})
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == 14, "3 from Steven, 3 echoed by the drone next to her"
    assert next(c for c in st["combatants"] if c["id"] == steven["id"])["statblock"]["copied"] == []
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": steven["id"], "spell": copied[0], "targets": [by["Aria"]["id"]]}, 400)
    assert "already been cast back" in err["error"]


def test_far_from_every_drone_nothing_is_copied(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    m = api.get(f"/api/maps/{battlemap['mid']}")
    api.post(f"/api/tokens/{tok(m, 'Voss Drone 1')['id']}/move", {"x": 19, "y": 0, "free": True})
    frost = {"name": "Frost Spit", "effect": "damage", "level": 0, "dice": "3"}
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": frost, "targets": [by["Bandit 2"]["id"]]})
    assert "records" not in st["cast"]["summary"]
    assert not next(c for c in st["combatants"] if c["id"] == steven["id"])["statblock"].get("copied")


def test_steven_goes_into_the_library_with_his_goggles(app):
    from app.db import get_db
    with app.app_context():
        conn = get_db()
        ids = voss.add_to_library(conn, app.config["UPLOAD_DIR"])
        again = voss.add_to_library(conn, app.config["UPLOAD_DIR"])  # running it twice updates, never duplicates
        conn.commit()
        assert ids == again
        st = conn.execute("SELECT * FROM creatures WHERE id = ?", (ids["Steven Voss"],)).fetchone()
        assert st["boss"] == 1 and st["portrait"] == "voss-steven-voss.png" and "Level 18 Artificer" in st["creature_type"]
        assert "summon 2 Voss Drone, relay" in st["spells"] and "Titan Arm" in st["attacks"]
        assert conn.execute("SELECT count(*) FROM creatures WHERE name = 'Voss Drone'").fetchone()[0] == 1


def _boss_with_a_copy(api, bm):
    """A library boss (2 legendary actions) whose drones aren't on the map: they hear every spell."""
    eid, by = setup(api, bm)
    api.post("/api/creatures", {"name": "Voss Drone", "max_hp": 12, "ac": 15}, 201)
    cr = api.post("/api/creatures", {"name": "Steven", "max_hp": 190, "ac": 19, "boss": True, "legendary_per_round": 2,
                                     "legendary": "Drone Zap: +11 to hit, 2d6 lightning damage"}, 201)
    st = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["creature"]["id"]})
    boss = next(c for c in st["combatants"] if c["name"] == "Steven")
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": boss["id"]})
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": boss["id"], "spell": DRONES, "targets": []})
    frost = {"name": "Frost Spit", "effect": "damage", "level": 0, "dice": "3", "damage_type": "cold"}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": frost, "targets": [by["Bandit 2"]["id"]]})
    return eid, by, next(c for c in st["combatants"] if c["id"] == boss["id"])


def test_copied_spell_remembers_a_look_for_the_map(api, battlemap):
    eid, by, steven, drones = _fight(api, battlemap)
    frost = {"name": "Frost Spit", "effect": "damage", "level": 0, "dice": "3", "damage_type": "cold"}
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": frost, "targets": [by["Bandit 2"]["id"]]})
    me = next(c for c in st["combatants"] if c["id"] == steven["id"])
    assert me["statblock"]["copied"][0]["look"] == "frost"


def test_copied_spell_as_a_legendary_action(api, battlemap):
    eid, by, me = _boss_with_a_copy(api, battlemap)
    assert me["boss"]["per_round"] == 2 and me["boss"]["left"] == 2
    spell = me["statblock"]["copied"][0]
    # not on his own turn
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": me["id"]})
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": me["id"], "spell": spell, "targets": [by["Aria"]["id"]], "legendary": True}, 400)
    assert "not its own" in err["error"]
    still = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["id"] == me["id"])
    assert still["statblock"]["copied"], "a refused legendary cast doesn't use the copy up"
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": me["id"], "spell": spell, "targets": [by["Aria"]["id"]], "legendary": True})
    boss = next(c for c in st["combatants"] if c["id"] == me["id"])
    assert boss["boss"]["left"] == 1 and boss["statblock"]["copied"] == []
    assert any("legendary action: Frost Spit" in l["message"] for l in st["log"])


# ---- phase 2 shoves and Shocked, Metal Bend walls -------------------------------------------------

def _two_on_a_map(api, bm):
    eid, by = setup(api, bm)
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 20}}})
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    m = api.get(f"/api/maps/{bm['mid']}")
    for name, x, y in (("Aria", 6, 3), ("Bandit 1", 5, 3), ("Bandit 2", 0, 7)):
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    api.post(f"/api/encounters/{eid}/start")
    return eid, by


def test_a_hit_with_push_shoves_them_away_and_pull_drags_them_in(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Aria"]["id"]], "name": "Shocked", "rounds": 1,
                                                    "caster_id": by["Bandit 1"]["id"], "push": 20})
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert (tok(m, "Aria")["x"], tok(m, "Aria")["y"]) == (10, 3), "20 ft straight away from him"
    log = " ".join(x["message"] for x in api.get(f"/api/encounters/{eid}")["log"])
    assert "Aria is shoved 20 ft by Bandit 1" in log
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Aria"]["id"]], "name": "Knocked back", "caster_id": by["Bandit 1"]["id"], "push": -30})
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert (tok(m, "Aria")["x"], tok(m, "Aria")["y"]) == (6, 3), "pulled back in, stopping next to him (not on top)"
    aria = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    assert not any(c["name"] == "Knocked back" for c in aria["conditions"]), "a plain shove leaves no condition"


def test_a_shove_stops_at_a_wall(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": STEEL, "targets": [],
                                             "map_id": battlemap["mid"], "cells": [[8, 3]], "force": True})
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Aria"]["id"]], "name": "Knocked back", "caster_id": by["Bandit 1"]["id"], "push": 30})
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert m["map"]["terrain"].get("8,3") == "bulkhead" and tok(m, "Aria")["x"] == 7, "stopped by his own steel wall"


def test_shocked_costs_an_action_on_their_next_turn(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Aria"]["id"]], "name": "Shocked", "rounds": 1, "caster_id": by["Bandit 1"]["id"]})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    me = battlemap["pa"].get("/api/play/state")["character"]
    assert me["actions"]["limit"] == 1, me["actions"]


STEEL = {"name": "Metal Bend", "effect": "buff", "level": 0, "terrain": "steel", "area": "30 ft line, range 60"}


def test_metal_bend_walls_two_at_once_and_the_oldest_folds_down(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    cast = lambda cells: api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": STEEL, "targets": [],
                                                                 "map_id": battlemap["mid"], "cells": cells, "force": True})
    st = cast([[12, y] for y in range(0, 6)])
    assert "steel wall" in st["cast"]["summary"]
    terr = api.get(f"/api/maps/{battlemap['mid']}")["map"]["terrain"]
    assert all(terr.get(f"12,{y}") == "bulkhead" for y in range(6))
    cast([[15, y] for y in range(0, 6)])
    st = cast([[2, y] for y in range(0, 3)] + [[6, 3]])  # (6,3) is under Aria: no wall there
    assert "folds his oldest wall back down" in st["cast"]["summary"]
    terr = api.get(f"/api/maps/{battlemap['mid']}")["map"]["terrain"]
    assert not any(terr.get(f"12,{y}") for y in range(6)), "the first wall is gone"
    assert all(terr.get(f"15,{y}") == "bulkhead" for y in range(6)) and terr.get("2,0") == "bulkhead"
    assert "6,3" not in terr


def test_magnet_pull_drags_all_the_way_and_hits_heroes_on_the_way(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    m = api.get(f"/api/maps/{battlemap['mid']}")
    for name, x, y in (("Bandit 1", 5, 3), ("Aria", 9, 3), ("Bandit 2", 16, 1)):
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Bandit 2"]["id"]], "name": "Shocked", "rounds": 1,
                                                    "caster_id": by["Bandit 1"]["id"], "push": -999})
    st = api.get(f"/api/encounters/{eid}")
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert (tok(m, "Bandit 2")["x"], tok(m, "Bandit 2")["y"]) == (6, 3), "dragged right up beside him, past Aria"
    assert (tok(m, "Aria")["x"], tok(m, "Aria")["y"]) == (9, 3)
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == 16, "4 damage from the impact"
    log = " ".join(x["message"] for x in st["log"])
    assert "Bandit 2 slams into Aria" in log and "pulled 50 ft" in log


def test_magnet_pull_stops_at_a_monster_in_the_way(api, battlemap):
    eid, by = _two_on_a_map(api, battlemap)
    m = api.get(f"/api/maps/{battlemap['mid']}")
    for name, x, y in (("Bandit 1", 5, 3), ("Bandit 2", 9, 3), ("Aria", 14, 3)):
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    api.post(f"/api/encounters/{eid}/conditions", {"targets": [by["Aria"]["id"]], "name": "Knocked back",
                                                    "caster_id": by["Bandit 1"]["id"], "push": -999})
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert tok(m, "Aria")["x"] == 10, "only heroes get flown through"
    assert next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 2")["hp"] == 11
