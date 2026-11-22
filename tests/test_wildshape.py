"""2026-11-11: Zephyra Moonpetal, a level 15 Moon druid NPC (every attack +3 to hit), and Wild Shape:
the beast's HP, AC, speed and attacks swap in; at 0 she changes back and the rest carries over;
no spells in beast form; a bonus action on her turn; uses come back on a long rest."""
from app import zephyra
from app.db import get_db
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)


def _zephyra(api, app, bm, start=True):
    with app.app_context():
        conn = get_db()
        zid = zephyra.add(conn, bm["camp"]["id"])
        conn.commit()
    eid = bm["eid"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"characters": [zid]})
    z = next(c for c in st["combatants"] if c["character_id"] == zid)
    for c in st["combatants"]:
        roll = 30 if c["id"] == z["id"] else 5
        api.patch(f"/api/combatants/{c['id']}", {"changes": {"init_roll": {"from": c["init_roll"], "to": roll}}})
    if start:
        api.post(f"/api/encounters/{eid}/start")
    return eid, zid, z["id"]


def _me(api, eid, cid):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["id"] == cid)


def test_she_is_a_level_15_npc_druid_with_plus_3_attacks(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap)
    ch = api.get(f"/api/characters/{zid}")["character"]
    assert ch["kind"] == "npc" and ch["level"] == 15 and ch["class_name"] == "Druid"
    assert "pink alien antennas" in ch["appearance"] and "bug eyes" in ch["appearance"]
    assert not ch.get("portrait")
    assert ch["derived"]["spell"]["attack"] == 3 and ch["derived"]["spell"]["dc"] == 18
    assert all(a["bonus"] == "+3" for a in ch["attacks"])
    for f in zephyra.wildshape.MOON_FORMS:
        assert all(a["bonus"] == "+3" for a in f["attacks"]), f["name"]
    me = _me(api, eid, cid)
    assert me["spellcasting"]["attack"] == 3 and me["wild_shape"]["left"] == 2 and not me["wild_shape"]["active"]


def test_shift_swaps_in_the_beast_and_spells_are_off(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap)
    wolf = next(f["index"] for f in _me(api, eid, cid)["wild_shape"]["forms"] if f["name"] == "Dire Wolf")
    out = api.post(f"/api/characters/{zid}/wild-shape", {"form": wolf})
    assert out["character"]["max_hp"] == 37 and out["character"]["ac"] == 14 and out["character"]["speed"] == "50 ft."
    me = _me(api, eid, cid)
    assert me["hp"] == 37 and [a["name"] for a in me["attacks"]] == ["Bite"] and me["spells"] == []
    assert any(x["name"] == "Wild Shape: Dire Wolf" for x in me["conditions"])
    assert me["wild_shape"]["left"] == 1
    # a second shift (or change back) the same turn: the bonus action is spent
    api.post(f"/api/characters/{zid}/wild-shape", {"back": True}, expect=400)
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": cid, "spell": 0, "targets": [battlemap["combatants"][-1]["id"]]}, expect=400)


def test_beast_attacks_with_a_condition_still_work_in_beast_form(api, app, battlemap):
    """Bite (Prone), Tail Sweep, Moonquake Stomp... go through the cast path as moves: not blocked."""
    eid, zid, cid = _zephyra(api, app, battlemap)
    api.post(f"/api/characters/{zid}/wild-shape", {"form": 0})  # Dire Wolf
    me = _me(api, eid, cid)
    bite = next(a for a in me["attacks"] if a["name"] == "Bite")
    assert bite["cast"] and bite["cast"]["move"] and bite["cast"]["attack_bonus"] == 3
    foe = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Bandit"))
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": cid, "spell": bite["cast"], "targets": [foe["id"]]})
    assert "Bite" in st["cast"]["summary"]
    # her druid spells are still off in beast form
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": cid, "spell": 0, "targets": [foe["id"]]}, expect=400)


def test_damage_past_zero_changes_her_back_and_carries_over(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap)
    api.post(f"/api/characters/{zid}/wild-shape", {"form": 0})  # Dire Wolf, 37 HP
    st = api.post(f"/api/combatants/{cid}/hp", {"op": "damage", "amount": 10})
    assert _me(api, eid, cid)["hp"] == 27
    api.post(f"/api/combatants/{cid}/hp", {"op": "damage", "amount": 30})  # 27 in the wolf, 3 carry over
    me = _me(api, eid, cid)
    assert me["hp"] == 105 and me["max_hp"] == 108 and me["ac"] == 16 and me["status"] == "ok"
    assert not me["wild_shape"]["active"] and me["spells"]
    assert [a["name"] for a in me["attacks"]] == ["Moonwood Staff (Shillelagh)"]
    assert not any(x.get("wild_shape") for x in me["conditions"])
    log = " ".join(r["message"] for r in api.get(f"/api/encounters/{eid}")["log"])
    assert "changes back from a Dire Wolf" in log and "3 damage carries over" in log


def test_elementals_cost_two_and_long_rest_brings_uses_back(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap, start=False)  # outside a fight: any time, no bonus action
    forms = {f["name"]: f["index"] for f in _me(api, eid, cid)["wild_shape"]["forms"]}
    api.post(f"/api/characters/{zid}/wild-shape", {"form": forms["Earth Elemental"]})
    assert _me(api, eid, cid)["hp"] == 126 and _me(api, eid, cid)["wild_shape"]["left"] == 0
    api.post(f"/api/characters/{zid}/wild-shape", {"back": True})
    api.post(f"/api/characters/{zid}/wild-shape", {"form": forms["Dire Wolf"]}, expect=400)  # none left
    api.post(f"/api/characters/{zid}/long-rest")
    me = _me(api, eid, cid)
    assert me["wild_shape"]["left"] == 2 and me["hp"] == 108


def test_long_rest_while_shifted_changes_her_back(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap, start=False)
    api.post(f"/api/characters/{zid}/wild-shape", {"form": 1})
    api.post(f"/api/characters/{zid}/long-rest")
    ch = api.get(f"/api/characters/{zid}")["character"]
    assert ch["max_hp"] == 108 and ch["current_hp"] == 108 and ch["ac"] == 16


def test_moni_style_druid_sheet_gets_no_wild_shape(api, battlemap):
    """Only characters given forms can shift; a sheet that just says Druid can't."""
    aria = battlemap["a"]
    api.post(f"/api/characters/{aria['id']}/wild-shape", {"form": 0}, expect=400)


def test_trump_card_once_per_long_rest_on_top_of_her_uses_and_she_grows(api, app, battlemap):
    eid, zid, cid = _zephyra(api, app, battlemap, start=False)
    api.post(f"/api/maps/{battlemap['mid']}/tokens/from-encounter")
    forms = {f["name"]: f for f in _me(api, eid, cid)["wild_shape"]["forms"]}
    big = forms["Ancient Moon Behemoth"]
    assert big["trump"] and big["cost"] == 0 and big["hp"] == 250
    # spend both normal uses first: the trump card still works
    api.post(f"/api/characters/{zid}/wild-shape", {"form": forms["Earth Elemental"]["index"]})
    api.post(f"/api/characters/{zid}/wild-shape", {"back": True})
    api.post(f"/api/characters/{zid}/wild-shape", {"form": big["index"]})
    me = _me(api, eid, cid)
    assert me["hp"] == 250 and me["ac"] == 18 and me["wild_shape"]["active"]["trump"] and not me["wild_shape"]["trump_ready"]
    assert all(a["bonus"] == "+3" for a in zephyra.wildshape.MOON_FORMS[-1]["attacks"])
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert next(t for t in m["tokens"] if t["display"] == zephyra.NAME)["size"] == 3
    api.post(f"/api/characters/{zid}/wild-shape", {"back": True})
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert next(t for t in m["tokens"] if t["display"] == zephyra.NAME)["size"] == 1
    api.post(f"/api/characters/{zid}/wild-shape", {"form": big["index"]}, expect=400)  # once per long rest
    api.post(f"/api/characters/{zid}/long-rest")
    assert _me(api, eid, cid)["wild_shape"]["trump_ready"]


def test_portrait_is_drawn(app):
    img = zephyra.draw(128)
    assert img.size == (128, 128)
    # the antennas are pink: some pixel near the top is hot pink
    px = [img.getpixel((x, y)) for x in range(128) for y in range(10, 40)]
    assert any(r > 230 and 90 < g < 150 and b > 160 for r, g, b, a in px)
