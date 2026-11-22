"""Line of sight on made-up maps: 40 ft round each hero, stopped by walls; seen squares stay on the
map (dimmed when out of sight); enemies show to players only while a hero can see them."""
from app.vision import sight
from tests.test_dice_map_players import joined, remote  # noqa: F401  (fixtures)


def _corridor(length=20):
    """A one-square corridor along y = 1, walls above and below, from x = 0 to length - 1."""
    t = {}
    for x in range(length):
        t[f"{x},0"] = t[f"{x},2"] = "wall"
        t[f"{x},1"] = "stone"
    return t


def test_see_40_ft_down_a_corridor_and_no_further():
    s = sight(_corridor(), 20, 3, 0, 1, 1, 8)
    assert {(x, 1) for x in range(0, 9)} <= s, "8 squares (40 ft) down the hallway"
    assert (9, 1) not in s and (12, 1) not in s
    assert (3, 0) in s and (3, 2) in s, "the corridor's walls are seen too"


def test_walls_block_the_view():
    t = {f"{x},{y}": "stone" for x in range(10) for y in range(10)}
    for y in range(10):
        t[f"5,{y}"] = "wall"
    s = sight(t, 10, 10, 2, 5, 1, 8)
    assert (5, 5) in s, "the wall's face"
    assert not any((x, y) in s for x in range(6, 10) for y in range(10)), "nothing behind it"
    t["5,5"] = "door"  # an open doorway: you see through it
    s = sight(t, 10, 10, 2, 5, 1, 8)
    assert (7, 5) in s and (8, 5) in s
    t["5,5"] = "sealed"
    assert (7, 5) not in sight(t, 10, 10, 2, 5, 1, 8)


def test_no_peeking_between_walls_that_touch_at_a_corner():
    t = {f"{x},{y}": "stone" for x in range(5) for y in range(5)}
    t["1,0"] = t["0,1"] = "wall"   # two walls meeting diagonally at the hero's corner
    s = sight(t, 5, 5, 0, 0, 1, 8)
    assert (2, 2) not in s and (4, 4) not in s
    assert (1, 0) in s and (0, 1) in s


def test_see_round_a_room_through_its_doorway():
    t = {f"{x},{y}": "wall" for x in range(12) for y in range(9)}
    for x in range(1, 11):
        t[f"{x},1"] = "stone"         # a corridor
    for x in range(3, 9):
        for y in range(3, 8):
            t[f"{x},{y}"] = "stone"   # a room below it
    t["5,2"] = "door"
    s = sight(t, 12, 9, 5, 1, 1, 8)
    assert (5, 5) in s and (5, 7) in s, "straight through the doorway"
    assert (3, 3) not in s, "but not the corner of the room hidden behind the wall"
    assert {(x, 1) for x in range(1, 11)} <= s


def test_players_see_what_the_heroes_see(api, joined):
    camp, a, pa = joined["camp"], joined["a"], joined["pa"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "dungeon"}, 201)
    mid, m = st["map"]["id"], st["map"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    sx, sy = m["dungeon"]["start"]
    s = api.post(f"/api/maps/{mid}/party-to-start", {})
    view = pa.get("/api/play/state")["map"]["map"]
    me = next(t for t in s["tokens"] if t["character_id"] == a["id"])
    vis = view["visible"]
    assert vis and vis[int(me["y"]) * m["cols"] + int(me["x"])] == "1"
    assert all(view["revealed"][i] == "1" for i, c in enumerate(vis) if c == "1"), "what you see is remembered"
    # an enemy right next to the hero shows; one far away (out of sight) doesn't, even on a revealed square
    near = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "x": sx, "y": sy}, 201)
    far_room = max(m["dungeon"]["rooms"], key=lambda r: abs(r["box"][0] - sx) + abs(r["box"][1] - sy))
    api.post(f"/api/maps/{mid}/rooms/{m['dungeon']['rooms'].index(far_room)}/reveal", {"reveal": True})
    fx, fy = far_room["box"][0], far_room["box"][1]
    api.post(f"/api/maps/{mid}/monsters", {"book": "Orc", "x": fx, "y": fy}, 201)
    shown = [t["display"] for t in pa.get("/api/play/state")["map"]["tokens"]]
    assert any("Goblin" in n for n in shown), shown
    assert not any("Orc" in n for n in shown), "the orc is in a room they've seen, but nobody can see it now"
    assert near


def test_walking_reveals_what_you_see_on_the_way(api, joined):
    camp, a, pa = joined["camp"], joined["a"], joined["pa"]
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "prison"}, 201)
    pm = st["map"]["id"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": pm})
    d = st["map"]["dungeon"]
    tok = api.post(f"/api/maps/{pm}/tokens", {"character_id": a["id"], "x": d["start"][0], "y": d["start"][1]}, 201)
    t = next(x for x in tok["tokens"] if x["character_id"] == a["id"])
    before = pa.get("/api/play/state")["map"]["map"]["revealed"].count("1")
    # down the passage that joins the cell blocks (x 8..9, y 8..20)
    api.post(f"/api/tokens/{t['id']}/move", {"x": 8, "y": 9, "free": True})
    after = pa.get("/api/play/state")["map"]["map"]
    assert after["revealed"].count("1") > before
    cols = st["map"]["cols"]
    assert after["revealed"][16 * cols + 8] == "1", "7 squares down the passage, within 40 ft"
    assert after["visible"][9 * cols + 8] == "1"


def _hall(api, camp, a, b):
    """A made-up map (fog on) turned into one long corridor along y = 5, with Bram shut in a cupboard far away."""
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "dungeon"}, 201)
    mid, m = st["map"]["id"], st["map"]
    cols, rows = m["cols"], m["rows"]
    every = [[x, y] for x in range(cols) for y in range(rows)]
    api.post(f"/api/maps/{mid}/terrain", {"cells": every, "value": "wall"})
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[x, 5] for x in range(1, 36)] + [[2, 22]], "value": "stone"})
    # (the generated rooms are gone with the walls painted over them: forget them, so no two enemies
    # happen to share a "room" and come in together)
    import json
    with api.c.application.app_context():
        from app.db import get_db
        conn = get_db()
        d = json.loads(conn.execute("SELECT dungeon FROM maps WHERE id = ?", (mid,)).fetchone()["dungeon"])
        d["rooms"] = [r for r in d["rooms"] if r["kind"] == "start"]
        conn.execute("UPDATE maps SET dungeon = ? WHERE id = ?", (json.dumps(d), mid))
        conn.commit()
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    api.post(f"/api/maps/{mid}/tokens", {"character_id": a["id"], "x": 1, "y": 5}, 201)
    api.post(f"/api/maps/{mid}/tokens", {"character_id": b["id"], "x": 2, "y": 22}, 201)
    return mid


def _tok(api, mid, char_id):
    return next(t for t in api.get(f"/api/maps/{mid}")["tokens"] if t["character_id"] == char_id)


def test_only_an_enemy_in_your_view_starts_a_fight_with_just_you(api, joined):
    camp, a, b, pb = joined["camp"], joined["a"], joined["b"], joined["pb"]
    mid = _hall(api, camp, a, b)
    api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "x": 20, "y": 5, "hidden": True}, 201)  # darkvision 60 ft
    ta = _tok(api, mid, a["id"])
    st = api.post(f"/api/tokens/{ta['id']}/move", {"x": 6, "y": 5, "free": True})
    assert not st["map"]["dungeon"].get("fight"), "70 ft away: nobody sees anybody"
    st = api.post(f"/api/tokens/{ta['id']}/move", {"x": 9, "y": 5, "free": True})
    assert not st["map"]["dungeon"].get("fight"), "55 ft: the goblin's darkvision sees her, but it isn't in her view: no fight yet"
    st = api.post(f"/api/tokens/{ta['id']}/move", {"x": 12, "y": 5, "free": True})
    f = st["map"]["dungeon"].get("fight")
    assert f and f["foes"] == ["Goblin"] and "spots" in f["what"], "40 ft: it's on a lit square now, the fight starts"
    enc = api.get(f"/api/encounters/{f['eid']}")
    assert sorted(c["name"] for c in enc["combatants"]) == ["Aria", "Goblin"], "only the two of them"
    assert not any(c["hidden"] for c in enc["combatants"])
    # the rest of the party isn't pulled in by itself, even when the DM opens the map
    api.get(f"/api/maps/{mid}")
    assert len(api.get(f"/api/encounters/{f['eid']}")["combatants"]) == 2
    view = pb.get("/api/play/state")["map"]["map"]
    assert "spots" in view["fight_starting"]["what"]
    # the DM starts it, then brings Bram in: he rolls initiative and takes his place
    api.post(f"/api/maps/{mid}/room-fight", {"action": "start"})
    r = api.post(f"/api/maps/{mid}/fight-join", {"character_id": b["id"]})
    assert r["joined"] == "Bram" and r["rolled"]
    enc = api.get(f"/api/encounters/{f['eid']}")
    bram = next(c for c in enc["combatants"] if c["name"] == "Bram")
    assert bram["init_roll"] is not None and enc["encounter"]["status"] == "active"
    assert _tok(api, mid, b["id"])["combatant_id"] == bram["id"], "his token is his place in the fight"
    api.post(f"/api/maps/{mid}/fight-join", {"character_id": b["id"]}, 400)  # not twice


def test_you_spot_an_enemy_that_cant_see_as_far_and_walls_hide_others(api, joined):
    camp, a, b = joined["camp"], joined["a"], joined["b"]
    mid = _hall(api, camp, a, b)
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[20, 6], [20, 7]], "value": "stone"})  # a side passage
    api.post(f"/api/maps/{mid}/monsters", {"book": "Bandit", "x": 25, "y": 5}, 201)      # no darkvision: 40 ft
    api.post(f"/api/maps/{mid}/monsters", {"book": "Thug", "x": 20, "y": 7}, 201)        # round the corner
    ta = _tok(api, mid, a["id"])
    st = api.post(f"/api/tokens/{ta['id']}/move", {"x": 17, "y": 5, "free": True})
    f = st["map"]["dungeon"].get("fight")
    assert f and f["foes"] == ["Bandit"] and "spots" in f["what"], f
    assert "Thug" not in " ".join(f["foes"]), "the thug down the side passage is out of sight"


def test_sight_fights_dont_start_while_one_is_running(api, joined):
    camp, a, b = joined["camp"], joined["a"], joined["b"]
    mid = _hall(api, camp, a, b)
    api.post(f"/api/maps/{mid}/monsters", {"book": "Bandit", "x": 12, "y": 5}, 201)
    ta = _tok(api, mid, a["id"])
    f = api.post(f"/api/tokens/{ta['id']}/move", {"x": 6, "y": 5, "free": True})["map"]["dungeon"]["fight"]
    api.post(f"/api/maps/{mid}/room-fight", {"action": "start"})
    api.post(f"/api/maps/{mid}/monsters", {"book": "Bandit", "x": 30, "y": 5}, 201)
    st = api.post(f"/api/tokens/{ta['id']}/move", {"x": 7, "y": 5, "free": True})
    assert not st["map"]["dungeon"].get("fight") and st["map"]["encounter_id"] == f["eid"]
