"""In a running fight a player moves their hero only on their own turn, and only as far as
their speed (Dash doubles it). The DM moves anyone freely. Players' pings have a cooldown."""
import pytest

from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)


def setup(api, bm):
    camp, eid, mid = bm["camp"], bm["eid"], bm["mid"]
    api.patch(f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}}})
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    m = api.get(f"/api/maps/{mid}")
    me = tok(m, "Aria")
    api.post(f"/api/tokens/{me['id']}/move", {"x": 0, "y": 0})
    api.post(f"/api/encounters/{eid}/start")
    return me


def to_turn(api, eid, name):
    for _ in range(6):
        st = api.get(f"/api/encounters/{eid}")
        if next(c for c in st["combatants"] if c["id"] == st["encounter"]["current_id"])["name"] == name:
            return
        api.post(f"/api/encounters/{eid}/next")
    raise AssertionError(name + " never got a turn")


def test_only_on_your_turn_and_only_your_speed(api, battlemap):
    pa, eid = battlemap["pa"], battlemap["eid"]
    me = setup(api, battlemap)
    to_turn(api, eid, "Bandit 1")
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 1, "y": 0}, 403)
    assert "Wait for your turn" in r["error"]
    assert not tok(pa.get("/api/play/state")["map"], "Aria")["movable"]
    to_turn(api, eid, "Aria")
    st = pa.get("/api/play/state")
    assert st["character"]["move"] == {"my_turn": True, "speed": 30, "used": 0, "dash": False, "left": 30}
    assert tok(st["map"], "Aria")["movable"] is True
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 7, "y": 0}, 403)        # 35 ft
    assert "35 ft" in r["error"] and "30 ft" in r["error"]
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 4, "y": 4})             # diagonal: 4 squares = 20 ft
    assert r["move"]["left"] == 10
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 7, "y": 4}, 403)            # 15 ft, only 10 left
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 6, "y": 4})
    st = pa.get("/api/play/state")
    assert st["character"]["move"]["left"] == 0 and tok(st["map"], "Aria")["movable"] is False
    # Dash: another 30 ft, once
    pa.post("/api/play/me/dash", {})
    assert pa.get("/api/play/state")["character"]["move"]["left"] == 30
    pa.post("/api/play/me/dash", {}, 400)
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 12, "y": 4})
    # the DM still moves anyone, any distance, any time
    api.post(f"/api/tokens/{me['id']}/move", {"x": 25, "y": 0})
    # next round: a fresh 30 ft
    to_turn(api, eid, "Bandit 1")
    pa.post("/api/play/me/dash", {}, 403)                                          # not your turn
    to_turn(api, eid, "Aria")
    assert pa.get("/api/play/state")["character"]["move"]["left"] == 30


def test_speed_boosts_count(api, battlemap):
    pa, eid = battlemap["pa"], battlemap["eid"]
    me = setup(api, battlemap)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=[{"name": "Magic item", "effect": "buff", "aura": True, "speed_mult": 2, "area": "60 ft radius"}])
    api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": True})
    to_turn(api, eid, "Aria")
    assert pa.get("/api/play/state")["character"]["move"]["speed"] == 60
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 12, "y": 0})


def test_no_fight_no_limit(api, battlemap):
    pa = battlemap["pa"]
    camp, mid = battlemap["camp"], battlemap["mid"]
    api.patch(f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}}})
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    me = tok(api.get(f"/api/maps/{mid}"), "Aria")
    assert pa.get("/api/play/state")["character"]["move"] is None
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 20, "y": 0})


def test_ping_cooldown(api, battlemap, monkeypatch):
    import app.play as play
    pa, pb = battlemap["pa"], battlemap["pb"]
    api.post(f"/api/campaigns/{battlemap['camp']['id']}/live-map", {"map_id": battlemap["mid"]})
    pa.post("/api/play/ping", {"x": 1, "y": 1})
    r = pa.post("/api/play/ping", {"x": 2, "y": 1}, 429)
    assert "before pinging again" in r["error"]
    pb.post("/api/play/ping", {"x": 3, "y": 1})                                    # someone else isn't held up
    for _ in range(3):
        api.post(f"/api/maps/{battlemap['mid']}/ping", {"x": 1, "y": 1})           # the DM has no cooldown
    monkeypatch.setattr(play, "PING_COOLDOWN", 0)
    pa.post("/api/play/ping", {"x": 2, "y": 1})
