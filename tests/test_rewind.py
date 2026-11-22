"""Time Reversal (Lux's Worldheart Fate Ring): right after a creature ends its turn, the ring's
owner sends it back to where that turn began — position, HP and what it spent — and it takes
the turn again. Once per long rest (Grayson's rule for limited magic items)."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

RING = {"name": "Time Reversal (Worldheart Fate Ring)", "effect": "buff", "rewind": True, "per_rest": True,
        "notes": "Legendary ring · once per long rest"}


def _setup(api, bm):
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, spells=[RING])
    eid = bm["eid"]
    for i, name in enumerate(("Aria", "Bandit 1", "Bandit 2")):  # all close together (well within 60 ft)
        api.post(f"/api/tokens/{tok(bm['state'], name)['id']}/move", {"x": 2 + i, "y": 2})
    api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    return eid, by


def test_ring_rewinds_the_turn_that_just_ended(api, battlemap):
    eid, by = _setup(api, battlemap)
    b1, aria = by["Bandit 1"], by["Aria"]
    hp0 = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"]
    # Bandit 1's turn: it walks off and hurts Aria
    api.post(f"/api/tokens/{tok(battlemap['state'], 'Bandit 1')['id']}/move", {"x": 7, "y": 6})
    api.post(f"/api/combatants/{aria['id']}/hp", {"op": "damage", "amount": 5})
    assert api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"] == hp0 - 5
    api.post(f"/api/encounters/{eid}/next")
    pa = battlemap["pa"]
    r = pa.get("/api/play/state")["character"]["rewind"]
    assert r["ok"] and r["target"] == "Bandit 1", r
    out = pa.post("/api/play/me/rewind", {})
    assert out["rewind"]["target"] == "Bandit 1"
    st = api.get(f"/api/encounters/{eid}")
    assert st["encounter"]["current_id"] == b1["id"]  # it takes its turn again
    assert api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"] == hp0  # HP back
    m = api.get(f"/api/maps/{battlemap['mid']}")
    t = next(t for t in m["tokens"] if t["display"] == "Bandit 1")
    assert (t["x"], t["y"]) == (3, 2)  # back where its turn began
    assert any("Time Reversal" in l["message"] for l in st["log"])
    # the ring is spent until a long rest
    assert api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["spells"][0]["used"] is True
    api.post(f"/api/encounters/{eid}/next")
    r = pa.post("/api/play/me/rewind", {}, 400)
    assert "long rest" in r["error"]
    # a long rest brings it back
    api.post(f"/api/characters/{battlemap['a']['id']}/long-rest")
    assert not api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["spells"][0].get("used")


def test_too_late_for_the_player_once_the_next_turn_got_going_but_the_dm_can(api, battlemap):
    eid, by = _setup(api, battlemap)
    api.post(f"/api/encounters/{eid}/next")
    nxt = api.get(f"/api/encounters/{eid}")["encounter"]["current_id"]
    api.post(f"/api/combatants/{nxt}/hp", {"op": "damage", "amount": 1})  # the next one does something
    r = battlemap["pa"].post("/api/play/me/rewind", {}, 400)
    assert "too late" in r["error"]
    st = api.post(f"/api/encounters/{eid}/rewind", {"caster_id": by["Aria"]["id"]})
    assert st["encounter"]["current_id"] == by["Bandit 1"]["id"] and st["rewind"]["target"] == "Bandit 1"


def test_nothing_to_rewind_before_anyone_ends_a_turn_and_no_ordinary_cast(api, battlemap):
    eid, by = _setup(api, battlemap)  # set-turn starts afresh: no ended turn yet
    r = api.post(f"/api/encounters/{eid}/rewind", {"caster_id": by["Aria"]["id"]}, 400)
    assert "ends its turn" in r["error"]
    r = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": [by["Bandit 1"]["id"]]}, 400)
    assert "its own button" in r["error"]
    dm = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Aria")
    assert dm["rewind"] and not dm["rewind"]["ok"]
