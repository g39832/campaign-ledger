"""Gnocchi's Reckless attack: rolls to hit, and on a hit the Great Axe damage is doubled.
One-turn cooldown. The multiplier is the "Damage × on a hit" box on the sheet row."""
from app import dice
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

ROWS = [{"name": "Great Axe", "bonus": "", "damage": "3d12"},
        {"name": "Reckless attack", "bonus": "", "damage": "3d12", "dmg_mult": 2, "cooldown": 1,
         "notes": "Doubles your attack then opponents attacks"}]


def setup(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, attacks=ROWS)
    eid = battlemap["eid"]
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    spec = next(a for a in api.get(f"/api/encounters/{eid}")["combatants"] if a["name"] == "Aria")["attacks"][1]["cast"]
    return eid, by, spec, loaded


def hp(st, name):
    return next(c for c in st["combatants"] if c["name"] == name)["hp"]


def test_reckless_row_reaches_combat_as_a_double_damage_move(api, battlemap, monkeypatch):
    eid, by, spec, _ = setup(api, battlemap, monkeypatch)
    assert spec["dmg_mult"] == 2 and spec["dice"] == "3d12" and spec["hit"] == "attack" and spec["cooldown"] == 1
    great = next(a for a in by["Aria"]["attacks"] if a["name"] == "Great Axe")
    assert great["cast"] is None and great["dmg_mult"] == 1


def test_hit_doubles_the_damage(api, battlemap, monkeypatch):
    eid, by, spec, loaded = setup(api, battlemap, monkeypatch)
    api.post(f"/api/combatants/{by['Bandit 1']['id']}/hp", {"op": "set", "max_hp": 100, "hp": 100})
    loaded.next(15, 2, 3, 4)  # 15 vs AC 10 hits; 3d12 = 9 -> 18
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    t = st["cast"]["targets"][0]
    assert t["how"] == "hit" and t["amount"] == 18 and "doubled" in t["text"]
    assert hp(st, "Bandit 1") == 82
    assert st["cast"]["summary"].startswith("Aria uses Reckless attack")
    # one-turn cooldown
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]}, 400)
    assert "recharging" in err["error"].lower() or "Reckless" in err["error"]


def test_miss_does_nothing(api, battlemap, monkeypatch):
    eid, by, spec, loaded = setup(api, battlemap, monkeypatch)
    loaded.next(1)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    assert st["cast"]["targets"][0]["how"] == "miss" and hp(st, "Bandit 1") == 11


def test_crit_doubles_the_dice_then_the_total(api, battlemap, monkeypatch):
    eid, by, spec, loaded = setup(api, battlemap, monkeypatch)
    api.post(f"/api/combatants/{by['Bandit 1']['id']}/hp", {"op": "set", "max_hp": 200, "hp": 200})
    loaded.next(20, 1, 1, 1, 1, 1, 1)  # natural 20: 6d12 = 6 -> doubled 12
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    assert st["cast"]["targets"][0]["how"] == "crit" and st["cast"]["targets"][0]["amount"] == 12
    assert st["cast"]["rolls"][1]["expression"] == "6d12"


def test_the_dmg_button_doubles_too(api, battlemap, monkeypatch):
    eid, by, spec, loaded = setup(api, battlemap, monkeypatch)
    loaded.next(5, 5, 5)
    r = api.post("/api/rolls", {"check": {"type": "damage", "key": 1, "combatant_id": by["Aria"]["id"]}}, 201)["roll"]
    assert r["total"] == 30 and "doubled" in r["label"] and r["result"]["multiplier"] == 2
    loaded.next(5, 5, 5)
    r = api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": by["Aria"]["id"]}}, 201)["roll"]
    assert r["total"] == 15, "the plain Great Axe isn't doubled"
    me = battlemap["pa"].get("/api/play/state")["character"]
    assert next(a for a in me["attacks"] if a["name"] == "Reckless attack")["dmg_mult"] == 2
