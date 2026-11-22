"""2026-11-15: Gnocchi's Reckless attack is now +2 to hit (on top of her usual bonus) for the rest of
her turn, and nothing else: her damage isn't doubled and her saving throws don't change. On the sheet
it's a row with no dice and "To hit +" 2."""
from app import dice
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

ROWS = [{"name": "Pasta", "bonus": "+2", "damage": "2d20 + 15"},
        {"name": "Reckless attack", "bonus": "", "damage": "", "hit_bonus": 2, "cooldown": 1,
         "notes": "+2 to hit on your attacks this turn"}]


def test_reckless_adds_two_to_hit_only(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, attacks=ROWS)
    eid = battlemap["eid"]
    by = {c["name"]: c for c in api.post(f"/api/encounters/{eid}/start")["combatants"]}
    me = by["Aria"]["id"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": me})
    row = next(a for a in by["Aria"]["attacks"] if a["name"] == "Reckless attack")
    assert row["stance_hit"] == 2 and row["stance"] == 1 and row["cast"] is None

    def hit(face):
        loaded.next(face)
        return api.post("/api/rolls", {"check": {"type": "attack", "key": 0, "combatant_id": me}}, 201)["roll"]

    def dmg():
        loaded.next(5, 5)
        return api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": me}}, 201)["roll"]

    assert hit(10)["total"] == 12, "usual: 10 + 2"
    st = api.post(f"/api/combatants/{me}/surge", {"index": 1})
    assert any("Aria uses Reckless attack: +2 to hit this turn" in e["message"] for e in st["log"])
    r = hit(10)
    assert r["total"] == 14 and "Reckless attack" in r["label"], "usual +2, plus Reckless +2"
    assert dmg()["total"] == 25, "damage as usual (5 + 5 + 15), not doubled"
    loaded.next(10)
    save = api.post("/api/rolls", {"check": {"type": "save", "key": "dex", "combatant_id": me}}, 201)["roll"]
    assert "Reckless" not in save["label"], "saves don't get it"
    # end of her turn: gone
    api.post(f"/api/encounters/{eid}/next")
    c = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    assert not any(x["name"] == "Reckless attack" and not x.get("cooldown") and not x.get("expired") for x in c["conditions"])
