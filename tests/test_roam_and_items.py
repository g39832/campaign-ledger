"""Free roam (outside a fight, a hero walks one square at a time) and healing items used from the
player's screen (Stim injector: bonus action 2d4 + 2; Med-gel patch: action 1d4 + 1)."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

STIM = {"name": "Stim injector", "notes": "Uncommon · Bonus action: regain 2d4 + 2 hit points.", "qty": 2, "weight": 0.1}
PATCH = {"name": "Med-gel patch", "notes": "Common · Action: press it on a wound to regain 1d4 + 1 hit points.", "qty": 1, "weight": 0.1}
DRONE = {"name": "Medical drone", "notes": "Rare · Bonus action: a creature within 30 ft regains 2d6 hit points. Three charges, all back at dawn.", "qty": 1}
TORCH = {"name": "Torch", "notes": "Light for an hour.", "qty": 1}


def _live(api, bm):
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    return tok(bm["state"], "Aria")


def test_free_roam_one_square_at_a_time(api, battlemap):
    t = _live(api, battlemap)
    pa = battlemap["pa"]
    mine = next(x for x in pa.get("/api/play/state")["map"]["tokens"] if x.get("own"))
    assert mine["movable"] and mine["roam"]
    x, y = t["x"], t["y"]
    nx = x + 1 if x < 9 else x - 1
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": nx, "y": y})                       # one square: fine
    r = pa.post(f"/api/play/tokens/{t['id']}/move", {"x": nx, "y": min(7, y + 3) if y < 5 else y - 3}, 403)  # three: refused
    assert "one square at a time" in r["error"]
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": nx + (1 if nx < 9 else -1), "y": y + (1 if y < 7 else -1)})  # diagonal: fine


def test_free_roam_off_lets_them_drag_far_and_fights_use_speed(api, battlemap):
    t = _live(api, battlemap)
    camp = battlemap["camp"]["id"]
    api.patch(f"/api/campaigns/{camp}", {"changes": {"settings": {"to": {"players": {"free_roam": False}}}}})
    pa = battlemap["pa"]
    assert not next(x for x in pa.get("/api/play/state")["map"]["tokens"] if x.get("own")).get("roam")
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": 0, "y": 0})


def test_in_a_fight_its_their_speed_not_one_square(api, battlemap):
    t = _live(api, battlemap)
    api.post(f"/api/tokens/{t['id']}/move", {"x": 0, "y": 0})
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    pa = battlemap["pa"]
    assert not next(x for x in pa.get("/api/play/state")["map"]["tokens"] if x.get("own")).get("roam")
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": 3, "y": 0})  # 15 ft in one drag


def _hurt(api, bm, items):
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, equipment=items, current_hp=5)


def test_stim_and_patch_heal_and_get_used_up(api, battlemap):
    _hurt(api, battlemap, [TORCH, STIM, PATCH])
    pa = battlemap["pa"]
    inv = pa.get("/api/play/state")["character"]["inventory"]["items"]
    by = {i["name"]: i for i in inv}
    assert by["Torch"]["heal"] is None
    assert by["Stim injector"]["heal"] == {"dice": "2d4+2", "when": "bonus", "uses": None, "charges": None}
    assert by["Med-gel patch"]["heal"]["dice"] == "1d4+1" and by["Med-gel patch"]["heal"]["when"] == "action"
    d = pa.post("/api/play/me/item", {"index": by["Stim injector"]["index"]})
    assert 4 <= d["roll"]["total"] <= 10 and d["character"]["current_hp"] == 5 + d["roll"]["total"]
    stim = next(i for i in d["character"]["inventory"]["items"] if i["name"] == "Stim injector")
    assert stim["qty"] == 1
    hp = d["character"]["current_hp"]
    d = pa.post("/api/play/me/item", {"index": next(i for i in d["character"]["inventory"]["items"] if i["name"] == "Med-gel patch")["index"]})
    assert 2 <= d["roll"]["total"] <= 5 and d["character"]["current_hp"] == min(20, hp + d["roll"]["total"])
    assert not any(i["name"] == "Med-gel patch" for i in d["character"]["inventory"]["items"])  # the last one is gone
    pa.post("/api/play/me/item", {"index": 0}, 400)  # the torch doesn't heal


def test_in_a_fight_items_follow_action_and_bonus_action(api, battlemap):
    _hurt(api, battlemap, [dict(STIM, qty=3), dict(PATCH, qty=3)])
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    pa = battlemap["pa"]
    r = pa.post("/api/play/me/item", {"index": 0}, 403)
    assert "on your turn" in r["error"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    api.patch(f"/api/characters/{battlemap['a']['id']}", {"changes": {"current_hp": {"from": api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"], "to": 2}}})
    pa.post("/api/play/me/item", {"index": 0})                  # Stim: the bonus action
    r = pa.post("/api/play/me/item", {"index": 0}, 403)         # a second bonus action: no
    assert "bonus action" in r["error"]
    hp = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"]
    if hp < 20:
        d = pa.post("/api/play/me/item", {"index": 1})          # the patch: one of the two actions
        assert d["character"]["actions"]["used"] == 1


def test_charges_come_back_on_a_long_rest(api, battlemap):
    _hurt(api, battlemap, [DRONE])
    pa = battlemap["pa"]
    for _ in range(3):
        api.patch(f"/api/characters/{battlemap['a']['id']}", {"changes": {"current_hp": {"from": api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"], "to": 2}}})
        pa.post("/api/play/me/item", {"index": 0})
    api.patch(f"/api/characters/{battlemap['a']['id']}", {"changes": {"current_hp": {"from": api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["current_hp"], "to": 2}}})
    r = pa.post("/api/play/me/item", {"index": 0}, 400)
    assert "no charges left" in r["error"]
    api.post(f"/api/characters/{battlemap['a']['id']}/long-rest")
    item = pa.get("/api/play/state")["character"]["inventory"]["items"][0]
    assert item["heal"]["charges"]["left"] == 3


def test_dm_free_roam_button_holds_everyone_outside_a_fight(api, battlemap):
    """2026-11-15: the DM's Free roam button. Off: outside a fight players can't move (the phone says why);
    on: they walk again. In a fight they still move on their turn."""
    t = _live(api, battlemap)
    camp, pa = battlemap["camp"]["id"], battlemap["pa"]
    assert api.get(f"/api/maps/{battlemap['mid']}")["roam_open"] is True
    r = api.post(f"/api/campaigns/{camp}/roam", {"open": False})
    assert r["roam_open"] is False and api.get(f"/api/maps/{battlemap['mid']}")["roam_open"] is False
    mine = next(x for x in pa.get("/api/play/state")["map"]["tokens"] if x.get("own"))
    assert not mine["movable"] and mine["held"]
    x, y = t["x"], t["y"]
    nx = x + 1 if x < 9 else x - 1
    err = pa.post(f"/api/play/tokens/{t['id']}/move", {"x": nx, "y": y}, 403)
    assert "hasn't opened free roam" in err["error"]
    pa.post(f"/api/campaigns/{camp}/roam", {"open": True}, 403)  # players can't flip it
    # a fight: Aria moves on her turn even with it off
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": nx, "y": y})
    api.post(f"/api/encounters/{eid}/end")
    api.post(f"/api/campaigns/{camp}/roam", {"open": True})
    mine = next(x for x in pa.get("/api/play/state")["map"]["tokens"] if x.get("own"))
    assert mine["movable"] and not mine.get("held")
    pa.post(f"/api/play/tokens/{t['id']}/move", {"x": x, "y": y})
