"""Players use their attacks and harmful spells on enemies from their phone, like the DM does
on the map: only on their own turn, only at enemies, the server rolls against AC (which the
player never sees) and applies the damage. Heals and buffs still go on the party."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

ATTACKS = [{"name": "Punch", "bonus": "+50", "damage": "1d6+3 bludgeoning"},
           {"name": "Grapple", "bonus": "+50", "damage": "1d4", "condition": "Grappled"}]
SPELLS = [{"name": "Fire Bolt", "effect": "damage", "level": 0, "dice": "1d10", "damage_type": "fire", "hit": "attack", "attack_bonus": 50},
          {"name": "Cure Wounds", "effect": "heal", "level": 1, "dice": "1d8"}]


def setup(api, bm):
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, attacks=ATTACKS, spells=SPELLS, spell_slots={"1": {"max": 2, "used": 0}})
    eid = bm["eid"]
    m = api.get(f"/api/maps/{bm['mid']}")  # the bandits stand right next to her (physical moves reach 5 ft)
    for name, (x, y) in {"Aria": (3, 3), "Bandit 1": (4, 3), "Bandit 2": (3, 4)}.items():
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, by


def hp(api, eid, name):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["hp"]


def test_attack_an_enemy_from_the_phone(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    r = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]})
    t = r["cast"]["targets"][0]
    assert t["how"] in ("hit", "crit", "miss") and (hp(api, eid, "Bandit 1") < 11) == (t["how"] != "miss")  # a natural 1 still misses
    assert "AC" not in r["cast"]["summary"] and "AC" not in t["text"]
    assert all("AC" not in (x.get("outcome") or "") for x in r["cast"]["rolls"])
    assert r["character"]["actions"]["used"] == 1
    # a condition on a hit (Grapple)
    r = pa.post("/api/play/me/use", {"what": "attack", "index": 1, "targets": [by["Bandit 2"]["id"]]})
    b2 = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 2")
    assert any(x["name"] == "Grappled" for x in b2["conditions"]) == (r["cast"]["targets"][0]["how"] != "miss")
    # two actions used: a third is refused
    pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]}, 403)


def test_only_enemies_and_only_on_your_turn(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [battlemap["b"]["id"]]})
    bram = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bram")
    for who in (by["Aria"]["id"], bram["id"]):
        err = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [who]}, 403)
        assert "only use that on enemies" in err["error"]
    pa.post("/api/play/me/use", {"what": "spell", "index": 1, "targets": [by["Bandit 1"]["id"]]}, 400)   # Cure Wounds isn't aimed at foes
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    err = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]}, 403)
    assert "not your turn" in err["error"]
    assert hp(api, eid, "Bandit 1") == 11


def test_damage_spell_on_an_enemy_and_heals_still_on_the_party(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    r = pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": [by["Bandit 1"]["id"]]})
    t = r["cast"]["targets"][0]
    assert t["how"] in ("hit", "crit", "miss") and (hp(api, eid, "Bandit 1") < 11) == (t["how"] != "miss")
    aria = battlemap["a"]["id"]
    api.post(f"/api/combatants/{by['Aria']['id']}/hp", {"op": "damage", "amount": 5})
    pa.post("/api/play/cast", {"spell": 1, "targets": [aria], "slot": 1})
    assert api.get(f"/api/characters/{aria}")["character"]["current_hp"] > 15


def test_speed_comes_from_the_sheet(api, battlemap):
    from tests.test_turn_movement import to_turn, setup as map_setup
    pa, eid = battlemap["pa"], battlemap["eid"]
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, speed="40 ft")
    me = map_setup(api, battlemap)
    to_turn(api, eid, "Aria")
    assert pa.get("/api/play/state")["character"]["move"]["speed"] == 40
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 8, "y": 0})       # 40 ft: exactly her speed
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 9, "y": 0}, 403)  # one more square is too far
