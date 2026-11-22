"""2026-11-09: Lux's Mend is a cantrip (no slot, same cooldown); Yamato's Echo Teleport (pick a clone,
he teleports to its spot and they swap places, 15 ft of movement, no action) replaces Phantasmal force;
and the laboratory: five floors that get harder, three healing-and-money lockers a floor, and on the top
floor the Head Researcher and the only magic item (one rare one). Prison chests give fewer magic items."""
import random

import pytest

from app import loot as LOOT
from app.dungeon import LAB_FLOORS, generate, path_len
from app.monster_book import BY_NAME
from app.prison_monsters import LAB_NAMES, TACTICS
from tests.test_clone_parry import setup
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

SUMMON = {"name": "Echo Knight", "effect": "buff", "level": 0, "summon": "Yamato clone", "summon_max": 3}
TELEPORT = {"name": "Echo Teleport", "effect": "buff", "level": 0, "clone_swap": True}


# ---- Echo Teleport -------------------------------------------------------------------------------

def _fight_with_clone(api, bm):
    eid, by = setup(api, bm)
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, spells=[SUMMON, TELEPORT])
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 20}}})
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    clone = next(c for c in st["combatants"] if c["name"].startswith("Yamato clone"))
    m = api.get(f"/api/maps/{bm['mid']}")
    api.post(f"/api/tokens/{tok(m, 'Aria')['id']}/move", {"x": 2, "y": 2, "free": True})
    api.post(f"/api/tokens/{tok(m, 'Yamato clone')['id']}/move", {"x": 16, "y": 4, "free": True})
    return eid, by, clone


def test_teleport_swaps_him_with_the_clone_for_15_ft_and_no_action(api, battlemap):
    eid, by, clone = _fight_with_clone(api, battlemap)
    pa = battlemap["pa"]
    me = pa.get("/api/play/state")["character"]
    row = next(s for s in me["spells"] if s["name"] == "Echo Teleport")
    assert row["clone_swap"] and me["move"]["left"] == 30 and me["actions"]["left"] == 1  # (summoning used one)
    r = pa.post("/api/play/me/teleport", {"spell": row["index"], "clone": clone["id"], "op_id": "tp1"})
    assert r["teleport"] == {"name": "Echo Teleport", "clone": clone["name"]}
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert (tok(m, "Aria")["x"], tok(m, "Aria")["y"]) == (16, 4), "he's where the clone was"
    assert (tok(m, "Yamato clone")["x"], tok(m, "Yamato clone")["y"]) == (2, 2), "and the clone where he was"
    me = r["character"]
    assert me["move"]["left"] == 15 and me["actions"]["left"] == 1, "15 ft of movement, no action"
    # he walks on from the new spot: 15 ft left
    t = tok(m, "Aria")
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": 19, "y": 4})
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": 12, "y": 4}, 403)  # 20 ft from where he landed
    # no movement left for another teleport
    err = pa.post("/api/play/me/teleport", {"spell": row["index"], "clone": clone["id"], "op_id": "tp2"}, 403)
    assert "15 ft" in err["error"]
    assert any("swap places" in line["message"] for line in api.get(f"/api/encounters/{eid}")["log"])


def test_teleport_only_on_his_turn_and_to_his_own_clone(api, battlemap):
    eid, by, clone = _fight_with_clone(api, battlemap)
    pa, pb = battlemap["pa"], battlemap["pb"]
    pb.post("/api/play/me/teleport", {"spell": 1, "clone": clone["id"]}, 400)            # Bram has no such ability
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    err = pa.post("/api/play/me/teleport", {"spell": 1, "clone": clone["id"], "op_id": "x1"}, 403)
    assert "your own turn" in err["error"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    pa.post("/api/play/me/teleport", {"spell": 1, "clone": by["Bandit 1"]["id"], "op_id": "x2"}, 403)
    pa.post("/api/play/me/teleport", {"spell": 0, "clone": clone["id"], "op_id": "x3"}, 400)   # the summon row doesn't teleport
    # the DM's cast button explains instead of doing nothing
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 1, "targets": [clone["id"]]}, 400)
    assert "player's screen" in err["error"]


# ---- Mend as a cantrip ---------------------------------------------------------------------------

def test_mend_cantrip_heals_without_a_slot_and_keeps_its_cooldown(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    mend = {"name": "Mend", "level": 0, "effect": "heal", "dice": "2d20+6", "cooldown": 1}
    api.set_char(aria, spells=[mend], current_hp=5, max_hp=60, spell_slots={})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = pa.post("/api/play/cast", {"spell": 0, "targets": [battlemap["a"]["id"]], "op_id": "m1"})
    assert r["cast"]["slot"] == 0 and r["character"]["current_hp"] >= 5 + 8
    assert next(s for s in r["character"]["spells"] if s["name"] == "Mend")["recharging"], "the cooldown still applies"
    pa.post("/api/play/cast", {"spell": 0, "targets": [battlemap["a"]["id"]], "op_id": "m2"}, 400)


# ---- the laboratory: map ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(1, 25))
def test_five_floors_join_up_and_the_top_has_no_lift(seed):
    for level in range(1, LAB_FLOORS + 1):
        g = generate("lab", seed, level)
        t = g["terrain"]
        assert "stone" not in t.values() and {"metal", "bulkhead", "blastdoor"} <= set(t.values())
        for r in g["rooms"]:
            assert any(path_len(t, g["start"], [a, b], g["cols"], g["rows"]) is not None
                       for a in range(r["box"][0], r["box"][2] + 1) for b in range(r["box"][1], r["box"][3] + 1)), r["name"]
        if level < LAB_FLOORS:
            assert t[f"{g['exit'][0]},{g['exit'][1]}"] == "stairs" and "floor " + str(level) in g["name"]
        else:
            assert g["exit"] is None and "stairs" not in t.values() and "(top)" in g["name"]
            assert any(r["name"] == "The Director's Office" and r["kind"] == "boss" for r in g["rooms"])


def test_lab_enemies_stats_tactics_and_drops_are_healing_and_money():
    assert len(LAB_NAMES) == 7 and set(LAB_NAMES) <= set(TACTICS)  # (the Director joined 2026-11-15)
    assert BY_NAME["The Director"]["boss"] and BY_NAME["The Director"]["phase2"] and BY_NAME["Head Researcher"]["boss"]
    for n in LAB_NAMES:
        for seed in range(30):
            for it in LOOT.roll_drop(n, seed):
                assert it.get("coins") or it["key"] in ("patch", "stim", "trauma"), (n, it)


# ---- the laboratory: loot ------------------------------------------------------------------------

def test_lab_lockers_hold_only_healing_and_money_and_the_safe_one_rare_magic_item():
    heal = {"Med-gel patch", "Stim injector", "Trauma kit"}
    for seed in range(200):
        items = LOOT.roll_chest("lab", seed)
        assert any(i.get("coins") for i in items)
        assert all(i.get("coins") or i["name"] in heal for i in items) and not any(i.get("magic") for i in items)
    for seed in range(50):
        safe = LOOT.roll_chest("labprize", seed, magic_on=False)  # the one magic item ignores the switch
        assert len(safe) == 1 and safe[0]["magic"] and safe[0]["rarity"] == "rare"


def test_prison_chests_give_fewer_magic_items():
    assert LOOT.CHESTS["legendary"]["magic"] <= 20 and LOOT.CHESTS["experimental"]["magic"] <= 10
    assert LOOT.CHESTS["medical"]["magic"] == 0 and LOOT.CHESTS["supply"]["magic"] == 0


def _names(st):
    return [t["name"].rsplit(" ", 1)[0] if t["name"][-1].isdigit() else t["name"] for t in st["tokens"] if t["kind"] == "enemy"]


def test_lab_floors_ramp_up_with_three_lockers_and_the_safe_at_the_top(api, joined):
    camp = joined["camp"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "lab"}, 201)
    floors = [st]
    for _ in range(LAB_FLOORS - 1):
        nxt = api.post(f"/api/maps/{floors[-1]['map']['id']}/next-level", {})["next_level"]
        floors.append(api.get(f"/api/maps/{nxt['map_id']}"))
    assert [f["map"]["dungeon"]["level"] for f in floors] == [1, 2, 3, 4, 5]
    cr = {n: eval(BY_NAME[n]["cr"].replace("/", "/1.0/") if "/" in BY_NAME[n]["cr"] else BY_NAME[n]["cr"]) for n in LAB_NAMES}  # noqa: S307
    totals = []
    for f in floors:
        names = _names(f)
        assert names and set(names) <= set(LAB_NAMES)
        assert all(t["portrait"] and t["portrait"].startswith("lab-") for t in f["tokens"] if t["kind"] == "enemy")
        totals.append(sum(cr[n] for n in names))
        kinds = [c["kind"] for c in f["map"]["chests"]]
        assert kinds.count("lab") == 3
    assert totals == sorted(totals) and totals[-1] > 3 * totals[0], f"it ramps up: {totals}"
    assert "The Director" in _names(floors[-1]) and not any("The Director" in _names(f) for f in floors[:-1])
    assert [c["kind"] for c in floors[-1]["map"]["chests"]].count("labprize") == 1
    assert not any(c["kind"] == "labprize" for f in floors[:-1] for c in f["map"]["chests"])
    # no way up from the top floor
    err = api.post(f"/api/maps/{floors[-1]['map']['id']}/next-level", {}, 400)
    assert "top floor" in err["error"]
    # a new layout restocks a floor the same way
    st2 = api.post(f"/api/maps/{floors[1]['map']['id']}/reroll", {})
    assert [c["kind"] for c in st2["map"]["chests"]].count("lab") == 3 and set(_names(st2)) <= set(LAB_NAMES)


def test_lab_shows_on_the_maps_page():
    from app.dungeon import sample_thumbs
    assert any(t["key"] == "lab" and t["name"] == "Laboratory" for t in sample_thumbs())


def test_random_lab_rolls_stay_in_the_pool():
    rnd = random.Random(3)
    for _ in range(100):
        for it in LOOT.roll_chest("lab", rnd.randrange(1, 10 ** 9)):
            assert it.get("coins") or it.get("key") in ("patch", "stim", "trauma")
