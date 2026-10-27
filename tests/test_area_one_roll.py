"""An area attack (Wide Slash, a cone) is ONE attack roll checked against each one's AC, and one
damage roll for everyone it hits; a natural 20 crits them all. Its animation is one long sweep."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

WIDE = {"name": "Wide Slash", "effect": "damage", "level": 0, "dice": "2d12", "damage_type": "slashing", "hit": "attack",
        "attack_bonus": 5, "area": "20 ft cone, range 30", "cooldown": 3}


def setup(api, bm, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid = bm["eid"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"quick": {"name": "Ogre", "max_hp": 60, "ac": 18, "count": 1}})
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/start")
    return eid, by, loaded


def test_one_roll_against_each_ac(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)   # bandits AC 12 (quick default), ogre AC 18
    loaded.next(10, 6, 5)                                    # one d20: 10+5 = 15; one damage roll: 6+5 = 11
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": WIDE,
                                                   "targets": [by["Aria"]["id"], by["Ogre"]["id"]]})
    res = {t["name"]: t for t in st["cast"]["targets"]}
    assert res["Aria"]["roll"] == res["Ogre"]["roll"] == 15, "the same roll for both"
    assert res["Ogre"]["how"] == "miss" and res["Aria"]["how"] == "hit" and res["Aria"]["amount"] == 11
    attacks = [r for r in st["cast"]["rolls"] if r["kind"] == "attack"]
    assert len(attacks) == 1 and len([r for r in st["cast"]["rolls"] if r["kind"] == "damage"]) == 1


def test_natural_20_crits_them_all(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    loaded.next(20, 6, 5, 4, 3)                              # crit: 4d12
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": WIDE,
                                                   "targets": [by["Aria"]["id"], by["Ogre"]["id"]]})
    res = {t["name"]: t for t in st["cast"]["targets"]}
    assert res["Aria"]["how"] == res["Ogre"]["how"] == "crit" and res["Aria"]["amount"] == res["Ogre"]["amount"] == 18


def test_the_animation_knows_its_cone(api, battlemap, monkeypatch):
    eid, by, loaded = setup(api, battlemap, monkeypatch)
    api.post(f"/api/campaigns/{battlemap['camp']['id']}/live-map", {"map_id": battlemap["mid"]})
    loaded.next(10, 6, 5)
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": WIDE, "targets": [by["Aria"]["id"]]})
    fx = [p["fx"] for p in api.get(f"/api/maps/{battlemap['mid']}")["pings"] if p.get("fx")][-1]
    assert fx["area"] == {"kind": "cone", "squares": 4.0}
