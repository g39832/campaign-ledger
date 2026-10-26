"""Ending a fight clears conditions so they don't drag on into the next one. Switched-on
auras and spells lasting an hour or more (Aid) stay."""
from tests.test_spells import cast, eff, table, who  # noqa: F401  (fixtures)


def test_ending_a_fight_clears_conditions_but_keeps_long_spells(table):
    t = table
    api = t["api"]
    eid = t["eid"]
    api.post(f"/api/encounters/{eid}/start")
    cast(t, "Bram", 1, ["Ilse", "Bram"])            # Bless: concentration, 1 minute
    cast(t, "Bram", 6, ["Ilse"])                    # Aid: 8 hours, +5 max HP
    api.post(f"/api/combatants/{t['by']['Ilse']['id']}/conditions", {"name": "Poisoned"})
    st = api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "damage", "amount": 99})  # down: knocked prone
    assert eff(who(st, "Bram"), "Prone")
    api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "heal", "amount": 10})
    st = api.post(f"/api/encounters/{eid}/end")
    ilse, bram = who(st, "Ilse"), who(st, "Bram")
    assert [x["name"] for x in bram["conditions"]] == [], "Prone (knocked down at 0 HP) is gone"
    assert [x["name"] for x in ilse["conditions"]] == ["Aided"], "Poisoned and Blessed clear; Aid (8 hours) stays"
    assert ilse["max_hp"] == 27, "Aid's +5 max HP stays with it"
    assert any(e["message"].startswith("Cleared at the end of the fight:") and "Bram (Prone)" in e["message"] for e in st["log"])
    # and the sheet agrees
    sheet = api.get(f"/api/characters/{t['cleric']['id']}")["character"]
    assert sheet["conditions"] == []
