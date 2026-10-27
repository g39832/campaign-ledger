"""Spirit Guardians as a zone around the caster: enemies in it when it's cast save or take the
damage once; it stays up (and goes where the caster goes) for its rounds, halving enemies'
movement inside; teammates are never hurt or slowed; it recharges after it goes down.
And any cast can be taken back right after (a misclick), by the DM or the player who cast it."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

GUARDIANS = {"name": "Spirit Guardians", "effect": "damage", "level": 3, "dice": "3d8", "damage_type": "radiant", "hit": "wis",
             "force_save": True, "save_half": False, "area": "20 ft radius", "rounds": 3, "cooldown": 3, "zone": True, "zone_speed": "0.5"}


def setup(api, bm, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    camp, eid, mid = bm["camp"], bm["eid"], bm["mid"]
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, spells=[GUARDIANS], spellcasting_ability="wis", abilities=dict(aria["abilities"], wis=16))
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [bm["b"]["id"]]})
    api.post(f"/api/maps/{mid}/tokens/from-encounter")
    api.patch(f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}, "rows": {"to": 12}}})
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    m = api.get(f"/api/maps/{mid}")
    for name, (x, y) in {"Aria": (5, 5), "Bram": (6, 5), "Bandit 1": (9, 5), "Bandit 2": (11, 5)}.items():
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": x, "y": y, "free": True})
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, mid, by, loaded


def hp(api, eid, name):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["hp"]


def conds(api, eid, name):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["conditions"]


def test_spirit_guardians_zone(api, battlemap, monkeypatch):
    eid, mid, by, loaded = setup(api, battlemap, monkeypatch)
    pa = battlemap["pa"]
    hp0 = {n: hp(api, eid, n) for n in ("Bram", "Bandit 1", "Bandit 2")}
    loaded.next(1, 2, 1, 2)  # 3d8 = 4, Bandit 1's Wisdom save: 2 (fails)
    r = pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": []})["cast"]
    assert [t["name"] for t in r["targets"]] == ["Bandit 1"], "only the enemy within 20 ft; not Bram (a teammate), not Bandit 2 (25 ft away)"
    assert r["targets"][0]["how"] == "failed" and hp(api, eid, "Bandit 1") == hp0["Bandit 1"] - 4
    assert hp(api, eid, "Bram") == hp0["Bram"] and hp(api, eid, "Bandit 2") == hp0["Bandit 2"]
    assert not conds(api, eid, "Bandit 1"), "it's damage once, nothing left on them"
    zone = next(x for x in conds(api, eid, "Aria") if x.get("zone"))
    assert zone["rounds_left"] == 3 and zone["zone"]["half"] == 4
    rech = next(x for x in conds(api, eid, "Aria") if x.get("cooldown") == "Spirit Guardians")
    assert rech["rounds_left"] >= 6, "3 rounds up, then a 3-round cooldown"
    z = api.get(f"/api/maps/{mid}")["zones"]
    assert z and z[0]["token"] == tok(api.get(f"/api/maps/{mid}"), "Aria")["id"] and z[0]["half"] == 4
    assert pa.get("/api/play/state")["map"]["zones"], "the phones see it too"
    # enemies inside move at half speed; outside, or teammates, normally
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    assert api.get(f"/api/maps/{mid}")["move"]["speed"] == 15
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 2"]["id"]})
    assert api.get(f"/api/maps/{mid}")["move"]["speed"] == 30
    bram = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bram")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": bram["id"]})
    assert api.get(f"/api/maps/{mid}")["move"]["speed"] == 30
    # it goes with her: she walks away from Bandit 1, he's no longer slowed
    m = api.get(f"/api/maps/{mid}")
    api.post(f"/api/tokens/{tok(m, 'Aria')['id']}/move", {"x": 0, "y": 0, "free": True})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    assert api.get(f"/api/maps/{mid}")["move"]["speed"] == 30
    # three of her turns later it's down
    for _ in range(3):
        api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
        api.post(f"/api/encounters/{eid}/next")
    assert not any(x.get("zone") for x in conds(api, eid, "Aria"))
    assert api.get(f"/api/maps/{mid}")["zones"] == []


def test_take_back_a_cast(api, battlemap, monkeypatch):
    eid, mid, by, loaded = setup(api, battlemap, monkeypatch)
    pa = battlemap["pa"]
    b0 = hp(api, eid, "Bandit 1")
    acts0 = pa.get("/api/play/state")["character"]["actions"]["used"]
    loaded.next(8, 8, 8, 2)
    r = pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": []})["cast"]
    assert hp(api, eid, "Bandit 1") < b0 and r["undo"]
    back = pa.post(f"/api/play/me/casts/{r['undo']}/undo", {})
    assert back["taken_back"] == "Spirit Guardians"
    assert hp(api, eid, "Bandit 1") == b0, "the damage is gone"
    aria = conds(api, eid, "Aria")
    assert not any(x.get("zone") or x.get("cooldown") for x in aria), "the zone and the cooldown are gone"
    assert pa.get("/api/play/state")["character"]["actions"]["used"] == acts0, "the action is back"
    log = [e["message"] for e in api.get(f"/api/encounters/{eid}")["log"]]
    assert any("took back Spirit Guardians" in m for m in log) and not any("casts Spirit Guardians" in m for m in log)
    pa.post(f"/api/play/me/casts/{r['undo']}/undo", {}, 400)                     # only once
    # too late once something else happened
    loaded.next(8, 8, 8, 2)
    r = pa.post("/api/play/me/use", {"what": "spell", "index": 0, "targets": []})["cast"]
    api.post(f"/api/combatants/{by['Bandit 2']['id']}/hp", {"op": "damage", "amount": 1})
    err = pa.post(f"/api/play/me/casts/{r['undo']}/undo", {}, 400)
    assert "Too late" in err["error"]


def test_dm_takes_back_and_players_only_their_own(api, battlemap, monkeypatch):
    eid, mid, by, loaded = setup(api, battlemap, monkeypatch)
    spec = {"name": "Fire Bolt", "effect": "damage", "level": 0, "dice": "1d10", "hit": "attack", "attack_bonus": 50}
    loaded.next(15, 7)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": spec, "targets": [by["Aria"]["id"]]})
    undo = st["cast"]["undo"]
    battlemap["pa"].post(f"/api/play/me/casts/{undo}/undo", {}, 403)              # not hers
    a_hp = next(c for c in st["combatants"] if c["name"] == "Aria")["hp"]
    st = api.post(f"/api/encounters/{eid}/casts/{undo}/undo", {})
    assert st["taken_back"] == "Fire Bolt" and next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == a_hp + 7
