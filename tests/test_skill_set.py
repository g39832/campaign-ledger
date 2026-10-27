"""Skills can be typed in by hand: the number replaces the worked-out one everywhere (sheet,
rolls, passives, the player's phone); clearing it goes back to the worked-out number."""
from tests.test_dice_map_players import joined  # noqa: F401  (fixtures)


def test_a_skill_set_by_hand(api, joined):
    a = api.get(f"/api/characters/{joined['a']['id']}")["character"]
    a = api.set_char(a, abilities=dict(a["abilities"], wis=14), skill_profs={"perception": 1})
    assert a["derived"]["skills"]["perception"] == 4                               # +2 Wis, +2 proficiency
    a = api.set_char(a, skill_set={"perception": 9, "stealth": -1})
    assert a["derived"]["skills"]["perception"] == 9 and a["derived"]["skills"]["stealth"] == -1
    assert a["derived"]["passive_perception"] == 19
    r = api.post("/api/rolls", {"check": {"type": "skill", "key": "perception", "character_id": a["id"]}}, 201)["roll"]
    assert "+9" in r["expression"].replace(" ", "")
    phone = joined["pa"].get("/api/play/state")["character"]
    assert phone["derived"]["skills"]["perception"] == 9
    a = api.set_char(a, skill_set={"stealth": -1})                                  # cleared: worked out again
    assert a["derived"]["skills"]["perception"] == 4
