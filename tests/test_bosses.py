"""The creature library's Bosses: tick Boss on a creature and the library lists it with the bosses.
Nothing else about it changes: it goes into fights like any creature."""


def test_a_creature_can_be_a_boss(api):
    c = api.post("/api/creatures", {"name": "Lich king", "max_hp": 200, "ac": 17, "attacks": "Touch +9 to hit 3d6 cold"}, 201)["creature"]
    assert c["boss"] is False
    r = api.patch(f"/api/creatures/{c['id']}", {"changes": {"boss": {"from": False, "to": True}}})
    assert r["creature"]["boss"] is True
    listed = next(x for x in api.get("/api/creatures")["creatures"] if x["id"] == c["id"])
    assert listed["boss"] is True
    api.patch(f"/api/creatures/{c['id']}", {"changes": {"boss": {"from": True, "to": False}}})
    assert next(x for x in api.get("/api/creatures")["creatures"] if x["id"] == c["id"])["boss"] is False


def test_book_monsters_arent_bosses_and_bosses_still_fight(api):
    camp = api.campaign("Bosses")
    added = api.post("/api/monster-book/add", {"names": ["Goblin"], "campaign_id": camp["id"]})
    gob = next(x for x in added["creatures"] if x["name"] == "Goblin")
    assert gob["boss"] is False
    boss = api.post("/api/creatures", {"name": "Dragon", "max_hp": 150, "ac": 18, "attacks": "Bite +10 to hit 2d10+6", "boss": True}, 201)["creature"]
    assert boss["boss"] is True
    eid = api.encounter(camp["id"], "Lair")["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": boss["id"], "count": 1})
    d = next(c for c in st["combatants"] if c["name"] == "Dragon")
    assert d["hp"] == 150 and d["ac"] == 18 and d["statblock"]["attacks"] == "Bite +10 to hit 2d10+6"
