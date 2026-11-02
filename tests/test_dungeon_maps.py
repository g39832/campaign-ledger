"""Made-up maps: every theme joins up from the start to the stairs, has a boss room, and the
stairs take the party to a new level (not while a fight is running on the map)."""
import pytest

from app.dungeon import THEMES, generate, path_len, room_at
from tests.test_dice_map_players import joined, remote  # noqa: F401  (fixtures)


@pytest.mark.parametrize("theme", list(THEMES))
def test_every_layout_has_a_boss_room_and_reaches_the_stairs(theme):
    for seed in range(1, 60):
        g = generate(theme, seed)
        kinds = [r["kind"] for r in g["rooms"]]
        assert kinds.count("boss") == 1 and kinds.count("start") == 1
        boss = next(r for r in g["rooms"] if r["kind"] == "boss")
        assert room_at([boss], *g["exit"]), "the stairs are in the boss room"
        assert g["terrain"][f"{g['exit'][0]},{g['exit'][1]}"] == "stairs"
        assert path_len(g["terrain"], g["start"], g["exit"], g["cols"], g["rows"]) is not None
    assert generate(theme, 5)["terrain"] == generate(theme, 5)["terrain"], "the same seed, the same map"
    assert generate(theme, 5)["terrain"] != generate(theme, 6)["terrain"]


def test_a_prison_has_cells():
    assert sum(r["kind"] == "cell" for r in generate("prison", 3)["rooms"]) >= 6


def _hero_on(api, mid, char_id, xy):
    t = api.post(f"/api/maps/{mid}/tokens", {"character_id": char_id, "x": xy[0], "y": xy[1]}, 201)
    return next(x for x in t["tokens"] if x["character_id"] == char_id)


def test_stairs_take_the_party_down_and_the_players_follow(api, joined):
    camp, a, b = joined["camp"], joined["a"], joined["b"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "prison"}, 201)
    m, mid = st["map"], st["map"]["id"]
    d = m["dungeon"]
    assert m["fog_enabled"] and m["name"] == "Prison — level 1" and d["level"] == 1
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    view = joined["pa"].get("/api/play/state")["map"]
    assert "dungeon" not in view["map"], "players never get the rooms or where the stairs are"
    sx, sy = d["start"]
    assert view["map"]["revealed"][sy * m["cols"] + sx] == "1"
    ex, ey = d["exit"]
    assert view["map"]["revealed"][ey * m["cols"] + ex] == "0", "the boss room starts hidden"
    ta = _hero_on(api, mid, a["id"], d["start"])
    _hero_on(api, mid, b["id"], [sx, sy + 1])
    # the DM shows the boss room, then hides it again
    boss = next(i for i, r in enumerate(d["rooms"]) if r["kind"] == "boss")
    s = api.post(f"/api/maps/{mid}/rooms/{boss}/reveal", {"reveal": True})
    assert s["map"]["revealed"][ey * m["cols"] + ex] == "1"
    api.post(f"/api/maps/{mid}/rooms/{boss}/reveal", {"reveal": False})
    # a fight on the map holds the stairs shut
    eid = api.encounter(camp["id"], "Guards")["encounter"]["id"]
    api.patch(f"/api/maps/{mid}", {"changes": {"encounter_id": {"from": None, "to": eid}}})
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [a["id"]], "quick": {"name": "Guard", "max_hp": 5}})
    api.post(f"/api/encounters/{eid}/start")
    r = api.post(f"/api/tokens/{ta['id']}/move", {"x": ex, "y": ey, "free": True})
    assert r["next_level"]["blocked"]
    api.post(f"/api/encounters/{eid}/end")
    # Aria's player steps onto the stairs from next to them
    api.post(f"/api/tokens/{ta['id']}/move", {"x": ex - 1, "y": ey, "free": True})
    r = joined["pa"].post(f"/api/play/tokens/{ta['id']}/move", {"x": ex, "y": ey})
    went = r["next_level"]
    assert went["level"] == 2 and went["live"] and went["name"] == "Prison — level 2"
    st2 = api.get(f"/api/maps/{went['map_id']}")
    assert {t["character_id"] for t in st2["tokens"]} == {a["id"], b["id"]}, "the whole party goes down"
    assert st2["map"]["dungeon"]["prev"] == mid and api.get(f"/api/maps/{mid}")["map"]["dungeon"]["next"] == went["map_id"]
    assert joined["pb"].get("/api/play/state")["map"]["map"]["id"] == went["map_id"], "the players see the new level"
    # going down again from level 1 uses the level already made
    assert api.post(f"/api/maps/{mid}/next-level")["next_level"]["map_id"] == went["map_id"]


def test_walking_into_a_room_lights_it_up(api, joined):
    camp, a = joined["camp"], joined["a"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "dungeon"}, 201)
    m, d = st["map"], st["map"]["dungeon"]
    room = next(r for r in d["rooms"] if r["kind"] == "room")
    x0, y0, x1, y1 = room["box"]
    assert st["map"]["revealed"][y1 * m["cols"] + x1] == "0"
    t = _hero_on(api, m["id"], a["id"], d["start"])
    s = api.post(f"/api/tokens/{t['id']}/move", {"x": x0, "y": y0, "free": True})
    assert s["map"]["revealed"][y1 * m["cols"] + x1] == "1"


def test_party_to_start_and_a_new_layout(api, joined):
    camp, a, b = joined["camp"], joined["a"], joined["b"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "jungle"}, 201)
    mid, d = st["map"]["id"], st["map"]["dungeon"]
    assert st["map"]["name"] == "Jungle — level 1" and any(r["kind"] == "boss" for r in d["rooms"])
    st = api.post(f"/api/maps/{mid}/party-to-start")
    near = lambda t, xy: max(abs(t["x"] - xy[0]), abs(t["y"] - xy[1])) <= 2
    heroes = [t for t in st["tokens"] if t["kind"] == "pc"]
    assert {t["character_id"] for t in heroes} == {a["id"], b["id"]} and all(near(t, d["start"]) for t in heroes)
    api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 1, "x": d["exit"][0] - 2, "y": d["exit"][1]}, 201)
    st = api.post(f"/api/maps/{mid}/reroll")
    d2 = st["map"]["dungeon"]
    assert d2["seed"] != d["seed"] and d2["theme"] == "jungle" and d2["level"] == 1
    assert [t["kind"] for t in st["tokens"]] == ["pc", "pc"], "the monster on the old layout is gone, the heroes stay"
    assert all(near(t, d2["start"]) for t in st["tokens"])
