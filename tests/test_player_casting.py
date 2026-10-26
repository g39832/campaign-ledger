"""Players casting healing and buff spells on the party: tap the spell, then who."""
import pytest

from tests.conftest import Api
from tests.test_dice_map_players import remote

SPELLS = [
    {"name": "Cure Wounds", "effect": "heal", "dice": "1d8+mod", "hit": "", "condition": "", "rounds": None, "ac": None},
    {"name": "Shield of Faith", "effect": "effect", "dice": "", "hit": "", "condition": "Shield of Faith", "rounds": 100, "ac": 2},
    {"name": "Bless", "effect": "effect", "dice": "", "hit": "", "condition": "Blessed", "rounds": 10, "ac": None},
    {"name": "Fire Bolt", "effect": "damage", "dice": "1d10", "hit": "attack", "condition": "", "rounds": None, "ac": None},
    {"name": "Bane", "effect": "effect", "dice": "", "hit": "cha", "condition": "Baned", "rounds": 10, "ac": None},
]


@pytest.fixture
def party(app, api):
    camp = api.campaign("Party")
    cleric = api.character(camp["id"], name="Bram", max_hp=24, ac=12)
    cleric = api.set_char(cleric, spells=SPELLS, spellcasting_ability="wis",
                          abilities={"str": 10, "dex": 10, "con": 12, "int": 10, "wis": 16, "cha": 10})
    fighter = api.character(camp["id"], name="Aria", max_hp=30, ac=16)
    fighter = api.set_char(fighter, current_hp=10)
    other = api.campaign("Elsewhere")
    stranger = api.character(other["id"], name="Stranger", max_hp=10)
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.41")
    p.post("/api/join", {"code": code, "name": "Jo", "character_id": cleric["id"]})
    return {"camp": camp, "cleric": cleric, "fighter": fighter, "stranger": stranger, "p": p}


def test_player_sees_castable_spells(party):
    st = party["p"].get("/api/play/state")
    names = [s["name"] for s in st["character"]["spells"]]
    assert names == ["Cure Wounds", "Shield of Faith", "Bless", "Fire Bolt", "Bane"]
    assert st["character"]["can"]["cast_spells"] is True


def test_player_heals_an_ally_with_a_server_roll(api, party):
    r = party["p"].post("/api/play/cast", {"spell": 0, "targets": [party["fighter"]["id"]]})
    assert r["roll"]["kind"] == "heal" and 4 <= r["roll"]["total"] <= 11  # 1d8 + 3
    assert r["roll"]["outcome"] == f"Heals Aria for {r['roll']['total']}"
    aria = api.get(f"/api/characters/{party['fighter']['id']}")["character"]
    assert aria["current_hp"] == 10 + r["roll"]["total"]


def test_player_buffs_self_and_ally_with_ac(api, party):
    p = party["p"]
    r = p.post("/api/play/cast", {"spell": 1, "targets": [party["fighter"]["id"], party["cleric"]["id"]]})
    assert r["added"] == ["Aria", "Bram"] and r["effect"] == "Shield of Faith"
    st = p.get("/api/play/state")
    assert st["character"]["ac"] == 14 and st["character"]["ac_bonus"] == 2
    aria = api.get(f"/api/characters/{party['fighter']['id']}")["character"]
    assert [c["name"] for c in aria["conditions"]] == ["Shield of Faith"] and aria["conditions"][0]["ac"] == 2
    again = p.post("/api/play/cast", {"spell": 1, "targets": [party["fighter"]["id"]]})
    assert again["skipped"] == ["Aria"], "casting it twice doesn't stack"


def test_cast_in_a_fight_goes_through_the_encounter(api, party):
    camp = party["camp"]
    eid = api.encounter(camp["id"], "Fight")["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [party["cleric"]["id"], party["fighter"]["id"]],
                                                    "quick": {"name": "Goblin", "max_hp": 7, "count": 1}})
    api.post(f"/api/encounters/{eid}/start")
    party["p"].post("/api/play/cast", {"spell": 2, "targets": [party["fighter"]["id"]]})
    st = api.get(f"/api/encounters/{eid}")
    aria = next(c for c in st["combatants"] if c["name"] == "Aria")
    bram = next(c for c in st["combatants"] if c["name"] == "Bram")
    blessed = next(x for x in aria["conditions"] if x["name"] == "Blessed")
    assert blessed["rounds_left"] == 10 and blessed["tick_on"] == bram["id"], "counts down on the caster's turn"
    assert any(e["message"].startswith("Bram casts Bless: Aria — Blessed") for e in st["log"])


def test_cast_is_limited_to_the_party_and_helpful_spells(api, party):
    p = party["p"]
    p.post("/api/play/cast", {"spell": 1, "targets": [party["stranger"]["id"]]}, 403)
    p.post("/api/play/cast", {"spell": 3, "targets": [party["fighter"]["id"]]}, 400)  # Fire Bolt: a DM call
    p.post("/api/play/cast", {"spell": 4, "targets": [party["fighter"]["id"]]}, 400)  # Bane works against people
    p.post("/api/play/cast", {"spell": 9, "targets": [party["fighter"]["id"]]}, 400)
    p.post("/api/play/cast", {"spell": 0, "targets": []}, 400)
    camp = next(c for c in api.get("/api/campaigns")["campaigns"] if c["id"] == party["camp"]["id"])
    settings = camp["settings"]
    settings["players"]["cast_spells"] = False
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"from": {}, "to": settings}}})
    p.post("/api/play/cast", {"spell": 0, "targets": [party["fighter"]["id"]]}, 403)


def test_dm_cannot_be_spoofed_and_strangers_cannot_cast(app, party):
    Api(remote(app, "192.168.1.99").c).post("/api/play/cast", {"spell": 0, "targets": [party["fighter"]["id"]]}, 401)
