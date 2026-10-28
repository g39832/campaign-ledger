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
    api.post(f"/api/tokens/{me['id']}/move", {"x": 0, "y": 0, "free": True})
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
    assert st["character"]["move"] == {"my_turn": True, "speed": 30, "used": 0, "dash": False, "left": 30, "held": None, "budget": 30, "from": None}
    assert tok(st["map"], "Aria")["movable"] is True
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 7, "y": 0}, 403)        # 35 ft
    assert "35 ft" in r["error"] and "30 ft" in r["error"]
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 4, "y": 4})             # diagonal: 4 squares = 20 ft
    assert r["move"]["left"] == 10
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 7, "y": 4}, 403)            # 15 ft, only 10 left
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 6, "y": 4})
    st = pa.get("/api/play/state")
    assert st["character"]["move"]["left"] == 0 and tok(st["map"], "Aria")["movable"] is True  # used it all, can still readjust
    # Dash: another 30 ft, once
    pa.post("/api/play/me/dash", {})
    assert pa.get("/api/play/state")["character"]["move"]["left"] == 30
    pa.post("/api/play/me/dash", {}, 400)
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 12, "y": 4})
    # the DM's map follows the same rules in a fight; Free move ignores them
    err = api.post(f"/api/tokens/{me['id']}/move", {"x": 25, "y": 0}, 403)
    assert "Aria can only go" in err["error"]
    api.post(f"/api/tokens/{me['id']}/move", {"x": 25, "y": 0, "free": True})
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


def test_dm_map_moves_follow_turns_and_speed(api, battlemap):
    eid = battlemap["eid"]
    me = setup(api, battlemap)
    bandit = tok(api.get(f"/api/maps/{battlemap['mid']}"), "Bandit 1")
    to_turn(api, eid, "Aria")
    err = api.post(f"/api/tokens/{bandit['id']}/move", {"x": bandit["x"] - 1, "y": bandit["y"]}, 403)
    assert "not Bandit 1's turn" in err["error"]
    api.post(f"/api/tokens/{me['id']}/move", {"x": 6, "y": 0})                     # Aria: 30 ft on her turn
    api.post(f"/api/tokens/{me['id']}/move", {"x": 7, "y": 0}, 403)                # no more
    to_turn(api, eid, "Bandit 1")
    api.post(f"/api/tokens/{bandit['id']}/move", {"x": bandit["x"] - 6, "y": bandit["y"]})   # a bandit's 30 ft from its stat block


def test_player_ends_their_own_turn(api, battlemap):
    pa, eid = battlemap["pa"], battlemap["eid"]
    setup(api, battlemap)
    to_turn(api, eid, "Bandit 1")
    err = pa.post("/api/play/me/end-turn", {}, 403)
    assert "isn't your turn" in err["error"]
    to_turn(api, eid, "Aria")
    st = api.get(f"/api/encounters/{eid}")
    me = next(c for c in st["combatants"] if c["name"] == "Aria")
    pa.post("/api/play/me/end-turn", {"op_id": "end-1"})
    pa.post("/api/play/me/end-turn", {"op_id": "end-1"})                         # a retried tap doesn't skip anyone
    st = api.get(f"/api/encounters/{eid}")
    assert st["encounter"]["current_id"] != me["id"]
    assert any("Sam ended Aria's turn" in e["message"] for e in st["log"])
    assert pa.get("/api/play/state")["character"]["my_turn"] is False


def test_held_in_place_means_no_movement_anywhere(api, battlemap):
    """Grappled (or down): speed 0 on the phone, on the DM's map and in the reach box."""
    pa, eid, mid = battlemap["pa"], battlemap["eid"], battlemap["mid"]
    me = setup(api, battlemap)
    to_turn(api, eid, "Aria")
    aria = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    api.post(f"/api/combatants/{aria['id']}/conditions", {"name": "Grappled"})
    st = pa.get("/api/play/state")["character"]["move"]
    assert st["held"] == "Grappled" and st["left"] == 0
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 1, "y": 0}, 403)
    err = api.post(f"/api/tokens/{me['id']}/move", {"x": 1, "y": 0}, 403)
    assert "Aria is Grappled" in err["error"]
    assert api.get(f"/api/maps/{mid}")["move"]["left"] == 0
    api.post(f"/api/tokens/{me['id']}/move", {"x": 1, "y": 0, "free": True})        # Free move still works
    # a grappled monster too
    to_turn(api, eid, "Bandit 1")
    b1 = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 1")
    api.post(f"/api/combatants/{b1['id']}/conditions", {"name": "Restrained"})
    bt = tok(api.get(f"/api/maps/{mid}"), "Bandit 1")
    api.post(f"/api/tokens/{bt['id']}/move", {"x": bt["x"] - 1, "y": bt["y"]}, 403)


def test_they_can_readjust_after_placing_themselves(api, battlemap):
    """Movement is measured from where they started their turn: dragging again to fix the spot
    (even back toward the start) is fine, as long as they end within their speed of it."""
    pa, eid = battlemap["pa"], battlemap["eid"]
    me = setup(api, battlemap)
    to_turn(api, eid, "Aria")
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 6, "y": 0})                 # 30 ft: all of it
    st = pa.get("/api/play/state")
    assert st["character"]["move"]["left"] == 0 and tok(st["map"], "Aria")["movable"] is True, "she can still readjust"
    r = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 3, "y": 2})             # changed her mind: 15 ft from the start
    assert r["move"]["left"] == 15 and r["move"]["from"] == [0, 0]
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 6, "y": 6})                 # 30 ft from the start (diagonal)
    err = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 7, "y": 6}, 403)      # 35 ft from the start: too far
    assert "35 ft from where you started this turn" in err["error"]
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 0, "y": 0})                 # all the way back: fine
    assert pa.get("/api/play/state")["character"]["move"]["left"] == 30


def test_no_stacking_on_one_square(api, battlemap):
    """A hero or monster can't be moved onto a square someone already stands on (phone or DM map);
    the DM's Free move still can."""
    pa, eid, mid = battlemap["pa"], battlemap["eid"], battlemap["mid"]
    me = setup(api, battlemap)
    m = api.get(f"/api/maps/{mid}")
    bandit = tok(m, "Bandit 1")
    api.post(f"/api/tokens/{bandit['id']}/move", {"x": 2, "y": 0, "free": True})
    to_turn(api, eid, "Aria")
    err = pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 2, "y": 0}, 403)
    assert "Bandit 1 is already standing there" in err["error"]
    pa.post(f"/api/play/tokens/{me['id']}/move", {"x": 1, "y": 0})                # next to it is fine
    err = api.post(f"/api/tokens/{me['id']}/move", {"x": 2, "y": 0}, 403)          # the DM's map too
    assert "already standing there" in err["error"]
    api.post(f"/api/tokens/{me['id']}/move", {"x": 2, "y": 0, "free": True})       # Free move: anywhere
