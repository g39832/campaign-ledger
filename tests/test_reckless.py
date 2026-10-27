"""Gnocchi's Reckless attack: she uses it on herself, and for the rest of her turn her
damage is doubled (her Great Axe: roll to hit as usual; when it hits, the damage is
doubled). One-turn cooldown. On the sheet it's a row with Damage × 2 and no dice.
A row that has dice AND Damage × doubles just that attack instead."""
from app import dice
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

ROWS = [{"name": "Great Axe", "bonus": "+5", "damage": "3d12"},  # damage after a to-hit: not another action
        {"name": "Reckless attack", "bonus": "", "damage": "", "dmg_mult": 2, "cooldown": 1,
         "notes": "Doubles your attack then opponents attacks"},
        {"name": "Smite", "bonus": "+5", "damage": "1d8", "dmg_mult": 2}]


def setup(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, attacks=ROWS)
    eid = battlemap["eid"]
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, by, loaded


def me(api, eid):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")


def axe(api, by, loaded, *faces):
    loaded.next(*faces)
    return api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": by["Aria"]["id"]}}, 201)["roll"]


def test_reckless_is_used_on_herself_not_cast_at_others(api, battlemap, monkeypatch):
    eid, by, _ = setup(api, battlemap, monkeypatch)
    row = next(a for a in by["Aria"]["attacks"] if a["name"] == "Reckless attack")
    assert row["stance"] == 2 and row["cast"] is None, "no target picking"
    st = api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    rk = next(x for x in me(api, eid)["conditions"] if x["name"] == "Reckless attack")
    assert rk["dmg_mult"] == 2 and rk["note"] == "Damage doubled this turn"
    assert any("Aria uses Reckless attack: damage doubled this turn" in e["message"] for e in st["log"])


def test_her_damage_is_doubled_while_reckless_and_only_this_turn(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    assert axe(api, by, loaded, 4, 4, 4)["total"] == 12, "normal before"
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    loaded.next(15)
    hit = api.post("/api/rolls", {"check": {"type": "attack", "key": 2, "combatant_id": by["Aria"]["id"]}}, 201)["roll"]
    assert hit["total"] == 20 and "multiplier" not in hit["result"], "the to-hit roll isn't doubled"
    r = axe(api, by, loaded, 4, 4, 4)
    assert r["total"] == 24 and "doubled" in r["label"]
    loaded.next(6, 6, 6, 6, 6, 6)
    crit = api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": by["Aria"]["id"]}, "crit": True}, 201)["roll"]
    assert crit["total"] == 72, "a crit: 6d12 = 36, doubled"
    # end of her turn: gone, and recharging
    api.post(f"/api/encounters/{eid}/next")
    c = me(api, eid)
    assert not any(x["name"] == "Reckless attack" for x in c["conditions"])
    assert any(x.get("cooldown") == "Reckless attack" for x in c["conditions"])
    assert axe(api, by, loaded, 4, 4, 4)["total"] == 12, "normal again"


def test_a_spell_she_casts_while_reckless_is_doubled_too(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    api.post(f"/api/combatants/{by['Bandit 1']['id']}/hp", {"op": "set", "max_hp": 100, "hp": 100})
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    spec = {"name": "Fire Bolt", "effect": "damage", "dice": "1d10", "hit": "attack", "attack_bonus": 5}
    loaded.next(15, 7)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    assert st["cast"]["targets"][0]["amount"] == 14 and "doubled" in st["cast"]["targets"][0]["text"]
    loaded.next(1)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    assert st["cast"]["targets"][0]["how"] == "miss", "a miss is still a miss"


def test_cooldown_and_once_a_turn(api, battlemap, monkeypatch):
    eid, by, _ = setup(api, battlemap, monkeypatch)
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    err = api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1}, 400)
    assert "recharging" in err["error"] or "already" in err["error"]


def test_player_uses_it_on_her_turn_and_her_dmg_doubles(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    pa = battlemap["pa"]
    row = next(a for a in pa.get("/api/play/state")["character"]["attacks"] if a["name"] == "Reckless attack")
    assert row["stance"] == 2
    r = pa.post("/api/play/me/surge", {"index": 1})
    assert any("damage ×2" in c for c in r["character"]["conditions"])
    loaded.next(5, 5, 5)
    roll = pa.post("/api/rolls", {"check": {"type": "damage", "key": 0, "character_id": battlemap["a"]["id"]}}, 201)["roll"]
    assert roll["total"] == 30


def test_a_row_with_dice_and_damage_x_doubles_just_that_attack(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    smite = next(a for a in by["Aria"]["attacks"] if a["name"] == "Smite")
    assert smite["stance"] == 1 and smite["cast"]["dmg_mult"] == 2
    loaded.next(6)
    r = api.post("/api/rolls", {"check": {"type": "damage", "key": 2, "combatant_id": by["Aria"]["id"]}}, 201)["roll"]
    assert r["total"] == 12
