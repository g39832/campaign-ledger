"""Tests for dice, roll history and visibility, players joining, permissions,
battle maps, fog of war and the v1 -> v2 database migration."""
import io
import json
import os
import random
import sqlite3

import pytest

from app import create_app, db as appdb, dice
from tests.conftest import Api


def remote_client(app, ip="192.168.1.50"):
    """A client that looks like another device on the network."""
    c = app.test_client()
    c.environ_base["REMOTE_ADDR"] = ip
    return c


def remote(app, ip="192.168.1.50"):
    return Api(remote_client(app, ip))


# ---- dice engine --------------------------------------------------------------

@pytest.mark.parametrize("expr,norm", [
    ("d20", "1d20"), ("1d20+5", "1d20+5"), ("2d6 + 3", "2d6+3"), ("4d8-1", "4d8-1"), ("D%", "1d100"),
    ("2d20kh1", "2d20kh1"), ("2d20KL1", "2d20kl1"), ("4d6dl1", "4d6dl1"), ("3d6+1d4+2", "3d6+1d4+2"),
    ("-1+d4", "-1+1d4"), ("1d4", "1d4"), ("1d12", "1d12"), ("1d10", "1d10"),
])
def test_parse_and_normalize(expr, norm):
    assert dice.normalize(dice.parse(expr)) == norm


@pytest.mark.parametrize("bad", ["", "abc", "1d7", "d20++5", "5+", "0d6", "51d6", "60d6+50d6", "1d6kh3", "4d6dl4",
                                 "__import__('os')", "1d20; drop", "2**8", "1d20+5000", "1d6" + "+1" * 40, "(1d6)", "1d6*2"])
def test_invalid_expressions_rejected(bad):
    with pytest.raises(dice.DiceError):
        dice.parse(bad)


def test_every_die_size_stays_in_range():
    rng = random.Random(7)
    for sides in (4, 6, 8, 10, 12, 20, 100):
        r = dice.roll(f"20d{sides}", rng=rng)
        vals = [x["value"] for x in r["terms"][0]["rolls"]]
        assert all(1 <= v <= sides for v in vals)
        assert r["total"] == sum(vals)


def test_modifiers_and_totals():
    r = dice.roll("2d6+3-1", rng=random.Random(1))
    rolls = [x["value"] for x in r["terms"][0]["rolls"]]
    assert r["modifier"] == 2 and r["total"] == sum(rolls) + 2


def test_keep_and_drop():
    rng = random.Random(3)
    r = dice.roll("4d6dl1", rng=rng)
    vals = [x["value"] for x in r["terms"][0]["rolls"]]
    kept = [x["value"] for x in r["terms"][0]["rolls"] if x["kept"]]
    assert len(kept) == 3 and sum(kept) == sum(vals) - min(vals) == r["total"]
    r = dice.roll("2d20kl1", rng=rng)
    vals = [x["value"] for x in r["terms"][0]["rolls"]]
    assert r["total"] == min(vals) and r["natural"] == min(vals)


def test_advantage_disadvantage():
    rng = random.Random(11)
    a = dice.roll("1d20+4", mode="advantage", rng=rng)
    vals = [x["value"] for x in a["terms"][0]["rolls"]]
    assert len(vals) == 2 and a["total"] == max(vals) + 4 and a["expression"] == "2d20kh1+4" and a["mode"] == "advantage"
    d = dice.roll("1d20+4", mode="disadvantage", rng=rng)
    assert d["total"] == min(x["value"] for x in d["terms"][0]["rolls"]) + 4
    n = dice.roll("2d6", mode="advantage", rng=rng)  # no single d20: nothing to apply
    assert n["mode"] == "normal" and len(n["terms"][0]["rolls"]) == 2


def test_crit_doubles_dice_not_modifier():
    r = dice.roll("1d8+3", crit=True, rng=random.Random(5))
    assert r["expression"] == "2d8+3"


def test_damage_and_bonus_extraction():
    assert dice.damage_expression("1d8+3 slashing") == "1d8+3"
    assert dice.damage_expression("Hit: 5 (1d6 + 2) piercing") == "1d6+2"
    assert dice.damage_expression("2d6 + 1d8 fire") == "2d6+1d8"
    assert dice.damage_expression("no dice") is None
    assert dice.attack_bonus("+6") == 6 and dice.attack_bonus("-1") == -1 and dice.attack_bonus("DC 13") is None


# ---- roll API -------------------------------------------------------------------

@pytest.fixture
def table(api):
    camp = api.campaign("Table")
    hero = api.character(camp["id"], name="Wren", max_hp=30, level=5)
    hero = api.set_char(hero, abilities={"str": 8, "dex": 18, "con": 12, "int": 14, "wis": 12, "cha": 10},
                        skill_profs={"stealth": 2}, save_profs=["dex"],
                        attacks=[{"name": "Rapier", "bonus": "+7", "damage": "1d8+4 piercing", "notes": ""},
                                 {"name": "Net", "bonus": "DC 13", "damage": "", "notes": ""}])
    return {"camp": camp, "hero": hero}


def test_custom_roll_is_saved(api, table):
    r = api.post("/api/rolls", {"expression": "3d6+2", "campaign_id": table["camp"]["id"], "op_id": "a1"}, 201)["roll"]
    vals = [x["value"] for x in r["result"]["terms"][0]["rolls"]]
    assert r["total"] == sum(vals) + 2 and r["expression"] == "3d6+2"
    hist = api.get(f"/api/rolls?campaign_id={table['camp']['id']}")["rolls"]
    assert hist[0]["id"] == r["id"] and hist[0]["result"] == r["result"]


def test_retry_returns_same_roll(api, table):
    body = {"expression": "1d20", "campaign_id": table["camp"]["id"], "op_id": "same-op"}
    first = api.post("/api/rolls", body, 201)["roll"]
    again = api.post("/api/rolls", body, 200)
    assert again["repeat"] and again["roll"]["id"] == first["id"] and again["roll"]["total"] == first["total"]
    assert len(api.get(f"/api/rolls?campaign_id={table['camp']['id']}")["rolls"]) == 1


def test_invalid_roll_reports_error(api, table):
    r = api.post("/api/rolls", {"expression": "1d7", "op_id": "bad"}, 400)
    assert "d7" in r["error"]


def test_character_checks_use_real_modifiers(api, table):
    hid = table["hero"]["id"]
    def check(t, key=None, expect=201, **extra):
        return api.post("/api/rolls", {"check": {"type": t, "key": key, "character_id": hid}, **extra}, expect)
    assert check("skill", "stealth")["roll"]["expression"] == "1d20+10"      # dex +4, expertise 2x3
    assert check("skill", "arcana")["roll"]["expression"] == "1d20+2"        # int +2, no prof
    assert check("save", "dex")["roll"]["expression"] == "1d20+7"
    assert check("save", "str")["roll"]["expression"] == "1d20-1"
    assert check("ability", "int")["roll"]["label"] == "Intelligence check"
    assert check("initiative")["roll"]["expression"] == "1d20+4"
    assert check("attack", 0)["roll"]["expression"] == "1d20+7"
    dmg = check("damage", 0)["roll"]
    assert dmg["expression"] == "1d8+4" and dmg["label"] == "Rapier damage (piercing)" and dmg["kind"] == "damage"
    assert check("damage", 0, crit=True)["roll"]["expression"] == "2d8+4"
    assert "attack bonus" in check("attack", 1, expect=400)["error"]
    assert "spellcasting" in check("spell_attack", expect=400)["error"].lower()
    death = check("death")["roll"]
    assert death["expression"] == "1d20" and death["outcome"] in (
        "Success", "Failure", "Natural 20 — regain 1 HP", "Natural 1 — counts as two failures")
    adv = check("skill", "stealth", mode="advantage")["roll"]
    vals = [x["value"] for x in adv["result"]["terms"][0]["rolls"]]
    assert adv["total"] == max(vals) + 10


def test_rolls_never_change_game_state(api, table):
    camp, hero = table["camp"], table["hero"]
    eid = api.encounter(camp["id"])["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]], "quick": {"name": "Orc", "max_hp": 15, "count": 2}})
    before_enc = api.get(f"/api/encounters/{eid}")
    before_char = api.get(f"/api/characters/{hero['id']}")["character"]
    orc = next(c for c in before_enc["combatants"] if c["name"] == "Orc 1")
    api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "character_id": hero["id"]}, "encounter_id": eid}, 201)
    api.post("/api/rolls", {"check": {"type": "save", "key": "con", "combatant_id": orc["id"]}}, 201)
    api.post("/api/rolls", {"check": {"type": "initiative", "combatant_id": orc["id"]}}, 201)  # no apply flag
    after_enc = api.get(f"/api/encounters/{eid}")
    assert [(c["id"], c["hp"], c["init_roll"], c["conditions"]) for c in after_enc["combatants"]] == \
           [(c["id"], c["hp"], c["init_roll"], c["conditions"]) for c in before_enc["combatants"]]
    assert after_enc["encounter"]["rev"] == before_enc["encounter"]["rev"]
    assert api.get(f"/api/characters/{hero['id']}")["character"] == before_char


def test_explicit_initiative_roll_sets_order(api, table):
    camp = table["camp"]
    eid = api.encounter(camp["id"])["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"quick": {"name": "Wolf", "max_hp": 11, "init_mod": 2}})
    wolf = s["combatants"][0]
    r = api.post("/api/rolls", {"check": {"type": "initiative", "combatant_id": wolf["id"]}, "apply_initiative": True}, 201)["roll"]
    s = api.get(f"/api/encounters/{eid}")
    assert s["combatants"][0]["init_roll"] == r["total"]
    assert any("rolled initiative" in l["message"] for l in s["log"])


def test_enemy_save_uses_stat_block(api, table):
    camp = table["camp"]
    cr = api.post("/api/creatures", {"name": "Ogre", "max_hp": 59, "abilities": {"str": 19, "dex": 8, "con": 16, "int": 5, "wis": 7, "cha": 7}}, 201)["creature"]
    eid = api.encounter(camp["id"])["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"]})
    r = api.post("/api/rolls", {"check": {"type": "save", "key": "dex", "combatant_id": s["combatants"][0]["id"]}}, 201)["roll"]
    assert r["expression"] == "1d20-1" and r["subject"] == "Ogre" and r["label"] == "Dexterity save"


def test_roll_history_survives_restart(data_dir):
    a = Api(create_app({"DATA_DIR": data_dir}).test_client())
    camp = a.campaign()
    r = a.post("/api/rolls", {"expression": "2d10+1", "campaign_id": camp["id"]}, 201)["roll"]
    b = Api(create_app({"DATA_DIR": data_dir}).test_client())
    again = b.get(f"/api/rolls/{r['id']}")["roll"]
    assert again["total"] == r["total"] and again["result"] == r["result"]


# ---- permissions & players ---------------------------------------------------------------

def test_strangers_are_locked_out(app, api):
    camp = api.campaign()
    stranger = remote_client(app, "192.168.1.77")
    assert stranger.get("/api/campaigns").status_code == 401
    assert stranger.get(f"/api/campaigns/{camp['id']}/journal").status_code == 401
    r = stranger.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/join")
    assert stranger.get("/join").status_code == 200


def test_proxied_requests_are_not_trusted_as_dm(app):
    c = app.test_client()
    assert c.get("/api/campaigns", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 401
    assert c.get("/api/campaigns", headers={"Host": "evil.example.com"}).status_code == 401
    assert c.get("/api/campaigns").status_code == 200


def test_cross_site_writes_blocked(app, api):
    c = app.test_client()
    r = c.post("/api/campaigns", json={"name": "X"}, headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    r = c.post("/api/campaigns", json={"name": "Y"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/campaigns", json={"name": "Z"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 201


@pytest.fixture
def joined(app, api):
    camp = api.campaign("Shared")
    a = api.character(camp["id"], name="Aria", max_hp=20)
    b = api.character(camp["id"], name="Bram", max_hp=25)
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    pa, pb = remote(app, "192.168.1.21"), remote(app, "192.168.1.22")
    assert pa.get(f"/api/join/lookup?code={code.lower()}")["campaign"] == "Shared"
    pa.post("/api/join", {"code": code, "name": "Sam", "character_id": a["id"]})
    pb.post("/api/join", {"code": code, "name": "Jo", "character_id": b["id"]})
    return {"camp": camp, "a": a, "b": b, "code": code, "pa": pa, "pb": pb}


def test_join_requires_code_and_unclaimed_character(app, joined):
    other = remote(app, "192.168.1.30")
    other.post("/api/join", {"code": "ZZZZZZ", "name": "X"}, 404)
    r = other.post("/api/join", {"code": joined["code"], "name": "X", "character_id": joined["a"]["id"]}, 400)
    assert "already joined" in r["error"]


def test_players_only_reach_player_endpoints(joined):
    pa = joined["pa"]
    st = pa.get("/api/play/state")
    assert st["character"]["name"] == "Aria" and st["campaign"] == "Shared"
    for url in ("/api/campaigns", f"/api/characters/{joined['a']['id']}", f"/api/campaigns/{joined['camp']['id']}/journal",
                f"/api/campaigns/{joined['camp']['id']}/maps", "/api/backup/export", f"/api/campaigns/{joined['camp']['id']}/players"):
        assert pa.c.get(url).status_code == 403, url
    assert pa.c.patch(f"/api/characters/{joined['a']['id']}", json={"changes": {"current_hp": {"to": 99}}}).status_code == 403
    assert pa.c.get("/").status_code == 302


def test_players_roll_only_for_their_own_character(joined):
    pa = joined["pa"]
    pa.post("/api/rolls", {"check": {"type": "ability", "key": "str", "character_id": joined["a"]["id"]}}, 201)
    pa.post("/api/rolls", {"check": {"type": "ability", "key": "str", "character_id": joined["b"]["id"]}}, 403)
    pa.post("/api/rolls", {"expression": "1d20", "apply_initiative": True}, 201)  # ignored: not an initiative check


def test_roll_visibility_enforced_on_server(api, joined):
    pa, pb = joined["pa"], joined["pb"]
    pub = pa.post("/api/rolls", {"expression": "1d20", "visibility": "public"}, 201)["roll"]
    to_dm = pa.post("/api/rolls", {"expression": "1d20", "visibility": "dm"}, 201)["roll"]
    mine = pa.post("/api/rolls", {"expression": "1d20", "visibility": "private"}, 201)["roll"]
    dm_secret = api.post("/api/rolls", {"expression": "1d20", "visibility": "dm", "campaign_id": joined["camp"]["id"]}, 201)["roll"]
    ids = lambda client, extra="": {r["id"] for r in client.get(f"/api/rolls?limit=50{extra}")["rolls"]}
    assert ids(pa) == {pub["id"], to_dm["id"], mine["id"]}
    assert ids(pb) == {pub["id"]}
    assert ids(api, f"&campaign_id={joined['camp']['id']}") == {pub["id"], to_dm["id"], dm_secret["id"]}
    pb.get(f"/api/rolls/{dm_secret['id']}", expect=404)
    pb.get(f"/api/rolls/{mine['id']}", expect=404)


def test_kicked_player_loses_access(api, joined):
    players = api.get(f"/api/campaigns/{joined['camp']['id']}/players")["players"]
    sam = next(p for p in players if p["name"] == "Sam")
    api.delete(f"/api/players/{sam['id']}")
    assert joined["pa"].c.get("/api/play/state").status_code == 401


def test_dm_link_grants_dm_on_another_device(app, api):
    api.campaign()
    key = api.post("/api/dm-key")["key"]
    tablet = remote_client(app, "192.168.1.40")
    assert tablet.get("/api/campaigns").status_code == 401
    assert tablet.get(f"/dm-login?key={key}").status_code == 302
    assert tablet.get("/api/campaigns").status_code == 200
    api.post("/api/dm-key")  # a new key replaces the old one
    assert tablet.get("/api/campaigns").status_code == 401


# ---- battle map ----------------------------------------------------------------------------

@pytest.fixture
def battlemap(api, joined):
    camp = joined["camp"]
    eid = api.encounter(camp["id"], "Bridge")["encounter"]["id"]
    s = api.post(f"/api/encounters/{eid}/combatants", {"characters": [joined["a"]["id"]],
                                                        "quick": {"name": "Bandit", "max_hp": 11, "count": 2}})
    m = api.post(f"/api/campaigns/{camp['id']}/maps", {"name": "Bridge", "cols": 10, "rows": 8, "encounter_id": eid}, 201)
    m = api.post(f"/api/maps/{m['map']['id']}/tokens/from-encounter")
    return {"eid": eid, "mid": m["map"]["id"], "state": m, "combatants": s["combatants"], **joined}


def tok(state, name):
    return next(t for t in state["tokens"] if t["display"] == name)


def test_tokens_snap_and_stay_on_map(api, battlemap):
    t = tok(battlemap["state"], "Bandit 1")
    s = api.post(f"/api/tokens/{t['id']}/move", {"x": 4.4, "y": 2.6})
    assert (tok(s, "Bandit 1")["x"], tok(s, "Bandit 1")["y"]) == (4, 3)
    api.post(f"/api/tokens/{t['id']}/move", {"x": 1e9, "y": 0}, expect=400)       # nonsense is rejected
    api.post(f"/api/tokens/{t['id']}/move", {"x": "left", "y": 0}, expect=400)
    s = api.post(f"/api/tokens/{t['id']}/move", {"x": 99, "y": -5})               # off the map is clamped onto it
    assert (tok(s, "Bandit 1")["x"], tok(s, "Bandit 1")["y"]) == (9, 0)


def test_no_duplicate_character_tokens(api, battlemap):
    mid, aria = battlemap["mid"], battlemap["a"]
    r = api.post(f"/api/maps/{mid}/tokens", {"character_id": aria["id"], "x": 3, "y": 3}, expect=400)
    assert "already has a token" in r["error"]
    assert len([t for t in api.get(f"/api/maps/{mid}")["tokens"] if t["display"] == "Aria"]) == 1


def test_token_moves_never_touch_combat(api, battlemap):
    before = api.get(f"/api/encounters/{battlemap['eid']}")
    for t in battlemap["state"]["tokens"]:
        api.post(f"/api/tokens/{t['id']}/move", {"x": 5, "y": 5})
    after = api.get(f"/api/encounters/{battlemap['eid']}")
    key = lambda s: [(c["id"], c["hp"], c["init_roll"], c["sort_order"], c["status"]) for c in s["combatants"]]
    assert key(before) == key(after)
    # and HP shown on the token comes from combat
    b1 = next(c for c in before["combatants"] if c["name"] == "Bandit 1")
    api.post(f"/api/combatants/{b1['id']}/hp", {"op": "damage", "amount": 4})
    assert tok(api.get(f"/api/maps/{battlemap['mid']}"), "Bandit 1")["hp"] == 7


def test_player_view_hides_dm_information(api, battlemap):
    mid, camp = battlemap["mid"], battlemap["camp"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    api.patch(f"/api/maps/{mid}", {"changes": {"notes": {"from": "", "to": "The bridge is trapped"}, "fog_enabled": {"from": False, "to": True}}})
    st = api.get(f"/api/maps/{mid}")
    aria, b1, b2 = tok(st, "Aria"), tok(st, "Bandit 1"), tok(st, "Bandit 2")
    api.post(f"/api/tokens/{aria['id']}/move", {"x": 1, "y": 1})
    api.post(f"/api/tokens/{b1['id']}/move", {"x": 2, "y": 1})
    api.post(f"/api/tokens/{b2['id']}/move", {"x": 8, "y": 6})
    api.post(f"/api/maps/{mid}/fog", {"cells": [[x, y] for x in range(4) for y in range(3)], "reveal": True})
    api.post(f"/api/maps/{mid}/terrain", {"cells": [[1, 0], [9, 7]], "value": "wall"})
    trap = api.post(f"/api/maps/{mid}/tokens", {"kind": "trap", "label": "Pit trap", "x": 3, "y": 1, "hidden": True, "notes": "DC 15"}, 201)

    view = battlemap["pa"].get("/api/play/state")["map"]
    names = {t["display"] for t in view["tokens"]}
    assert names == {"Aria", "Bandit 1"}, "fogged Bandit 2 and hidden trap must not be sent"
    raw = json.dumps(view)
    assert "trapped" not in raw and "DC 15" not in raw and "Pit trap" not in raw
    assert view["map"]["terrain"] == {"1,0": "wall"}, "terrain under fog is not sent"
    b1_view = next(t for t in view["tokens"] if t["display"] == "Bandit 1")
    assert "hp" not in b1_view and "notes" not in b1_view
    aria_view = next(t for t in view["tokens"] if t["display"] == "Aria")
    assert aria_view["hp"] == 20 and aria_view["movable"] and not b1_view["movable"]
    # hiding a combatant in the encounter hides its token and its turn-order entry
    b1c = next(c for c in battlemap["combatants"] if c["name"] == "Bandit 1")
    api.patch(f"/api/combatants/{b1c['id']}", {"changes": {"hidden": {"from": False, "to": True}}})
    api.post(f"/api/encounters/{battlemap['eid']}/start")
    st = battlemap["pa"].get("/api/play/state")
    assert {t["display"] for t in st["map"]["tokens"]} == {"Aria"}
    assert "Bandit 1" not in {o["name"] for o in st["encounter"]["order"]}


def test_player_token_moves_are_checked(api, battlemap):
    mid, camp, pa, pb = battlemap["mid"], battlemap["camp"], battlemap["pa"], battlemap["pb"]
    st = api.get(f"/api/maps/{mid}")
    aria, bandit = tok(st, "Aria"), tok(st, "Bandit 1")
    pa.post(f"/api/play/tokens/{aria['id']}/move", {"x": 3, "y": 3}, 403)  # map not shown to players yet
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    r = pa.post(f"/api/play/tokens/{aria['id']}/move", {"x": 3.2, "y": 2.9})
    assert (r["x"], r["y"]) == (3, 3)
    pa.post(f"/api/play/tokens/{bandit['id']}/move", {"x": 0, "y": 0}, 403)
    pb.post(f"/api/play/tokens/{aria['id']}/move", {"x": 0, "y": 0}, 403)
    api.patch(f"/api/maps/{mid}", {"changes": {"players_can_move": {"from": True, "to": False}}})
    pa.post(f"/api/play/tokens/{aria['id']}/move", {"x": 4, "y": 4}, 403)


def test_dice_do_not_modify_map(api, battlemap):
    before = api.get(f"/api/maps/{battlemap['mid']}")
    api.post("/api/rolls", {"expression": "8d6", "campaign_id": battlemap["camp"]["id"]}, 201)
    battlemap["pa"].post("/api/rolls", {"expression": "1d20"}, 201)
    assert api.get(f"/api/maps/{battlemap['mid']}") == before


def _png(color=(200, 30, 30), size=(100, 80)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_fog_is_burned_into_player_image(app, api, battlemap):
    from PIL import Image
    mid, camp = battlemap["mid"], battlemap["camp"]
    c = app.test_client()
    r = c.post(f"/api/maps/{mid}/image", data={"file": (_png(), "m.png")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    m = r.get_json()["map"]
    api.patch(f"/api/maps/{mid}", {"changes": {"cell_px": {"from": m["cell_px"], "to": 20}, "cols": {"from": m["cols"], "to": 5},
                                               "rows": {"from": m["rows"], "to": 4}, "fog_enabled": {"from": False, "to": True}}})
    api.post(f"/api/maps/{mid}/fog", {"cells": [[0, 0]], "reveal": True})
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    pa = battlemap["pa"]
    view = pa.get("/api/play/state")["map"]["map"]
    assert view["image_url"].startswith(f"/api/play/map-image/{mid}")
    img = pa.c.get(view["image_url"])
    assert img.status_code == 200
    pic = Image.open(io.BytesIO(img.data)).convert("RGB")
    assert pic.getpixel((10, 10))[0] > 150, "revealed square shows the map"
    assert max(pic.getpixel((70, 50))) < 30, "fogged square is black"
    assert pa.c.get("/api/uploads/" + api.get(f"/api/maps/{mid}")["map"]["image"]).status_code == 404, "raw image is not served to players"


def test_backup_includes_maps_tokens_and_rolls(app, api, battlemap, tmp_path):
    camp = battlemap["camp"]
    api.post("/api/rolls", {"expression": "1d20+1", "campaign_id": camp["id"]}, 201)
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": battlemap["mid"]})
    raw = app.test_client().get(f"/api/backup/export?campaign_id={camp['id']}").data
    other = create_app({"DATA_DIR": str(tmp_path / "iso"), "TESTING": True})
    b, c = Api(other.test_client()), other.test_client()
    rep = c.post("/api/backup/inspect", data={"file": (io.BytesIO(raw), "b.json")}, content_type="multipart/form-data").get_json()
    assert rep["campaigns"][0]["counts"]["maps"] == 1 and rep["campaigns"][0]["counts"]["rolls"] >= 1
    new_id = b.post("/api/backup/import", {"token": rep["token"], "decisions": {rep["campaigns"][0]["uid"]: "add"}})["imported"][0]["id"]
    maps = b.get(f"/api/campaigns/{new_id}/maps")
    assert maps["live_map_id"] == maps["maps"][0]["id"]
    st = b.get(f"/api/maps/{maps['maps'][0]['id']}")
    assert {t["display"] for t in st["tokens"]} == {"Aria", "Bandit 1", "Bandit 2"}
    assert st["encounter"]["name"] == "Bridge"
    assert b.get(f"/api/rolls?campaign_id={new_id}")["rolls"][0]["expression"] == "1d20+1"
    assert b.get(f"/api/campaigns/{new_id}/players")["players"] == [], "player sessions are not exported"


# ---- migration from the first schema -----------------------------------------------------

def test_v1_database_is_backed_up_and_upgraded(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = str(data / "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    for stmt in appdb._split_sql(appdb.MIGRATIONS[1]):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO campaigns (uid, name, created_at, updated_at) VALUES ('u1', 'Old campaign', 'x', 'x')")
    conn.commit()
    conn.close()
    app = create_app({"DATA_DIR": str(data), "AUTO_SNAPSHOT": False})
    snaps = [f for f in os.listdir(data / "backups") if f.startswith(f"pre-migration-v1-to-v{appdb.SCHEMA_VERSION}")]
    assert len(snaps) == 1
    s = sqlite3.connect(str(data / "backups" / snaps[0]))
    assert s.execute("PRAGMA user_version").fetchone()[0] == 1
    assert s.execute("SELECT name FROM campaigns").fetchone()[0] == "Old campaign"
    s.close()
    a = Api(app.test_client())
    assert a.get("/api/campaigns")["campaigns"][0]["name"] == "Old campaign"
    assert a.post("/api/rolls", {"expression": "1d4"}, 201)["roll"]["campaign_id"] == 1
    create_app({"DATA_DIR": str(data), "AUTO_SNAPSHOT": False})
    assert len([f for f in os.listdir(data / "backups") if f.startswith("pre-migration")]) == 1, "no snapshot when nothing to migrate"


def test_new_pages_render(api, battlemap, joined):
    c = api.c
    for url in ("/map", f"/map/{battlemap['mid']}", "/table"):
        assert c.get(url).status_code == 200, url
    assert joined["pa"].c.get("/play").status_code == 200


def test_share_addresses_put_home_network_first(monkeypatch):
    """DM and join links must use an address the tablet can reach: the home
    network first, Tailscale labelled, virtual adapters (WSL/Hyper-V) left out."""
    from app import play
    monkeypatch.setattr(play, "_primary_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(play.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("100.112.51.35", 0)), (2, 1, 6, "", ("172.17.144.1", 0)), (2, 1, 6, "", ("192.168.1.10", 0))])
    assert [a["ip"] for a in play.lan_addresses()] == ["192.168.1.10", "100.112.51.35"]
    assert "Tailscale" in play.lan_addresses()[1]["label"]
