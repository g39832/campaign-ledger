"""Moni's Entangle (a sheet attack, house rule): on a hit it knocks them Prone, the way her sheet says,
not the book spell's Restrained."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded


def test_entangle_knocks_them_prone(api, battlemap, monkeypatch):
    monkeypatch.setattr(dice, "_rng", Loaded())
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, attacks=[{"name": "Entangle ", "bonus": "1d20", "damage": "1d20", "notes": "Makes prone", "condition": "Prone"}])
    eid = battlemap["eid"]
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    m = api.get(f"/api/maps/{battlemap['mid']}")
    api.post(f"/api/tokens/{tok(m, 'Bandit 1')['id']}/move", {"x": tok(m, "Aria")["x"] + 1, "y": tok(m, "Aria")["y"], "free": True})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    for _ in range(6):  # until one lands
        r = battlemap["pa"].post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]})
        if r["cast"]["targets"][0]["how"] != "miss":
            break
        api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 2"]["id"]})
        api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    b = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 1")
    names = [x["name"] for x in b["conditions"]]
    assert "Prone" in names and "Restrained" not in names, (r["cast"]["targets"][0]["text"], names)
