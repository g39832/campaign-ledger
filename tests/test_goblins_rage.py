"""2026-11-15: Gnocchi's Goblin's Rage: once a fight, the first hit that would drop her to 0 HP leaves
her on 1 instead. The second one that fight drops her as usual; the next fight it's back."""
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)

RAGE = {"name": "Goblin's Rage", "level": 0, "effect": "", "last_stand": True,
        "notes": "Once a fight: the first time she'd drop to 0 HP, she drops to 1 instead."}


def hp(st, cid):
    return next(c for c in st["combatants"] if c["id"] == cid)["hp"]


def test_goblins_rage_once_a_fight(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=[RAGE], current_hp=20, max_hp=20)
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    me = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")["id"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 50})
    assert hp(st, me) == 1, "Goblin's Rage: she stays on 1"
    assert any("Goblin's Rage" in line["message"] and "1 HP" in line["message"] for line in st["log"])
    assert any(x["name"] == "Goblin's Rage used this fight" for x in next(c for c in st["combatants"] if c["id"] == me)["conditions"])
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 5})
    assert hp(st, me) == 0, "only once a fight"
    # a new fight: it's back
    api.post(f"/api/encounters/{eid}/end")
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, current_hp=20, status="ok", death_failures=0, death_successes=0)
    e2 = api.encounter(battlemap["camp"]["id"], "Round two")["encounter"]["id"]
    api.post(f"/api/encounters/{e2}/combatants", {"characters": [aria["id"]], "quick": {"name": "Ogre", "max_hp": 50}})
    api.post(f"/api/encounters/{e2}/start")
    me2 = next(c for c in api.get(f"/api/encounters/{e2}")["combatants"] if c["name"] == "Aria")["id"]
    st = api.post(f"/api/encounters/{e2}/damage", {"targets": [me2], "amount": 50})
    assert hp(st, me2) == 1, "back again in the next fight"


def test_no_rage_row_drops_as_usual(api, battlemap):
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    me = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")["id"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 500})
    assert hp(st, me) == 0
