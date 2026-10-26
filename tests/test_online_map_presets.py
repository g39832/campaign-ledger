"""Spell areas, pings, map and encounter presets, and playing online through a tunnel."""
import pytest

from app import map_presets
from app.maps import BLOCKING
from tests.test_dice_map_players import remote


@pytest.fixture
def camp(api):
    return api.campaign("Online")


def test_every_map_preset_builds_inside_its_grid():
    from app.maps import TERRAIN
    for p in map_presets.listing():
        b = map_presets.build(p["key"])
        assert b["terrain"], p["key"]
        for key, kind in b["terrain"].items():
            x, y = map(int, key.split(","))
            assert 0 <= x < b["cols"] and 0 <= y < b["rows"], (p["key"], key)
            assert kind in TERRAIN, (p["key"], kind)


def test_new_map_from_preset(api, camp):
    names = [p["key"] for p in api.get("/api/map-presets")["presets"]]
    assert {"tavern", "cave", "forest", "dungeon", "bridge", "arena", "ship", "crypt"} <= set(names)
    st = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "tavern"}, 201)
    assert st["map"]["name"] == "Tavern common room" and st["map"]["terrain"]["0,0"] == "wall"
    st = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "cave", "name": "Goblin hole"}, 201)
    assert st["map"]["name"] == "Goblin hole" and st["map"]["cols"] == 30
    api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "moon-base"}, 400)


def test_encounter_preset_makes_fight_and_map(api, camp):
    a = api.character(camp["id"], name="Aria", max_hp=20)
    api.character(camp["id"], name="Bram", max_hp=25)
    presets = api.get("/api/encounter-presets")["presets"]
    assert len(presets) >= 8 and all(p["monsters"] for p in presets)
    d = api.post(f"/api/campaigns/{camp['id']}/encounter-presets/goblin-ambush", {}, 201)
    names = [c["name"] for c in d["encounter"]["combatants"]]
    assert set(names) == {"Aria", "Bram", "Goblin 1", "Goblin 2", "Goblin 3", "Goblin 4", "Goblin Boss"}
    gob = [c for c in d["encounter"]["combatants"] if c["name"] == "Goblin 1"][0]
    assert gob["max_hp"] == 7 and gob["ac"] == 15 and "Scimitar" in gob["statblock"]["attacks"]
    st = api.get(f"/api/maps/{d['map_id']}")
    assert st["encounter"]["id"] == d["encounter_id"] and len(st["tokens"]) == 7
    for t in st["tokens"]:  # nobody starts inside a tree, wall or the river
        assert st["map"]["terrain"].get(f"{int(t['x'])},{int(t['y'])}") not in BLOCKING, t
    assert api.get(f"/api/characters/{a['id']}")["character"]["current_hp"] == 20, "the party's HP is untouched"
    api.post(f"/api/campaigns/{camp['id']}/encounter-presets/nope", {}, 404)


def test_every_encounter_preset_uses_real_monsters_and_maps():
    from app.encounter_presets import PRESETS
    from app.monster_book import BY_NAME
    for key, _, _, monsters, map_key in PRESETS:
        assert map_key in map_presets.PRESETS, key
        for name, count in monsters:
            assert name in BY_NAME and count > 0, (key, name)


def test_spell_areas(api, camp):
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Field"}, 201)["map"]["id"]
    st = api.post(f"/api/maps/{mid}/shapes", {"kind": "circle", "x": 5, "y": 5, "size": 20, "label": "Fireball", "color": "#e0714f"}, 201)
    s = st["map"]["shapes"][0]
    assert (s["kind"], s["size"], s["label"]) == ("circle", 20, "Fireball")
    st = api.patch(f"/api/maps/{mid}/shapes/{s['id']}", {"x": 8, "dir": 450})
    s2 = st["map"]["shapes"][0]
    assert (s2["x"], s2["y"], s2["dir"], s2["label"]) == (8, 5, 90, "Fireball")
    api.post(f"/api/maps/{mid}/shapes", {"kind": "cone", "x": 1, "y": 1, "size": 15, "dir": 45, "hidden": True}, 201)
    for bad in ({"kind": "star", "x": 1, "y": 1}, {"kind": "line", "y": 1}, {"kind": "line", "x": 1, "y": 1, "size": "big"}):
        api.post(f"/api/maps/{mid}/shapes", bad, 400)
    api.patch(f"/api/maps/{mid}/shapes/nope", {"x": 1}, 404)
    # players see the area but not the hidden one
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    view = api.get(f"/api/maps/{mid}/player-preview")
    assert [x["label"] for x in view["map"]["shapes"]] == ["Fireball"] and "hidden" not in view["map"]["shapes"][0]
    st = api.delete(f"/api/maps/{mid}/shapes/{s['id']}")
    assert len(st["map"]["shapes"]) == 1
    assert api.delete(f"/api/maps/{mid}/shapes")["map"]["shapes"] == []


def test_pings_from_dm_and_players(app, api, camp):
    ch = api.character(camp["id"], name="Aria", max_hp=20)
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Field"}, 201)["map"]["id"]
    p = remote(app, "192.168.1.30")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": ch["id"]})
    p.post("/api/play/ping", {"x": 2, "y": 2}, 400)  # nothing shared yet
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    pings = p.post("/api/play/ping", {"x": 2.5, "y": 3.5})["pings"]
    assert pings[-1]["by"] == "Sam" and (pings[-1]["x"], pings[-1]["y"]) == (2.5, 3.5)
    api.post(f"/api/maps/{mid}/ping", {"x": 1, "y": 1})
    assert [x["by"] for x in api.get(f"/api/maps/{mid}")["pings"]] == ["Sam", "DM"]
    assert [x["by"] for x in p.get("/api/play/state")["map"]["pings"]] == ["Sam", "DM"]
    for _ in range(5):
        p.post("/api/play/ping", {"x": 1, "y": 1})
    assert len([x for x in api.get(f"/api/maps/{mid}")["pings"] if x["by"] == "Sam"]) == 3, "no spamming"
    p.post("/api/play/ping", {"x": 999, "y": 1}, 400)


def test_tunnel_visitors_are_not_the_dm_and_are_rate_limited_separately(app, api, camp):
    api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})
    c = app.test_client()
    tunnel = lambda ip: {"CF-Connecting-IP": ip, "Host": "abc.trycloudflare.com"}
    r = c.get("/api/campaigns", headers=tunnel("203.0.113.5"))
    assert r.status_code == 401, "someone coming through the tunnel is not the DM"
    for _ in range(10):
        c.get("/api/join/lookup?code=ZZZZZZ", headers=tunnel("203.0.113.5"))
    assert c.get("/api/join/lookup?code=ZZZZZZ", headers=tunnel("203.0.113.5")).status_code == 429
    r = c.get("/api/join/lookup?code=ZZZZZZ", headers=tunnel("198.51.100.7"))
    assert r.status_code == 404, "a different visitor isn't locked out by someone else's guessing"


def test_online_status_is_dm_only(app, api, monkeypatch):
    from app import online
    monkeypatch.setattr(online, "find_cloudflared", lambda: None)
    s = api.get("/api/online")
    assert s == s | {"installed": False, "running": False, "url": None} and "winget" in s["install_hint"]
    api.post("/api/online/start", {}, 400)
    r = app.test_client().get("/api/online", headers={"CF-Connecting-IP": "203.0.113.5", "Host": "x.trycloudflare.com"})
    assert r.status_code == 401
