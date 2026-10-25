"""Monster Book: ready-made stat blocks that copy into the creature library."""
import re

import pytest

from app import dice
from app import fields as F
from app.monster_book import BY_NAME, MONSTERS


@pytest.mark.parametrize("m", MONSTERS, ids=[m["name"] for m in MONSTERS])
def test_every_monster_is_a_valid_creature_with_rollable_attacks(m):
    F.validate_new(F.CREATURE, m)
    assert m["max_hp"] > 0 and m["ac"] > 0 and m["cr"]
    assert m["initiative_mod"] == (m["abilities"]["dex"] - 10) // 2
    lines = [l for l in m["attacks"].split("\n") if "to hit" in l]
    assert lines, "needs at least one attack the combat screen can roll"
    for line in lines:
        assert re.match(r"^\s*([^.:]{1,40})[.:]", line), line
        dmg = re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", line)
        if dmg:
            dice.parse(dmg.group(1).replace(" ", ""))


def test_known_stat_blocks():
    g = BY_NAME["Goblin"]
    assert (g["max_hp"], g["ac"], g["cr"], g["initiative_mod"]) == (7, 15, "1/4", 2)
    assert BY_NAME["Young Red Dragon"]["max_hp"] == 178 and BY_NAME["Troll"]["ac"] == 15


def test_browse_and_add_without_duplicates(api):
    camp = api.campaign()
    book = api.get(f"/api/monster-book?campaign_id={camp['id']}")
    assert len(book["monsters"]) == len(MONSTERS) and "CC BY 4.0" in book["attribution"]
    assert not any(m["in_library"] for m in book["monsters"])
    r = api.post("/api/monster-book/add", {"names": ["Goblin", "Wolf", "Goblin"], "campaign_id": camp["id"]})
    assert r["added"] == ["Goblin", "Wolf"] and r["skipped"] == []
    r = api.post("/api/monster-book/add", {"names": ["Goblin", "Ogre"], "campaign_id": camp["id"]})
    assert r["added"] == ["Ogre"] and r["skipped"] == ["Goblin"]
    names = [c["name"] for c in api.get("/api/creatures")["creatures"]]
    assert sorted(names) == ["Goblin", "Ogre", "Wolf"]
    book = api.get(f"/api/monster-book?campaign_id={camp['id']}")["monsters"]
    assert {m["name"] for m in book if m["in_library"]} == {"Goblin", "Ogre", "Wolf"}
    api.post("/api/monster-book/add", {"names": ["Tarrasque"]}, 400)
    api.post("/api/monster-book/add", {"names": []}, 400)
    api.post("/api/monster-book/add", {"names": [["x"]]}, 400)


def test_added_monster_works_in_combat_and_stays_editable(api):
    camp = api.campaign()
    api.post("/api/monster-book/add", {"names": ["Ogre"], "campaign_id": camp["id"]})
    ogre = next(c for c in api.get("/api/creatures")["creatures"] if c["name"] == "Ogre")
    eid = api.encounter(camp["id"])["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": ogre["id"], "count": 2})
    assert [c["name"] for c in s["combatants"]] == ["Ogre 1", "Ogre 2"]
    assert s["combatants"][0]["hp"] == 59 and s["combatants"][0]["statblock"]["attacks"].startswith("Greatclub")
    roll = api.post("/api/rolls", {"check": {"type": "save", "key": "str", "combatant_id": s["combatants"][0]["id"]}}, 201)["roll"]
    assert roll["expression"] == "1d20+4"
    api.patch(f"/api/creatures/{ogre['id']}", {"changes": {"max_hp": {"from": 59, "to": 70}}})
    assert api.get(f"/api/encounters/{eid}")["combatants"][0]["max_hp"] == 59, "editing the library doesn't change a fight"


def test_creatures_page_has_monster_book(api, client):
    api.campaign()
    html = client.get("/creatures").get_data(as_text=True)
    assert 'id="book"' in html and "Monster Book" in html and 'id="boot-encounters"' in html
