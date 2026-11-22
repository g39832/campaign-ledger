"""The abandoned (sci-fi) prison: its layout and sealed rooms, its ten enemies (stat blocks, pictures,
tactics), chests and loot (rarity, locks, rolled once, taken once, onto the sheet, carry weight,
saved in backups), magic items from the DM's list, sealed doors, enemy drops, and enemies that take
their own turn."""
import json
import random

import pytest

from app import loot as LOOT
from app.ai import area_cells, parse_moves
from app.dungeon import generate, path_len
from app.monster_book import BY_NAME
from app.prison_monsters import NAMES, TACTICS
from tests.test_dice_map_players import joined, remote  # noqa: F401  (fixtures)


# ---- the map ----------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(1, 40))
def test_layout_joins_up_and_every_sealed_room_opens_onto_it(seed):
    g = generate("futureprison", seed)
    assert path_len(g["terrain"], g["start"], g["exit"], g["cols"], g["rows"]) is not None
    sealed = [r for r in g["rooms"] if r.get("door")]
    assert {r["name"] for r in sealed} == {"Hidden armory", "Smugglers' stash", "Restricted vault", "Experimental lab"}
    for r in sealed:
        x, y = r["door"]
        assert g["terrain"][f"{x},{y}"] == ("sealed" if r["needs"] else "panel")
        t = dict(g["terrain"], **{f"{x},{y}": "blastdoor"})
        assert any(path_len(t, g["start"], [a, b], g["cols"], g["rows"]) is not None
                   for a in range(r["box"][0], r["box"][2] + 1) for b in range(r["box"][1], r["box"][3] + 1))
    kinds = set(g["terrain"].values())
    assert {"metal", "bulkhead", "blastdoor", "forcefield", "redlight", "turret", "terminal"} <= kinds
    assert "stone" not in kinds and "wall" not in kinds, "all steel, no stone"


def test_old_prison_is_unchanged():
    g = generate("prison", 3)
    assert "metal" not in g["terrain"].values() and not any(r.get("door") for r in g["rooms"])


# ---- enemies ----------------------------------------------------------------------------------

def test_ten_enemies_with_their_own_stats_moves_and_tactics():
    from app.prison_monsters import LAB_NAMES, SILO_NAMES
    assert len(NAMES) == 10 and set(NAMES) | set(LAB_NAMES) | set(SILO_NAMES) == set(TACTICS)  # (the lab's and silo's have tactics too)
    blocks = [BY_NAME[n] for n in NAMES]
    assert len({(b["max_hp"], b["ac"], b["cr"]) for b in blocks}) == 10, "different health, defense and difficulty"
    assert BY_NAME["Prison Warden"]["boss"] and BY_NAME["Prison Warden"]["phase2"]
    for b in blocks:
        multi, moves = parse_moves(b["attacks"])
        assert moves, b["name"]
        for mv in moves:
            assert mv["dmg"] and (mv["bonus"] is not None or mv["save"]), (b["name"], mv)
    _, sentinel = parse_moves(BY_NAME["Sentinel Unit"]["attacks"])
    cannon = next(m for m in sentinel if m["name"] == "Suppression Cannon")
    assert cannon["kind"] == "area" and cannon["shape"] == "line" and cannon["recharge"] == 5 and cannon["save"] == (15, "dex")
    baton = next(m for m in parse_moves(BY_NAME["Riot Suppressor"]["attacks"])[1] if m["name"] == "Stun Baton")
    assert baton["cond"] == "Stunned" and baton["save"] == (12, "con") and baton["look"] == "sparks"
    assert parse_moves(BY_NAME["Inmate Enforcer"]["attacks"])[0] == 2


def test_portraits_are_distinct_pictures():
    from app.prison_monsters import draw
    pics = {n: draw(n, 64).tobytes() for n in NAMES}
    assert len(set(pics.values())) == 10


def test_area_shapes():
    cone = area_cells("cone", 15, 5, 0.5, 5.5, 5.5, 5.5)
    assert (3, 5) in cone and (1, 5) in cone and (3, 9) not in cone
    line = area_cells("line", 30, 5, 0.5, 0.5, 10.5, 0.5)
    assert {(x, 0) for x in range(1, 6)} <= line and (3, 2) not in line


# ---- loot -------------------------------------------------------------------------------------

def test_better_chests_roll_better_loot_and_the_same_seed_rolls_the_same():
    def score(kind):
        return sum(LOOT.RARITIES.index(i["rarity"]) for s in range(300) for i in LOOT.roll_chest(kind, s, False) if i["type"] != "coins")
    order = [score(k) / 300 for k in ("supply", "military", "vault", "experimental", "legendary")]
    assert order == sorted(order)
    assert LOOT.roll_chest("vault", 42) == LOOT.roll_chest("vault", 42)
    meds = [i for s in range(50) for i in LOOT.roll_chest("medical", s, False)]
    assert all(i["type"] == "med" for i in meds)
    assert any(i.get("magic") for s in range(80) for i in LOOT.roll_chest("legendary", s, True))
    assert not any(i.get("magic") for s in range(80) for i in LOOT.roll_chest("legendary", s, False))


def test_magic_items_come_from_the_word_list_by_tier():
    assert len(LOOT.magic_items()) == 500
    rnd = random.Random(3)
    for r in LOOT.RARITIES:
        it = LOOT.magic_item(r, rnd)
        assert it["rarity"] == r and it["magic"]
        src = next(m for m in LOOT.magic_items() if m["name"] == it["name"])
        assert src["tier"] == LOOT.RARITIES.index(r) + 1 and src["effect"] in it["desc"]


def test_giving_respects_weight_and_one_of_a_kind():
    ch = {"abilities": {"str": 8}, "equipment": [{"qty": 1, "name": "Anvil", "weight": 115}], "currency": {"gp": 1}}
    eq, cur = LOOT.give(ch, LOOT.coins("2d1", "gp", random.Random(1)))
    assert cur["gp"] == 3 and eq == ch["equipment"], "coins go into the coins"
    with pytest.raises(ValueError, match="Too heavy"):
        LOOT.give(ch, LOOT.make("rifle", random.Random(1)))  # 115 + 8 > 120
    eq, _ = LOOT.give(ch, LOOT.make("seckey", random.Random(1)))
    ch["equipment"] = eq
    with pytest.raises(ValueError, match="only carry one"):
        LOOT.give(ch, LOOT.make("seckey", random.Random(2)))
    eq, _ = LOOT.give(ch, LOOT.make("cell", random.Random(1), qty=3))
    eq, _ = LOOT.give(dict(ch, equipment=eq), LOOT.make("cell", random.Random(2), qty=2))
    assert next(r for r in eq if r["name"] == "Energy cell")["qty"] == 5, "the same thing stacks"


# ---- in the app -------------------------------------------------------------------------------

def _prison(api, camp):
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "futureprison"}, 201)
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": st["map"]["id"]})
    return st


def test_a_new_prison_comes_with_hidden_enemies_and_chests(api, joined):
    camp = joined["camp"]
    st = _prison(api, camp)
    m, d = st["map"], st["map"]["dungeon"]
    assert m["name"] == "Abandoned prison — level 1"
    foes = [t for t in st["tokens"] if t["kind"] == "enemy"]
    names = {t["name"].rsplit(" ", 1)[0] if t["name"][-1].isdigit() else t["name"] for t in foes}
    assert {"Prison Warden", "Cybernetic Prison Guard", "Stealth Infiltrator", "Security Drone", "Prototype Cyborg"} <= names
    assert all(t["combatant_hidden"] for t in foes), "they wait hidden until a hero walks in"
    assert all(t["portrait"] and t["portrait"].startswith("prison-") for t in foes), "each has its own picture"
    kinds = {c["kind"] for c in m["chests"]}
    assert {"supply", "military", "medical", "vault", "experimental", "legendary"} <= kinds
    vault = next(c for c in m["chests"] if c["kind"] == "legendary")
    assert vault["locked_by"] == "Warden's access card" and not vault["rolled"] and not vault["opened"]
    # the keys are out there: a guard carries the Security keycard, the infiltrator the Lab keycard
    enc = api.get(f"/api/encounters/{m['encounter_id']}")
    carries = {tuple(c["statblock"].get("carries") or ()) for c in enc["combatants"]}
    assert ("seckey",) in carries and ("labkey",) in carries
    # players see only the chests in rooms they can see, and nothing of what's inside
    view = joined["pa"].get("/api/play/state")["map"]["map"]
    start = next(r for r in d["rooms"] if r["kind"] == "start")
    seen = view["chests"]
    assert seen and all(start["box"][0] - 1 <= c["x"] <= start["box"][2] + 1 for c in seen)
    assert all("loot" not in c and "locked_by" in c for c in seen)
    # a new layout restocks it without piling up old enemies
    st2 = api.post(f"/api/maps/{m['id']}/reroll", {})
    on_map = {t["combatant_id"] for t in st2["tokens"]}
    assert all(c["id"] in on_map for c in api.get(f"/api/encounters/{m['encounter_id']}")["combatants"] if c["kind"] == "enemy")
    assert st2["map"]["chests"] and len(api.get(f"/api/maps/{m['id']}")["map"]["chests"]) == len(st2["map"]["chests"])


def _stand(api, mid, char_id, xy):
    s = api.post(f"/api/maps/{mid}/tokens", {"character_id": char_id, "x": xy[0], "y": xy[1]}, 201)
    return next(t for t in s["tokens"] if t["character_id"] == char_id)


def test_open_a_chest_take_the_loot_once_and_it_stays_open(api, app, joined):
    camp, a, pa, pb = joined["camp"], joined["a"], joined["pa"], joined["pb"]
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Store", "cols": 10, "rows": 10}, 201)["map"]["id"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    s = api.post(f"/api/maps/{mid}/chests", {"kind": "military", "x": 5, "y": 5}, 201)
    chest = s["map"]["chests"][0]
    assert chest["name"] == "Military Weapons Crate" and not chest["rolled"]
    api.post(f"/api/maps/{mid}/chests", {"kind": "supply", "x": 5, "y": 5}, 400)  # one per square
    tok = _stand(api, mid, a["id"], [1, 1])
    pa.post(f"/api/play/chests/{chest['id']}/open", {}, 403)  # too far
    api.post(f"/api/tokens/{tok['id']}/move", {"x": 4, "y": 5, "free": True})
    # the DM adds a magic item from their list before anyone opens it
    added = api.post(f"/api/chests/{chest['id']}/magic", {"rarity": "rare"})["added"]
    assert added["rarity"] == "rare" and added["magic"]
    opened = pa.post(f"/api/play/chests/{chest['id']}/open", {})["chest"]
    assert opened["opened"] and opened["opened_by"] == "Aria"
    items = opened["loot"]
    assert added["name"] in [i["name"] for i in items], "the DM's magic item is in there"
    assert all(i["rarity"] in LOOT.RARITIES and i["desc"] for i in items)
    # opening again doesn't roll again
    assert pa.post(f"/api/play/chests/{chest['id']}/open", {})["chest"]["loot"] == items
    first = items[0]
    took = pa.post(f"/api/play/chests/{chest['id']}/take", {"item": first["id"]})["took"]
    assert took[0]["id"] == first["id"]
    pa.post(f"/api/play/chests/{chest['id']}/take", {"item": first["id"]}, 409)  # nobody gets it twice
    sheet = api.get(f"/api/characters/{a['id']}")["character"]
    if first.get("type") != "coins":
        row = next(r for r in sheet["equipment"] if r["name"] == first["name"])
        assert LOOT.RARITY_NAME[first["rarity"]] in row["notes"]
    pb.post(f"/api/play/chests/{chest['id']}/take", {"item": "all"}, 403)  # Bram isn't on the map
    pa.post(f"/api/play/chests/{chest['id']}/take", {"item": "all"})
    left = api.get(f"/api/maps/{mid}")["map"]["chests"][0]
    assert left["opened"] and left["loot"] == [] and len(left["taken"]) == len(items)
    # it's all in the database: a fresh request (a "load") sees it opened and empty
    view = remote(app, "192.168.1.21")
    view.c = pa.c
    assert pa.get("/api/play/state")["map"]["map"]["chests"][0]["opened"]


def test_locks_need_the_card_and_doors_open_with_it(api, joined):
    camp, a, pa = joined["camp"], joined["a"], joined["pa"]
    st = _prison(api, camp)
    m = st["map"]
    mid = m["id"]
    lab = next(r for r in m["dungeon"]["rooms"] if r["kind"] == "lab")
    dx, dy = lab["door"]
    tok = _stand(api, mid, a["id"], m["dungeon"]["start"])
    api.post(f"/api/tokens/{tok['id']}/move", {"x": dx, "y": dy - 1, "free": True})
    r = pa.post("/api/play/doors", {"x": dx, "y": dy}, 403)
    assert "Lab keycard" in r["error"]
    sheet = api.get(f"/api/characters/{a['id']}")["character"]
    api.patch(f"/api/characters/{a['id']}", {"changes": {"equipment": {"from": sheet["equipment"], "to": [{"qty": 1, "name": "Lab keycard", "weight": 0, "notes": ""}]}}})
    assert pa.post("/api/play/doors", {"x": dx, "y": dy})["opened"] == "Experimental lab"
    m2 = api.get(f"/api/maps/{mid}")["map"]
    assert m2["terrain"][f"{dx},{dy}"] == "blastdoor"
    cx, cy = (lab["box"][0] + lab["box"][2]) // 2, (lab["box"][1] + lab["box"][3]) // 2
    assert m2["revealed"][cy * m2["cols"] + cx] == "1", "the room behind lights up"
    # a hidden panel needs no card; the DM can open any door
    stash = next(r for r in m["dungeon"]["rooms"] if r["kind"] == "secret" and not r["needs"])
    api.post(f"/api/maps/{mid}/doors", {"x": stash["door"][0], "y": stash["door"][1]})
    api.post(f"/api/maps/{mid}/doors", {"x": stash["door"][0], "y": stash["door"][1]}, 400)
    # a locked vault chest
    vault = next(c for c in m["chests"] if c["kind"] == "legendary")
    api.post(f"/api/maps/{mid}/doors", {"x": next(r for r in m["dungeon"]["rooms"] if r["kind"] == "vault")["door"][0],
                                        "y": next(r for r in m["dungeon"]["rooms"] if r["kind"] == "vault")["door"][1]})
    # clear the guard off the square next to it, then step up (DM free move)
    api.post(f"/api/tokens/{tok['id']}/move", {"x": vault["x"], "y": vault["y"] + 1, "free": True})
    r = pa.post(f"/api/play/chests/{vault['id']}/open", {}, 403)
    assert r["needs"] == "Warden's access card"
    sheet = api.get(f"/api/characters/{a['id']}")["character"]
    api.patch(f"/api/characters/{a['id']}", {"changes": {"equipment": {"from": sheet["equipment"], "to": sheet["equipment"] + [{"qty": 1, "name": "Warden's access card", "weight": 0, "notes": ""}]}}})
    got = pa.post(f"/api/play/chests/{vault['id']}/open", {})["chest"]
    assert got["opened"] and got["loot"]
    assert all(i["rarity"] in ("rare", "epic", "legendary", "common") for i in got["loot"])


def test_opening_in_a_fight_is_on_your_turn_and_uses_an_action(api, joined):
    camp, a, pa = joined["camp"], joined["a"], joined["pa"]
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Hall", "cols": 10, "rows": 10}, 201)["map"]["id"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    c1 = api.post(f"/api/maps/{mid}/chests", {"kind": "supply", "x": 5, "y": 5}, 201)["map"]["chests"][0]["id"]
    _stand(api, mid, a["id"], [4, 5])
    s = api.post(f"/api/maps/{mid}/monsters", {"book": "Inmate Enforcer", "x": 8, "y": 8}, 201)
    eid = s["map"]["encounter_id"]
    api.post(f"/api/encounters/{eid}/roll", {})
    api.post(f"/api/encounters/{eid}/start", {})
    enc = api.get(f"/api/encounters/{eid}")
    hero = next(c for c in enc["combatants"] if c["character_id"] == a["id"])
    if enc["encounter"]["current_id"] != hero["id"]:
        r = pa.post(f"/api/play/chests/{c1}/open", {}, 403)
        assert "your turn" in r["error"]
        api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": hero["id"]})
    pa.post(f"/api/play/chests/{c1}/open", {})
    me = pa.get("/api/play/state")["character"]
    assert me["actions"]["used"] == 1


def test_a_fallen_prison_enemy_drops_its_gear_once(api, joined):
    camp = joined["camp"]
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Deck", "cols": 10, "rows": 10}, 201)["map"]["id"]
    s = api.post(f"/api/maps/{mid}/monsters", {"book": "Prison Warden", "x": 6, "y": 6}, 201)
    eid = s["map"]["encounter_id"]
    w = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Prison Warden"))
    api.post(f"/api/encounters/{eid}/damage", {"targets": [w["id"]], "amount": 500})
    chests = api.get(f"/api/maps/{mid}")["map"]["chests"]
    assert len(chests) == 1 and chests[0]["kind"] == "drop" and chests[0]["rolled"]
    assert "Warden's access card" in [i["name"] for i in chests[0]["loot"]], "the warden always drops its card"
    api.post(f"/api/combatants/{w['id']}/hp", {"op": "heal", "amount": 10})
    api.post(f"/api/encounters/{eid}/damage", {"targets": [w["id"]], "amount": 500})
    assert len(api.get(f"/api/maps/{mid}")["map"]["chests"]) == 1, "no second drop"
    # an ordinary monster drops nothing (as before)
    s = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "x": 2, "y": 2}, 201)
    g = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Goblin"))
    api.post(f"/api/encounters/{eid}/damage", {"targets": [g["id"]], "amount": 50})
    assert len(api.get(f"/api/maps/{mid}")["map"]["chests"]) == 1


def _fight(api, camp, hero, monster, hero_at, foe_at, cols=14, rows=10):
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Arena", "cols": cols, "rows": rows}, 201)["map"]["id"]
    _stand(api, mid, hero["id"], hero_at)
    s = api.post(f"/api/maps/{mid}/monsters", {"book": monster, "x": foe_at[0], "y": foe_at[1]}, 201)
    eid = s["map"]["encounter_id"]
    api.post(f"/api/encounters/{eid}/roll", {})
    api.post(f"/api/encounters/{eid}/start", {})
    foe = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["kind"] == "enemy")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": foe["id"]})
    return mid, eid, foe


def _tok(api, mid, cb_id=None, char_id=None):
    return next(t for t in api.get(f"/api/maps/{mid}")["tokens"] if (cb_id and t["combatant_id"] == cb_id and not t["character_id"])
                or (char_id and t["character_id"] == char_id))


def test_a_brawler_walks_up_and_attacks(api, joined):
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _fight(api, camp, a, "Riot Suppressor", [1, 4], [9, 4])
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    t = _tok(api, mid, foe["id"])
    assert max(abs(t["x"] - 1), abs(t["y"] - 4)) <= 5, "moved up to 25 ft towards the hero"
    assert any("moves" in l or "dashes" in l for l in r["did"]), r["did"]
    # next turn it's in reach and swings
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": foe["id"]})
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    assert any("Stun Baton" in l or "Shield Bash" in l for l in r["did"]), r["did"]
    rolls = api.get(f"/api/rolls?campaign_id={camp['id']}")["rolls"]
    assert any(x["kind"] == "attack" and x["roller_name"].startswith("Riot Suppressor") for x in rolls)
    # Undo last action takes the whole turn back
    before = api.get(f"/api/encounters/{eid}")["encounter"]["rev"]
    api.post(f"/api/encounters/{eid}/undo-last", {})
    assert api.get(f"/api/encounters/{eid}")["encounter"]["rev"] > before


def test_a_shooter_keeps_its_distance_and_a_drone_backs_off(api, joined):
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _fight(api, camp, a, "Security Drone", [5, 4], [6, 4])
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    t = _tok(api, mid, foe["id"])
    assert max(abs(t["x"] - 5), abs(t["y"] - 4)) >= 2, "it doesn't stay next to the hero"
    assert any("Twin Laser" in l for l in r["did"]), r["did"]


def test_walls_are_walked_round_and_no_shot_through_them(api, joined):
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _fight(api, camp, a, "Cybernetic Prison Guard", [1, 1], [10, 1], cols=12, rows=8)
    # a steel wall between them, with a gap at the bottom
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[5, y] for y in range(0, 7)], "value": "bulkhead"})
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    t = _tok(api, mid, foe["id"])
    assert t["x"] != 5 or t["y"] == 7, "never inside the wall"
    assert not any("Pulse Rifle" in l for l in r["did"]) or t["y"] >= 6, "no shooting through steel"


def test_area_attack_hits_a_cluster_with_saves(api, joined):
    camp, a, b = joined["camp"], joined["a"], joined["b"]
    mid, eid, foe = _fight(api, camp, a, "Experimental Prisoner", [3, 4], [5, 4])
    _stand(api, mid, b["id"], [3, 5])
    link = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "x": 12, "y": 9}, 201)  # (links Bram into the fight)
    assert link
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": foe["id"]})
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    assert any("Bio-Shriek" in l for l in r["did"]), r["did"]
    rolls = api.get(f"/api/rolls?campaign_id={camp['id']}")["rolls"]
    assert sum(1 for x in rolls if x["kind"] == "save") >= 2
    # recharge: it's spent now
    sb = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["id"] == foe["id"])["statblock"]
    assert "Bio-Shriek" in sb["ai"]["spent"]


def test_heroes_and_turns_that_arent_theirs_are_refused(api, joined):
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _fight(api, camp, a, "Inmate Enforcer", [1, 1], [8, 8])
    hero = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["character_id"])
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": hero["id"]})
    r = api.post(f"/api/encounters/{eid}/auto-turn", {}, 400)
    assert "heroes" in r["error"]


def test_enemies_act_on_their_own_with_the_setting(api, joined):
    camp, a, pa = joined["camp"], joined["a"], joined["pa"]
    mid, eid, foe = _fight(api, camp, a, "Riot Suppressor", [1, 4], [4, 4])
    hero = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["character_id"])
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": hero["id"]})
    full = next(c for c in api.get("/api/campaigns")["campaigns"] if c["id"] == camp["id"])["settings"]
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": dict(full, loot={"magic_items": True, "auto_act": True})}}})
    api.post(f"/api/encounters/{eid}/next", {})
    enc = api.get(f"/api/encounters/{eid}")
    assert enc["encounter"]["current_id"] == hero["id"], "the enemy acted and handed the turn back"
    assert any("Riot Suppressor" in l["message"] and ("Baton" in l["message"] or "Bash" in l["message"] or "moves" in l["message"])
               for l in enc["log"])


def test_backup_keeps_chests(api, joined):
    camp = joined["camp"]
    _prison(api, camp)
    data = api.get(f"/api/backup/export?campaign_id={camp['id']}")
    maps = data["data"]["campaigns"][0]["maps"]
    assert sum(len(m.get("chests", [])) for m in maps) >= 8


def test_the_prison_loads_on_its_own():
    """Making a prison first thing after a restart imports app.prison before the Monster Book."""
    import subprocess
    import sys
    for first in ("app.prison", "app.prison_monsters", "app.ai", "app.monster_book"):
        r = subprocess.run([sys.executable, "-c", f"import {first}; import app.monster_book as b; assert len(b.MONSTERS) > 40"], capture_output=True, text=True)
        assert r.returncode == 0, (first, r.stderr[-400:])


def _lane_fight(api, camp, hero, lanes):
    """A made-up map turned into a hall `lanes` squares wide (y = 5..), a guard at the far end with its
    drone right in front of it, and the hero at the other end; the guard's turn."""
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "dungeon"}, 201)
    mid, m = st["map"]["id"], st["map"]
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[x, y] for x in range(m["cols"]) for y in range(m["rows"])], "value": "wall"})
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[x, y] for x in range(1, 30) for y in range(5, 5 + lanes)], "value": "stone"})
    # a waist-high terminal in the hall: you can shoot over it, not walk through it
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[5, 5]], "value": "terminal"})
    api.post(f"/api/maps/{mid}/tokens", {"character_id": hero["id"], "x": 2, "y": 5}, 201)
    s = api.post(f"/api/maps/{mid}/monsters", {"book": "Riot Suppressor", "x": 20, "y": 5}, 201)
    api.post(f"/api/maps/{mid}/monsters", {"book": "Security Drone", "x": 19, "y": 5}, 201)
    eid = s["map"]["encounter_id"]
    api.post(f"/api/encounters/{eid}/roll", {})
    api.post(f"/api/encounters/{eid}/start", {})
    foe = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Riot"))
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": foe["id"]})
    return mid, eid, foe


def test_an_enemy_goes_round_its_own_side_and_says_so_when_it_cant(api, joined):
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _lane_fight(api, camp, a, lanes=2)
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    t = next(t for t in api.get(f"/api/maps/{mid}")["tokens"] if t["combatant_id"] == foe["id"] and not t["character_id"])
    assert t["x"] < 19, f"it walked round the drone ({r['did']})"
    mid, eid, foe = _lane_fight(api, camp, a, lanes=1)  # one square wide: the drone is in the way
    r = api.post(f"/api/encounters/{eid}/auto-turn", {})
    assert r["did"] and any("holds its position" in l for l in r["did"]), r["did"]


def test_shots_go_over_terminals_but_not_through_walls(api, joined):
    from app.ai import Board
    camp, a = joined["camp"], joined["a"]
    mid, eid, foe = _lane_fight(api, camp, a, lanes=1)
    from app.maps import map_dict
    with api.c.application.app_context():
        from app.db import get_db
        conn = get_db()
        m = map_dict(conn.execute("SELECT * FROM maps WHERE id = ?", (mid,)).fetchone())
        tok = conn.execute("SELECT * FROM map_tokens WHERE map_id = ? AND combatant_id = ?", (mid, foe["id"])).fetchone()
        b = Board(conn, m, tok, False)
        assert b.clear_shot((8, 5), 1, (2, 5), 1), "over the terminal at (5, 5)"
        m["terrain"]["5,5"] = "bulkhead"
        b = Board(conn, m, tok, False)
        assert not b.clear_shot((8, 5), 1, (2, 5), 1), "not through steel"


def test_player_sees_their_inventory(api, joined):
    """The player screen lists what their character carries: sheet items (with rarity for chest loot),
    coins and weight. Bram never sees Aria's."""
    a, pa, pb = joined["a"], joined["pa"], joined["pb"]
    sheet = api.get(f"/api/characters/{a['id']}")["character"]
    api.patch(f"/api/characters/{a['id']}", {"changes": {
        "equipment": {"from": sheet["equipment"], "to": [
            {"qty": 50, "name": "Rope, hempen (50 ft)", "weight": 10, "notes": ""},
            {"qty": 2, "name": "Stim pack", "weight": 0.5, "notes": "Uncommon · Heals 2d4+2."},
            {"qty": 1, "name": "", "weight": None, "notes": ""}]},
        "currency": {"from": sheet["currency"], "to": {"gp": 12, "sp": 0, "cp": 3}}}})
    inv = pa.get("/api/play/state")["character"]["inventory"]
    assert [i["name"] for i in inv["items"]] == ["Rope, hempen (50 ft)", "Stim pack"]  # blank rows left out
    stim = inv["items"][1]
    assert stim["rarity"] == "uncommon" and stim["notes"] == "Heals 2d4+2." and stim["qty"] == 2
    assert inv["items"][0]["rarity"] is None
    assert inv["coins"] == {"gp": 12, "cp": 3}
    assert inv["carried"] == 501.0 and inv["capacity"] == LOOT.carry_capacity(api.get(f"/api/characters/{a['id']}")["character"])
    other = pb.get("/api/play/state")["character"]
    assert "Stim pack" not in json.dumps(other)
