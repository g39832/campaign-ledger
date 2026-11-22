"""2026-11-15: Gnocchi's Totem Spirit: Bear. A buff on herself that lasts the whole fight: every kind of
damage but psychic is halved. Once a fight (the cooldown is the fight) and twice before a long rest."""
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)

BEAR = {"name": "Totem Spirit: Bear", "level": 0, "effect": "buff", "condition": "Bear Totem", "resist_all": True,
        "per_fight": True, "per_rest": True, "rest_uses": 2}


def hp(st, cid):
    return next(c for c in st["combatants"] if c["id"] == cid)["hp"]


def fight(api, battlemap, aid, name):
    eid = api.encounter(battlemap["camp"]["id"], name)["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [aid], "quick": {"name": "Ogre", "max_hp": 50}})
    api.post(f"/api/encounters/{eid}/start")
    me = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")["id"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": me})
    return eid, me


def test_bear_totem(api, battlemap):
    aid = battlemap["a"]["id"]
    aria = api.get(f"/api/characters/{aid}")["character"]
    api.set_char(aria, spells=[BEAR], current_hp=100, max_hp=100)
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    me = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")["id"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 10})
    assert hp(st, me) == 90, "no totem yet: full damage"
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": me})
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": me, "spell": 0, "targets": [me]})
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 11, "damage_type": "slashing", "attacker_id": me})
    assert hp(st, me) == 85, "halved, rounded down"
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 10, "damage_type": "psychic", "attacker_id": me})
    assert hp(st, me) == 75, "psychic isn't resisted"
    # still on many rounds later
    for _ in range(12):
        api.post(f"/api/encounters/{eid}/next")
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [me], "amount": 10})
    assert hp(st, me) == 70, "lasts the whole fight"
    row = api.get(f"/api/characters/{aid}")["character"]["spells"][0]
    assert row["spent"] == 1 and not row.get("used")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": me})
    r = api.post(f"/api/encounters/{eid}/cast", {"caster_id": me, "spell": 0, "targets": [me]}, 400)
    assert "this fight" in r["error"]
    # the fight ends: the totem goes
    api.post(f"/api/encounters/{eid}/end")
    e2, me2 = fight(api, battlemap, aid, "Second")
    st = api.post(f"/api/encounters/{e2}/damage", {"targets": [me2], "amount": 10})
    assert hp(st, me2) == 60
    cast = api.post(f"/api/encounters/{e2}/cast", {"caster_id": me2, "spell": 0, "targets": [me2]})
    row = api.get(f"/api/characters/{aid}")["character"]["spells"][0]
    assert row["spent"] == 2 and row["used"] is True
    # undo gives that use back
    api.post(f"/api/encounters/{e2}/casts/{cast['cast']['cast_id']}/undo")
    row = api.get(f"/api/characters/{aid}")["character"]["spells"][0]
    assert row["spent"] == 1 and not row.get("used")
    api.post(f"/api/encounters/{e2}/set-turn", {"combatant_id": me2})
    api.post(f"/api/encounters/{e2}/cast", {"caster_id": me2, "spell": 0, "targets": [me2]})
    api.post(f"/api/encounters/{e2}/end")
    # third fight the same day: none left
    e3, me3 = fight(api, battlemap, aid, "Third")
    r = api.post(f"/api/encounters/{e3}/cast", {"caster_id": me3, "spell": 0, "targets": [me3]}, 400)
    assert "after a long rest" in r["error"]
    api.post(f"/api/characters/{aid}/long-rest")
    row = api.get(f"/api/characters/{aid}")["character"]["spells"][0]
    assert not row.get("used") and not row.get("spent")
    api.post(f"/api/encounters/{e3}/cast", {"caster_id": me3, "spell": 0, "targets": [me3]})
