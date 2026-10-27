"""Monster spells, writing attacks and spells mid-fight, and the roll-to-hit house rule."""
import os
import sqlite3

from app import create_app, db as appdb
from tests.conftest import Api


def fight(api):
    camp = api.campaign()
    lib = api.post("/api/creatures", {"name": "Mad mushroom", "max_hp": 10, "ac": 7, "attacks": "Bite 1d4"}, 201)["creature"]
    eid = api.encounter(camp["id"], "Tavern")["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": lib["id"], "count": 3})
    return camp, lib, eid, st


def test_creatures_have_a_spells_box(api):
    cr = api.post("/api/creatures", {"name": "Hag", "max_hp": 30, "ac": 14, "spells": "Fire bolt +5 2d10\nWeb: Restrained 10 rounds"}, 201)["creature"]
    assert cr["spells"].startswith("Fire bolt")
    cr = api.patch(f"/api/creatures/{cr['id']}", {"changes": {"spells": {"from": cr["spells"], "to": "Heal 1d8 heal"}}})["creature"]
    assert cr["spells"] == "Heal 1d8 heal"


def test_write_attacks_and_spells_for_one_or_all_like_it(api):
    camp, lib, eid, st = fight(api)
    m1, m2, m3 = [c for c in st["combatants"] if c["name"].startswith("Mad mushroom")]
    st = api.post(f"/api/combatants/{m1['id']}/statblock", {"spells": "Spore cloud 2d6"})
    by = {c["id"]: c for c in st["combatants"]}
    assert by[m1["id"]]["statblock"]["spells"] == "Spore cloud 2d6"
    assert by[m1["id"]]["statblock"]["attacks"] == "Bite 1d4", "attacks are left alone"
    assert "spells" not in by[m2["id"]]["statblock"] or not by[m2["id"]]["statblock"]["spells"]
    st = api.post(f"/api/combatants/{m2['id']}/statblock", {"attacks": "Bite +3 to hit 1d4", "spells": "Spread: Poisoned 2 rounds", "all_like_it": True})
    for c in st["combatants"]:
        if c["name"].startswith("Mad mushroom"):
            assert c["statblock"]["attacks"] == "Bite +3 to hit 1d4" and c["statblock"]["spells"] == "Spread: Poisoned 2 rounds"
    assert any("Changed attacks and spells" in e["message"] for e in st["log"])
    lib_now = next(c for c in api.get("/api/creatures")["creatures"] if c["id"] == lib["id"])
    assert lib_now["spells"] == "Spread: Poisoned 2 rounds", "the library copy changes too, so new ones match"


def test_characters_attacks_are_not_edited_from_combat(api):
    camp = api.campaign()
    hero = api.character(camp["id"], name="Aria")
    eid = api.encounter(camp["id"])["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]]})
    api.post(f"/api/combatants/{st['combatants'][0]['id']}/statblock", {"attacks": "Bite 1d4"}, 400)


def test_roll_to_hit_rule_is_on_by_default_and_reaches_combat(api):
    camp, lib, eid, st = fight(api)
    assert st["settings"]["roll_to_hit"] is True


def test_migration_to_v6_adds_monster_spells(data_dir):
    create_app({"DATA_DIR": data_dir})
    path = os.path.join(data_dir, "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE creatures DROP COLUMN spells")
    conn.execute("ALTER TABLE combatants DROP COLUMN moved")
    conn.execute("PRAGMA user_version = 5")
    conn.commit(); conn.close()
    api = Api(create_app({"DATA_DIR": data_dir}).test_client())
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == appdb.SCHEMA_VERSION >= 6
    api.post("/api/creatures", {"name": "Bat", "max_hp": 1, "ac": 12, "spells": "Screech 1d4"}, 201)
