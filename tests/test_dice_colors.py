"""Dice colors: each character's own (the DM sets them on the sheet, the player on their screen),
and everyone sees that character's rolls in them. Rolls without a character stay classic."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)


def test_the_player_picks_their_dice_colors(api, joined):
    pa, a = joined["pa"], joined["a"]
    assert pa.get("/api/play/state")["character"]["dice_style"] is None          # classic to start with
    r = pa.post("/api/play/me/dice", {"body": "#4B2A6B", "ink": "#f2e6ff"})
    assert r["dice_style"] == {"body": "#4b2a6b", "ink": "#f2e6ff"}
    assert api.get(f"/api/characters/{a['id']}")["character"]["dice_style"] == {"body": "#4b2a6b", "ink": "#f2e6ff"}
    # their rolls carry the colors, for everyone
    roll = pa.post("/api/rolls", {"expression": "1d20", "label": "check"}, 201)["roll"]
    assert roll["dice"] == {"body": "#4b2a6b", "ink": "#f2e6ff"}
    listed = next(x for x in api.get("/api/rolls")["rolls"] if x["id"] == roll["id"])
    assert listed["dice"] == {"body": "#4b2a6b", "ink": "#f2e6ff"}
    # nonsense is refused; {} goes back to classic
    pa.post("/api/play/me/dice", {"body": "red", "ink": "#fff"}, 400)
    pa.post("/api/play/me/dice", {"body": "#123456", "ink": "javascript:x"}, 400)
    pa.post("/api/play/me/dice", {})
    assert pa.get("/api/play/state")["character"]["dice_style"] is None


def test_numbers_stay_readable(api, joined):
    pa = joined["pa"]
    r = pa.post("/api/play/me/dice", {"body": "#111111", "ink": "#151515"})       # black on black
    assert r["dice_style"]["ink"] == "#ffffff"
    r = pa.post("/api/play/me/dice", {"body": "#f5f5f5", "ink": "#ffffff"})       # white on white
    assert r["dice_style"]["ink"] == "#111111"


def test_the_dm_sets_them_on_the_sheet_and_fight_rolls_use_them(api, battlemap):
    a = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(a, dice_style={"body": "#1f4e79", "ink": "#e8f4ff"},
                 attacks=[{"name": "Bite", "bonus": "+5", "damage": "1d8"}])
    eid = battlemap["eid"]
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    m = api.get(f"/api/maps/{battlemap['mid']}")
    api.post(f"/api/tokens/{tok(m, 'Bandit 1')['id']}/move", {"x": tok(m, "Aria")["x"] + 1, "y": tok(m, "Aria")["y"], "free": True})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = battlemap["pa"].post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 1"]["id"]]})
    assert r["cast"]["rolls"] and all(x["dice"] == {"body": "#1f4e79", "ink": "#e8f4ff"} for x in r["cast"]["rolls"])
    # a bandit's roll (no character): classic dice
    br = api.post("/api/rolls", {"expression": "1d20+3", "label": "Scimitar", "subject": "Bandit 1"}, 201)["roll"]
    assert br["dice"] is None


def test_a_player_cant_change_someone_elses_dice(api, joined):
    pb = joined["pb"]
    pb.post("/api/play/me/dice", {"body": "#8e1b1b", "ink": "#fbe9d0"})
    assert api.get(f"/api/characters/{joined['a']['id']}")["character"]["dice_style"] == {}
    assert api.get(f"/api/characters/{joined['b']['id']}")["character"]["dice_style"] == {"body": "#8e1b1b", "ink": "#fbe9d0"}
