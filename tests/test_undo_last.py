"""The DM's Undo last action: back to just before the most recent change in the fight, whatever
it was (a cast, damage, a move, a turn), one step at a time."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded


def state(api, eid):
    st = api.get(f"/api/encounters/{eid}")
    return st, {c["name"]: c for c in st["combatants"]}


def test_undo_last_action_step_by_step(api, battlemap, monkeypatch):
    monkeypatch.setattr(dice, "_rng", Loaded())
    eid, mid = battlemap["eid"], battlemap["mid"]
    api.post(f"/api/encounters/{eid}/start")
    st, by = state(api, eid)
    assert st["undo_last"]                                               # starting the fight is the last action
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    hp0 = by["Bandit 1"]["hp"]
    api.post(f"/api/combatants/{by['Bandit 1']['id']}/hp", {"op": "damage", "amount": 4})
    m = api.get(f"/api/maps/{mid}")
    t0 = tok(m, "Aria")
    api.post(f"/api/tokens/{t0['id']}/move", {"x": t0["x"] + 1, "y": t0["y"]})
    st, by = state(api, eid)
    assert st["undo_last"] == "Aria moved" and api.get(f"/api/maps/{mid}")["encounter"]["undo_last"] == "Aria moved"
    r = api.post(f"/api/encounters/{eid}/undo-last", {})
    assert r["undone"] == "Aria moved"
    assert (tok(api.get(f"/api/maps/{mid}"), "Aria")["x"], tok(api.get(f"/api/maps/{mid}"), "Aria")["y"]) == (t0["x"], t0["y"])
    r = api.post(f"/api/encounters/{eid}/undo-last", {})                # then the damage
    assert next(c for c in r["combatants"] if c["name"] == "Bandit 1")["hp"] == hp0
    api.post(f"/api/encounters/{eid}/next")
    cur = api.get(f"/api/encounters/{eid}")["encounter"]["current_id"]
    r = api.post(f"/api/encounters/{eid}/undo-last", {})                # a turn change, back too
    assert r["encounter"]["current_id"] == by["Aria"]["id"] != cur
    assert any("The DM undid" in e["message"] for e in r["log"])


def test_undo_a_cast(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    st, by = state(api, eid)
    loaded.next(15, 6)
    spec = {"name": "Fire Bolt", "effect": "damage", "dice": "1d10", "hit": "attack", "attack_bonus": 50}
    a0 = by["Aria"]["hp"]
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": spec, "targets": [by["Aria"]["id"]]})
    r = api.post(f"/api/encounters/{eid}/undo-last", {})
    assert "Fire Bolt" in r["undone"] and next(c for c in r["combatants"] if c["name"] == "Aria")["hp"] == a0
