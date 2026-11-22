"""A magic item's area attack on a sheet with its own save DC (Gnocchi's Meteor Strike from the
Astral Aegis): a barbarian with no spellcasting ability can use it; targets make a real DC 14
Dexterity save (even with the roll-to-hit house rule), half damage on a save; once a fight."""
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)

METEOR = {"name": "Meteor Strike (Astral Aegis)", "effect": "damage", "level": 3, "dice": "6d6", "damage_type": "fire",
          "hit": "dex", "dc": 14, "force_save": True, "save_half": True, "per_rest": True,
          "area": "15 ft radius, range 120", "notes": "Astral Aegis · once per dawn"}


def test_meteor_strike_uses_its_own_dc(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, class_name="Barbarian", spellcasting_ability="", spells=[METEOR])
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0,
                                                 "targets": [by["Bandit 1"]["id"], by["Bandit 2"]["id"]]})
    cast = st["cast"]
    assert len(cast["targets"]) == 2
    for t in cast["targets"]:
        assert t["how"] in ("saved", "failed") and t["vs"] == 14, t  # a real Dexterity save against 14
    hits = {t["how"]: t["amount"] for t in cast["targets"]}
    if "saved" in hits and "failed" in hits:
        assert hits["saved"] == hits["failed"] // 2  # half on a save, same roll for everyone
    # once per long rest: marked used on the sheet
    aid = battlemap["a"]["id"]
    assert api.get(f"/api/characters/{aid}")["character"]["spells"][0]["used"] is True
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [by["Bandit 1"]["id"]]}, 400)
    assert "after a long rest" in r["error"]
    # still used in the next fight
    api.post(f"/api/encounters/{eid}/end")
    eid2 = api.encounter(battlemap["camp"]["id"], "Next")["encounter"]["id"]
    s2 = api.post(f"/api/encounters/{eid2}/combatants", {"characters": [aid], "quick": {"name": "Wolf", "max_hp": 50}})
    api.post(f"/api/encounters/{eid2}/start")
    by2 = {c["name"]: c for c in api.get(f"/api/encounters/{eid2}")["combatants"]}
    api.post(f"/api/encounters/{eid2}/set-turn", {"combatant_id": by2["Aria"]["id"]})
    r = api.post(f"/api/encounters/{eid2}/cast", {"caster_id": by2["Aria"]["id"], "spell": 0, "targets": [by2["Wolf"]["id"]]}, 400)
    assert "after a long rest" in r["error"]
    # a long rest brings it back
    api.post(f"/api/characters/{aid}/long-rest")
    assert not api.get(f"/api/characters/{aid}")["character"]["spells"][0].get("used")
    st = api.post(f"/api/encounters/{eid2}/cast", {"caster_id": by2["Aria"]["id"], "spell": 0, "targets": [by2["Wolf"]["id"]]})
    assert api.get(f"/api/characters/{aid}")["character"]["spells"][0]["used"] is True
    # undoing that use makes it ready again
    api.post(f"/api/encounters/{eid2}/casts/{st['cast']['cast_id']}/undo")
    assert not api.get(f"/api/characters/{aid}")["character"]["spells"][0].get("used")


def test_the_player_screen_shows_it(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spellcasting_ability="", spells=[METEOR])
    sp = battlemap["pa"].get("/api/play/state")["character"]["spells"][0]
    assert sp["dc"] == 14 and sp["force_save"] and sp["hit"] == "dex" and sp["area"]["size"] == 15


def test_player_screen_says_used_until_a_long_rest(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spellcasting_ability="", spells=[dict(METEOR, used=True)])
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    sp = battlemap["pa"].get("/api/play/state")["character"]["spells"][0]
    assert sp["used"] and sp["recharging"] > 50000  # the screen: "used · back after a long rest", no Use button
