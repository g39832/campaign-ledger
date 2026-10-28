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
    p.post("/api/play/ping", {"x": 1, "y": 1}, 429)  # a cooldown between a player's pings
    import app.play as play
    play.PING_COOLDOWN, keep = 0, play.PING_COOLDOWN
    try:
        for _ in range(5):
            p.post("/api/play/ping", {"x": 1, "y": 1})
        assert len([x for x in api.get(f"/api/maps/{mid}")["pings"] if x["by"] == "Sam"]) == 3, "no spamming"
        p.post("/api/play/ping", {"x": 999, "y": 1}, 400)
    finally:
        play.PING_COOLDOWN = keep


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
    monkeypatch.setattr(online, "left_running", lambda: None)
    s = api.get("/api/online")
    assert s == s | {"installed": False, "running": False, "url": None} and "winget" in s["install_hint"]
    api.post("/api/online/start", {}, 400)
    r = app.test_client().get("/api/online", headers={"CF-Connecting-IP": "203.0.113.5", "Host": "x.trycloudflare.com"})
    assert r.status_code == 401


def test_a_tunnel_left_running_keeps_its_link(app, api, monkeypatch):
    """The app restarted, but the tunnel it started is still up: the same link shows, and Go online
    doesn't make a new one."""
    from app import online
    monkeypatch.setattr(online, "find_cloudflared", lambda: "cloudflared.exe")
    monkeypatch.setattr(online, "left_running", lambda: ("https://same-link.trycloudflare.com", 20241))
    monkeypatch.setattr(online.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no new tunnel")))
    s = api.get("/api/online")
    assert s["running"] and s["url"] == "https://same-link.trycloudflare.com" and s["kept"]
    s = api.post("/api/online/start", {})
    assert s["already"] and s["url"] == "https://same-link.trycloudflare.com"


def test_add_monsters_straight_onto_a_map(api, camp):
    hero = api.character(camp["id"], name="Aria", max_hp=20)
    st = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "forest"}, 201)
    mid = st["map"]["id"]
    assert st["map"]["encounter_id"] is None
    d = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 3, "x": 10, "y": 10}, 201)
    assert d["added"] == ["Goblin 1", "Goblin 2", "Goblin 3"] and d["encounter_created"]
    eid = d["map"]["encounter_id"]
    assert eid and d["encounter"]["id"] == eid, "the map got an encounter so the fight can be run"
    spots = {(int(t["x"]), int(t["y"])) for t in d["tokens"]}
    assert len(spots) == 3 and all(abs(x - 10) <= 2 and abs(y - 10) <= 2 for x, y in spots), "placed around the click"
    for x, y in spots:
        assert d["map"]["terrain"].get(f"{x},{y}") not in BLOCKING
    enc = api.get(f"/api/encounters/{eid}")
    gob = [c for c in enc["combatants"] if c["name"] == "Goblin 2"][0]
    assert (gob["max_hp"], gob["ac"]) == (7, 15) and "Scimitar" in gob["statblock"]["attacks"]
    # more of the same keep counting up; library creatures work too, and big ones take more squares
    d = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 1, "x": 10, "y": 10}, 201)
    assert d["added"] == ["Goblin 4"] and not d["encounter_created"]
    cid = api.post("/api/creatures", {"name": "Bog Hag", "max_hp": 40, "ac": 13, "creature_type": "Large fey"}, 201)["creature"]["id"]
    d = api.post(f"/api/maps/{mid}/monsters", {"creature_id": cid, "x": 3, "y": 3}, 201)
    hag = [t for t in d["tokens"] if t["display"] == "Bog Hag"][0]
    assert hag["size"] == 2 and hag["hp"] == 40
    for bad in ({"book": "Tarrasque"}, {"book": "Goblin", "count": 0}, {"book": "Goblin", "count": 50}, {}):
        api.post(f"/api/maps/{mid}/monsters", bad, 400)
    assert api.get(f"/api/characters/{hero['id']}")["character"]["current_hp"] == 20


def test_hidden_monsters_ambush_then_show(app, api, camp):
    ch = api.character(camp["id"], name="Aria", max_hp=20)
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.40")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": ch["id"]})
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "forest"}, 201)["map"]["id"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    api.post(f"/api/maps/{mid}/monsters", {"book": "Wolf", "count": 1, "x": 5, "y": 5}, 201)
    d = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 2, "x": 20, "y": 5, "hidden": True}, 201)
    eid = d["map"]["encounter_id"]
    names = lambda st: sorted(t["display"] for t in st["map"]["tokens"])
    order = lambda st: [o["name"] for o in st["encounter"]["order"]] if st["encounter"] else []
    api.post(f"/api/encounters/{eid}/start", {})
    st = p.get("/api/play/state")
    assert names(st) == ["Wolf"], "players can't see the ambushers on the map"
    assert "Goblin 1" not in order(st) and "Goblin 2" not in order(st), "...or in the turn order"
    dm = api.get(f"/api/maps/{mid}")
    assert sorted(t["display"] for t in dm["tokens"]) == ["Goblin 1", "Goblin 2", "Wolf"], "the DM sees everyone"
    # one at a time
    g1 = [t for t in dm["tokens"] if t["display"] == "Goblin 1"][0]
    api.post(f"/api/tokens/{g1['id']}/visibility", {"hidden": False})
    assert names(p.get("/api/play/state")) == ["Goblin 1", "Wolf"]
    # ...or all at once
    r = api.post(f"/api/maps/{mid}/reveal", {})
    assert r["revealed"] == 1
    st = p.get("/api/play/state")
    assert names(st) == ["Goblin 1", "Goblin 2", "Wolf"] and "Goblin 2" in order(st)
    log = [e["message"] for e in api.get(f"/api/encounters/{eid}")["log"]]
    assert any("revealed to players" in m for m in log)
    # and hiding again works, for the token and the turn order
    api.post(f"/api/tokens/{g1['id']}/visibility", {"hidden": True})
    st = p.get("/api/play/state")
    assert "Goblin 1" not in names(st) and "Goblin 1" not in order(st)
    # traps and markers stay hidden when everything is shown
    api.post(f"/api/maps/{mid}/tokens", {"kind": "trap", "label": "Pit", "x": 1, "y": 1, "hidden": True}, 201)
    api.post(f"/api/maps/{mid}/reveal", {})
    assert "Pit" not in names(p.get("/api/play/state"))


def test_heroes_on_a_map_join_its_fight(api, camp):
    """Bug: heroes placed on a map weren't in the fight that adding monsters made,
    so monsters couldn't attack them from the map ("isn't in this fight")."""
    lux = api.character(camp["id"], name="Lux", max_hp=20, ac=14)
    yam = api.character(camp["id"], name="Yamato", max_hp=25, ac=13)
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "tavern"}, 201)["map"]["id"]
    for ch, x in ((lux, 1), (yam, 2)):
        api.post(f"/api/maps/{mid}/tokens", {"character_id": ch["id"], "kind": "pc", "x": x, "y": 1}, 201)
    d = api.post(f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 2, "x": 10, "y": 6}, 201)
    enc = api.get(f"/api/encounters/{d['map']['encounter_id']}")
    assert {"Lux", "Yamato", "Goblin 1", "Goblin 2"} <= {c["name"] for c in enc["combatants"]}
    heroes = [t for t in d["tokens"] if t["character_id"]]
    assert len(heroes) == 2 and all(t["combatant_id"] for t in heroes), "hero tokens point at their combatant"
    assert any("joined the fight from the battle map" in e["message"] for e in enc["log"])
    # a hero added to the map later joins too
    gn = api.character(camp["id"], name="Gnocchi", max_hp=18)
    st = api.post(f"/api/maps/{mid}/tokens", {"character_id": gn["id"], "kind": "pc", "x": 3, "y": 1}, 201)
    assert next(t for t in st["tokens"] if t["display"] == "Gnocchi")["combatant_id"]
    # nobody is added twice, and deleting the fight leaves the heroes on the map
    api.get(f"/api/maps/{mid}")
    enc = api.get(f"/api/encounters/{d['map']['encounter_id']}")
    assert sorted(c["name"] for c in enc["combatants"] if c["kind"] == "pc") == ["Gnocchi", "Lux", "Yamato"]
    api.delete(f"/api/encounters/{enc['encounter']['id']}")
    left = api.get(f"/api/maps/{mid}")["tokens"]
    assert sorted(t["display"] for t in left if t["character_id"]) == ["Gnocchi", "Lux", "Yamato"]


def test_maps_made_before_the_fix_heal_themselves(api, camp, app):
    lux = api.character(camp["id"], name="Lux", max_hp=20)
    eid = api.encounter(camp["id"], "Tavern common room")["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"quick": {"name": "Mad mushroom", "max_hp": 10, "count": 1}})
    mid = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Old map"}, 201)["map"]["id"]
    api.post(f"/api/maps/{mid}/tokens", {"character_id": lux["id"], "kind": "pc", "x": 1, "y": 1}, 201)
    with app.app_context():  # how the old version left things: linked map, hero token not in the fight
        from app.db import get_db
        db = get_db()
        db.execute("UPDATE maps SET encounter_id = ? WHERE id = ?", (eid, mid))
        db.commit()
    st = api.get(f"/api/maps/{mid}")
    assert next(t for t in st["tokens"] if t["display"] == "Lux")["combatant_id"]
    assert "Lux" in {c["name"] for c in api.get(f"/api/encounters/{eid}")["combatants"]}


def test_sheet_rows_people_actually_write(api, camp):
    """'1d20' in the bonus box means roll a d20 (+0), not +1; a no-dice row with
    '+2 ac to target' is a buff; other no-dice rows are just notes."""
    from app import dice
    assert [dice.attack_bonus(b) for b in ("1d20", "1d20+2", "d20+3", "+5", "0", "")] == [0, 2, 3, 5, 0, None]
    lux = api.character(camp["id"], name="Lux", max_hp=13, ac=8)
    lux = api.set_char(lux, attacks=[{"name": "Entangle", "bonus": "1d20", "damage": "1d20", "notes": "Makes prone"},
                                     {"name": "Sheild of faith", "bonus": "", "damage": "", "notes": "+2 ac to target"},
                                     {"name": "Mold earth", "bonus": "", "damage": "", "notes": "Shape dirt"}])
    r = api.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": lux["id"]}}, 201)["roll"]
    assert r["expression"] == "1d20", "no stray +1"
    eid = api.encounter(camp["id"])["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"characters": [lux["id"]]})
    atk = {a["name"]: a for a in st["combatants"][0]["attacks"]}
    assert atk["Sheild of faith"]["ac"] == 2 and atk["Mold earth"]["ac"] == 0 and atk["Entangle"]["ac"] == 0
    assert atk["Mold earth"]["notes"] == "Shape dirt"


def test_combat_and_map_are_one_click_apart(api, camp):
    hero = api.character(camp["id"], name="Aria")
    eid = api.encounter(camp["id"], "Road")["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]], "quick": {"name": "Wolf", "max_hp": 11, "count": 1}})
    page = api.c.get(f"/combat/{eid}").get_data(as_text=True)
    assert 'id="open-map"' in page and "Make map" in page, "no map yet: the switch offers to make one"
    assert 'href="/combat"' in page, "the menu goes to the fight list until a fight is running"
    mid = api.post(f"/api/encounters/{eid}/map")["map_id"]
    api.post(f"/api/encounters/{eid}/start")
    page = api.c.get(f"/combat/{eid}").get_data(as_text=True)
    assert f'id="to-map" title="This fight on its battle map (M)"' in page and f'href="/map/{mid}"' in page
    m = api.c.get(f"/map/{mid}").get_data(as_text=True)
    assert f'href="/combat/{eid}" id="to-combat"' in m
    home = api.c.get("/").get_data(as_text=True)
    assert f'href="/combat/{eid}"' in home and f'href="/map/{mid}"' in home, "the top menu jumps into the running fight"
    other = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": "cave"}, 201)["map"]["id"]
    assert 'id="to-combat"' not in api.c.get(f"/map/{other}").get_data(as_text=True), "a map with no fight has no switch"


def test_area_attacks_know_their_shape_and_range(api, camp):
    from app.rules import parse_area
    assert parse_area("10 ft cone, range 20") == {"kind": "cone", "size": 10, "range": 20}
    assert parse_area("1 action · 90 ft · 20 ft square · concentration") == {"kind": "square", "size": 20, "range": 90}
    assert parse_area("150 ft · 20-foot radius") == {"kind": "circle", "size": 20, "range": 150}
    assert parse_area("1 action · 15 ft cone · fire") == {"kind": "cone", "size": 15, "range": 0}
    assert parse_area("10ft 3 turn cool down") is None
    yam = api.character(camp["id"], name="Yamato")
    yam = api.set_char(yam, attacks=[{"name": "Wide Slash", "bonus": "0", "damage": "2d12", "notes": "3 turn cool down", "area": "10 ft cone, range 20"},
                                     {"name": "Parry", "bonus": "0", "damage": "1d4", "notes": ""}],
                       spells=[{"name": "Burning Hands", "effect": "damage", "dice": "3d6", "hit": "dex", "notes": "1 action · 15 ft cone · fire"}])
    eid = api.encounter(camp["id"])["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"characters": [yam["id"]]})
    c = st["combatants"][0]
    assert c["attacks"][0]["area"] == {"kind": "cone", "size": 10, "range": 20} and c["attacks"][1]["area"] is None
    assert c["spells"][0]["area"] == {"kind": "cone", "size": 15, "range": 0}
