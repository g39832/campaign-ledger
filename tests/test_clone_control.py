"""Yamato's clones: he can have two out at once (Phantasmal Force and Echo Knight, one each), and
his player runs them from the phone on their turns: move them, attack with their Slash, end their turn."""
from tests.test_clone_parry import SPELLS, setup
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

ECHO = {"name": "Echo Knight", "effect": "buff", "level": 0, "summon": "Yamato clone", "per_fight": True}


def two_spells(api, bm):
    eid, by = setup(api, bm)
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, spells=SPELLS + [ECHO])
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 20}}})
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, by


def clones(st):
    return [c for c in st["combatants"] if c["name"].startswith("Yamato clone") and c["status"] not in ("dead", "defeated")]


def test_two_clones_at_once_not_three(api, battlemap):
    eid, by = two_spells(api, battlemap)
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 2, "targets": []})
    assert sorted(c["name"] for c in clones(st)) == ["Yamato clone 1", "Yamato clone 2"]
    # both act right after him
    names = [c["name"] for c in st["combatants"]]
    assert names[names.index("Aria") + 1:names.index("Aria") + 3] == ["Yamato clone 1", "Yamato clone 2"]
    # a third: no (Phantasmal Force again, once it's recharged)
    for _ in range(12):
        api.post(f"/api/encounters/{eid}/next")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []}, 400)
    assert "still standing" in err["error"] and "2 at a time" in err["error"]
    # one goes down: another can come
    api.post(f"/api/combatants/{clones(st)[0]['id']}/hp", {"op": "damage", "amount": 5})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    assert len(clones(st)) == 2


def test_his_player_runs_the_clone_on_its_turn(api, battlemap):
    eid, by = two_spells(api, battlemap)
    pa, pb = battlemap["pa"], battlemap["pb"]
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    clone = clones(st)[0]
    m = api.get(f"/api/maps/{battlemap['mid']}")
    ct, bandit = tok(m, "Yamato clone"), tok(m, "Bandit 2")
    api.post(f"/api/tokens/{ct['id']}/move", {"x": 10, "y": 3, "free": True})
    api.post(f"/api/tokens/{bandit['id']}/move", {"x": 15, "y": 3, "free": True})
    # on his own turn the clone stays put
    me = pa.get("/api/play/state")
    k = me["character"]["clones"][0]
    assert k["name"] == "Yamato clone" and not k["my_turn"] and k["attacks"] == [{"index": 0, "name": "Slash", "damage": "2d8", "reach": 5}]
    assert tok(me["map"], "Yamato clone")["pet"] and not tok(me["map"], "Yamato clone")["movable"]
    pa.post(f"/api/play/tokens/{ct['id']}/move", {"x": 11, "y": 3}, 403)
    pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]], "as": clone["id"]}, 403)
    # the clone's turn: his phone runs it
    pa.post("/api/play/me/end-turn", {"op_id": "end-aria"})
    me = pa.get("/api/play/state")
    k = me["character"]["clones"][0]
    assert k["my_turn"] and k["move"]["left"] == 30 and k["actions"]["left"] == 2
    assert tok(me["map"], "Yamato clone")["movable"]
    pa.post(f"/api/play/tokens/{ct['id']}/move", {"x": 17, "y": 3}, 403)            # 35 ft: too far
    # too far for Slash (5 ft)
    err = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]], "as": clone["id"], "op_id": "s0"}, 403)
    assert "5 ft" in err["error"] or "reach" in err["error"]
    pa.post(f"/api/play/tokens/{ct['id']}/move", {"x": 14, "y": 3})
    assert pa.get("/api/play/state")["character"]["clones"][0]["move"]["left"] == 10
    # Slash only: his own attacks and spells aren't the clone's
    pa.post("/api/play/me/use", {"what": "spell", "index": 1, "targets": [by["Bandit 2"]["id"]], "as": clone["id"], "op_id": "s1"}, 400)
    r = pa.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]], "as": clone["id"], "op_id": "s2"})
    assert r["cast"]["spell"] == "Slash" and r["cast"]["targets"][0]["name"] == "Bandit 2"
    assert "ac" not in r["cast"]["targets"][0]
    assert pa.get("/api/play/state")["character"]["clones"][0]["actions"]["left"] == 1
    # a misclick: he can take back what the clone did
    if r["cast"].get("undo"):
        pa.post(f"/api/play/me/casts/{r['cast']['undo']}/undo", {})
        assert pa.get("/api/play/state")["character"]["clones"][0]["actions"]["left"] == 2
    # another player can't touch it
    pb.post(f"/api/play/tokens/{ct['id']}/move", {"x": 13, "y": 3}, 403)
    pb.post("/api/play/me/use", {"what": "attack", "index": 0, "targets": [by["Bandit 2"]["id"]], "as": clone["id"], "op_id": "s3"}, 403)
    pb.post("/api/play/me/end-turn", {"as": clone["id"], "op_id": "e-b"}, 400)  # he isn't even in the fight
    # he ends the clone's turn
    pa.post("/api/play/me/end-turn", {"as": clone["id"], "op_id": "e-c"})
    st = api.get(f"/api/encounters/{eid}")
    assert st["encounter"]["current_id"] != clone["id"]
    assert not pa.get("/api/play/state")["character"]["clones"][0]["my_turn"]


def test_rolls_on_the_clones_turn_are_his_to_show(api, battlemap):
    eid, by = two_spells(api, battlemap)
    pa = battlemap["pa"]
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    pa.post("/api/play/me/end-turn", {"op_id": "end-aria2"})
    r = pa.post("/api/rolls", {"expression": "1d20", "label": "check"}, 201)
    assert not r.get("watching") and r["roll"]["visibility"] == "public"


def test_he_picks_where_the_clone_appears(api, battlemap):
    eid, by = two_spells(api, battlemap)
    pa, mid = battlemap["pa"], battlemap["mid"]
    bandit = tok(api.get(f"/api/maps/{mid}"), "Bandit 1")
    # not on someone, not off the map
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [],
                                                   "at": {"map_id": mid, "x": bandit["x"], "y": bandit["y"]}}, 400)
    assert "already standing there" in err["error"]
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [], "at": {"map_id": mid, "x": 50, "y": 1}}, 400)
    # the DM picks a square
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [], "at": {"map_id": mid, "x": 18, "y": 6}})
    c1 = tok(api.get(f"/api/maps/{mid}"), "Yamato clone")
    assert (c1["x"], c1["y"]) == (18, 6)
    # his player picks the square for Echo Knight's clone
    r = pa.post("/api/play/cast", {"spell": 2, "targets": [], "at": {"map_id": mid, "x": 12, "y": 0}})
    assert "Yamato clone 2" in r["cast"]["summary"]
    c2 = tok(api.get(f"/api/maps/{mid}"), "Yamato clone 2")
    assert (c2["x"], c2["y"]) == (12, 0)


def test_he_cant_pick_a_square_he_cant_see(api, battlemap):
    eid, by = two_spells(api, battlemap)
    pa, mid = battlemap["pa"], battlemap["mid"]
    api.patch(f"/api/maps/{mid}", {"changes": {"fog_enabled": {"from": False, "to": True}}})
    err = pa.post("/api/play/cast", {"spell": 0, "targets": [], "at": {"map_id": mid, "x": 15, "y": 5}}, 400)
    assert "can't see" in err["error"]
    assert not any(c["name"].startswith("Yamato clone") for c in api.get(f"/api/encounters/{eid}")["combatants"])
    pa.post("/api/play/cast", {"spell": 0, "targets": [], "at": {"map_id": mid + 999, "x": 1, "y": 1}}, 400)
    pa.post("/api/play/cast", {"spell": 0, "targets": []})       # no square: next to him, like before
    assert any(c["name"].startswith("Yamato clone") for c in api.get(f"/api/encounters/{eid}")["combatants"])
