"""Physical moves (attacks on the sheet) only reach enemies right next to you (5 ft), or what
their notes say ("reach 10 ft"); bows and other ranged attacks, and spells, have no limit."""
from app.rules import melee_reach
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

ATTACKS = [{"name": "Bite", "bonus": "+50", "damage": "1d8"},
           {"name": "Whip", "bonus": "+50", "damage": "1d4", "notes": "reach 10 ft"},
           {"name": "Longbow", "bonus": "+50", "damage": "1d8", "notes": "range 150/600"}]
SPELLS = [{"name": "Fire Bolt", "effect": "damage", "level": 0, "dice": "1d10", "hit": "attack", "attack_bonus": 50}]


def test_what_counts_as_melee():
    assert melee_reach({"name": "Punch", "damage": "2d12+6 bludgeoning"}) == 5
    assert melee_reach({"name": "Whip", "notes": "reach 10 ft"}) == 10
    assert melee_reach({"name": "Heavy Crossbow", "damage": "1d10"}) is None
    assert melee_reach({"name": "Shot", "notes": "Ranged weapon attack, range 80 ft"}) is None
    assert melee_reach({"name": "Spear", "notes": "melee or thrown"}) == 5
    assert melee_reach({"name": "Wide cut", "damage": "2d6", "area": "15 ft cone"}) is None


def setup(api, bm):
    camp, eid, mid = bm["camp"], bm["eid"], bm["mid"]
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, attacks=ATTACKS, spells=SPELLS)
    api.patch(f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}}})
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    m = api.get(f"/api/maps/{mid}")
    api.post(f"/api/tokens/{tok(m, 'Aria')['id']}/move", {"x": 0, "y": 0, "free": True})
    api.post(f"/api/tokens/{tok(m, 'Bandit 1')['id']}/move", {"x": 1, "y": 1, "free": True})   # diagonal: right next to her
    api.post(f"/api/tokens/{tok(m, 'Bandit 2')['id']}/move", {"x": 2, "y": 0, "free": True})   # one square between: 10 ft
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return by


def test_melee_reaches_only_the_enemy_next_to_you(api, battlemap):
    by = setup(api, battlemap)
    pa = battlemap["pa"]
    pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]})          # Bite: next to her
    err = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]]}, 403)
    assert "Bandit 2 is 10 ft away" in err["error"] and "Bite only reaches 5 ft" in err["error"]
    st = pa.get("/api/play/state")["character"]
    assert st["actions"]["used"] == 1, "a refused attack doesn't use an action"
    assert next(a for a in st["attacks"] if a["name"] == "Bite")["reach"] == 5


def test_reach_ranged_and_spells(api, battlemap):
    by = setup(api, battlemap)
    pa = battlemap["pa"]
    pa.post("/api/play/me/use", {"what": "attack", "index": 1, "targets": [by["Bandit 2"]["id"]]})          # Whip: reach 10 ft
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/next"); api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    for _ in range(4):
        st = api.post(f"/api/encounters/{eid}/next")
        if st["encounter"]["current_id"] == by["Aria"]["id"]:
            break
    m = api.get(f"/api/maps/{battlemap['mid']}")
    api.post(f"/api/tokens/{tok(m, 'Bandit 2')['id']}/move", {"x": 25, "y": 0, "free": True})               # far away
    pa.post("/api/play/me/use", {"what": "attack", "index": 2, "targets": [by["Bandit 2"]["id"]]})          # Longbow: no limit
    pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": [by["Bandit 2"]["id"]]})           # spells: no limit


def test_no_map_no_limit(api, battlemap):
    by = setup(api, battlemap)
    api.patch(f"/api/maps/{battlemap['mid']}", {"changes": {"encounter_id": {"to": None}}})                  # the fight has no map now
    battlemap["pa"].post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]]})
