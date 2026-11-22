"""2026-11-15: Yamato's seven techniques (app/yamato.py): Phantom Blade, Storm Wave, Upper Slash, Guard
Break, Clone Calling, Chain Attack, Mirage. Cooldowns, clones used up vs moved, no clone counted twice."""
from app import dice
from app import yamato as Y
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

SLASH = {"name": "Slash", "bonus": "+2", "damage": "2d8+4", "notes": "Basic Slash"}
KILLERS = {"name": "Phantasmal Killers", "effect": "buff", "level": 1, "summon": "Yamato clone", "summon_count": 2,
           "summon_ac": 10, "summon_hp": 1, "summon_max": 3,
           "on_death": {"dc": 10, "name": "Phantasmal Killers", "reach": 5, "save": "dex"}}


def fight(api, bm, monkeypatch, clones=2):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    api.post("/api/creatures", {"name": "Yamato clone", "max_hp": 1, "ac": 10, "attacks": "Slash 2d8"}, 201)
    aria = api.get(f"/api/characters/{bm['a']['id']}")["character"]
    api.set_char(aria, attacks=[SLASH], spells=[KILLERS] + Y.rows(), max_hp=40, current_hp=40,
                 abilities={"str": 15, "dex": 19, "con": 12, "int": 12, "wis": 11, "cha": 8}, level=4)
    api.patch(f"/api/maps/{bm['mid']}", {"changes": {"cols": {"to": 20}, "rows": {"to": 12}}})
    api.post(f"/api/campaigns/{bm['camp']['id']}/live-map", {"map_id": bm["mid"]})
    eid = bm["eid"]
    by = {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}
    for n, r in (("Aria", 15), ("Bandit 1", 10), ("Bandit 2", 5)):
        api.patch(f"/api/combatants/{by[n]['id']}", {"changes": {"init_roll": {"from": None, "to": r}}})
    api.post(f"/api/encounters/{eid}/start")
    for n in ("Bandit 1", "Bandit 2"):  # tough enough to take a max-damage hit and still be there
        api.post(f"/api/combatants/{by[n]['id']}/hp", {"op": "temp", "amount": 500})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    m = api.get(f"/api/maps/{bm['mid']}")
    for name, xy in (("Aria", (5, 5)), ("Bandit 1", (6, 5)), ("Bandit 2", (12, 9))):
        api.post(f"/api/tokens/{tok(m, name)['id']}/move", {"x": xy[0], "y": xy[1], "free": True})
    if clones:
        api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
        fresh_turn(api, eid, by)
    return eid, by, loaded


def fresh_turn(api, eid, by, who="Aria"):
    """Their next turn (a new round), with both actions."""
    st = api.post(f"/api/encounters/{eid}/next")
    while st["encounter"]["current_id"] != by[who]["id"]:
        st = api.post(f"/api/encounters/{eid}/next")
    return st


def tech(api, eid, by, key, expect=200, **body):
    st = api.get(f"/api/encounters/{eid}")
    me = next(c for c in st["combatants"] if c["id"] == by["Aria"]["id"])
    mv = next(m for m in me["techniques"]["moves"] if m["key"] == key)
    return api.post(f"/api/encounters/{eid}/technique", dict({"caster_id": by["Aria"]["id"], "index": mv["index"]}, **body), expect)


def clones_of(st, by):
    return [c for c in st["combatants"] if c.get("follows") == by["Aria"]["id"]]


def conds(st, cid):
    return {x["name"]: x for x in next(c for c in st["combatants"] if c["id"] == cid)["conditions"]}


def test_seven_techniques_show_with_their_cooldowns_and_never_as_normal_spells(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch)
    me = next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["id"] == by["Aria"]["id"])
    moves = {m["key"]: m for m in me["techniques"]["moves"]}
    assert list(moves) == Y.ORDER
    assert {k: m["cooldown"] for k, m in moves.items()} == {"phantom_blade": 2, "storm_wave": 5, "upper_slash": 1, "guard_break": 3,
                                                           "clone_calling": 0, "chain_attack": 4, "mirage": 5}
    assert moves["storm_wave"]["clones"] == "uses up all" and moves["guard_break"]["clones"] == "uses up one"
    assert moves["clone_calling"]["clones"] == "moves" and not moves["clone_calling"]["action"]
    assert not any(s.get("technique") for s in me["spells"]), "they aren't offered as ordinary spells"
    assert len(me["techniques"]["clones"]) == 2
    # and the normal Cast refuses them
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 1, "targets": [by["Bandit 1"]["id"]]}, 400)
    assert "Techniques panel" in err["error"]


def test_phantom_blade_hits_within_10_ft_knocks_back_and_recharges(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch, clones=0)
    tech(api, eid, by, "phantom_blade", 403, targets=[by["Bandit 2"]["id"]])  # far away
    st = tech(api, eid, by, "phantom_blade", targets=[by["Bandit 1"]["id"]])
    assert "Phantom Blade" in st["technique"]["summary"]
    m = api.get(f"/api/maps/{battlemap['mid']}")
    assert tok(m, "Bandit 1")["x"] == 8, "a Medium bandit is knocked back 10 ft"
    assert "Phantom Blade recharging" in conds(st, by["Aria"]["id"])
    fresh_turn(api, eid, by)
    tech(api, eid, by, "phantom_blade", 400, targets=[by["Bandit 1"]["id"]])  # still recharging (2 turns)
    fresh_turn(api, eid, by)
    fresh_turn(api, eid, by)
    b1tok = tok(api.get(f"/api/maps/{battlemap['mid']}"), "Bandit 1")
    api.post(f"/api/tokens/{b1tok['id']}/move", {"x": 6, "y": 5, "free": True})
    tech(api, eid, by, "phantom_blade", targets=[by["Bandit 1"]["id"]])  # ready again


def test_phantom_blade_dm_can_slow_instead(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch, clones=0)
    b1 = by["Bandit 1"]["id"]
    st = tech(api, eid, by, "phantom_blade", targets=[b1], rider={str(b1): "slow"})
    assert conds(st, b1)["Slowed"]["slowed"]


def test_upper_slash_launches_until_its_own_next_turn(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch, clones=0)
    b1 = by["Bandit 1"]["id"]
    st = tech(api, eid, by, "upper_slash", targets=[b1])
    launched = conds(st, b1)["Launched"]
    assert launched["adv"] == "attacked_adv" and launched["tick_on"] == b1
    api.post(f"/api/encounters/{eid}/next")   # Bandit 1's turn begins: it lands
    st = api.get(f"/api/encounters/{eid}")
    assert "Launched" not in conds(st, b1)


def test_guard_break_uses_up_the_clone_and_staggers(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch)
    st = api.get(f"/api/encounters/{eid}")
    k = clones_of(st, by)[0]
    b1 = by["Bandit 1"]["id"]
    tech(api, eid, by, "guard_break", 400, targets=[b1])  # pick a clone
    st = tech(api, eid, by, "guard_break", targets=[b1], clones=[k["id"]])
    assert k["id"] not in {c["id"] for c in st["combatants"]}, "the clone is used up"
    sg = conds(st, b1)["Staggered"]
    assert sg["ac"] == -2 and sg["tick_on"] == b1
    assert not any("Phantasmal Killers" in line["message"] and "save" in line["message"] for line in st["log"][-3:]), "no death burst"


def test_storm_wave_sheathe_then_release_uses_every_clone(api, battlemap, monkeypatch):
    eid, by, loaded = fight(api, battlemap, monkeypatch)
    b1 = by["Bandit 1"]["id"]
    st = tech(api, eid, by, "storm_wave")
    assert "Storm Wave: blade sheathed" in conds(st, by["Aria"]["id"])
    tech(api, eid, by, "storm_wave", 400, targets=[b1])  # not the same turn
    st = fresh_turn(api, eid, by)  # his next turn
    loaded.rest = "min"  # the bandit fails its save
    st = tech(api, eid, by, "storm_wave", targets=[b1])
    assert not clones_of(st, by), "both clones turned into the wave"
    assert "3× the weapon dice" in st["technique"]["summary"]
    c = conds(st, by["Aria"]["id"])
    assert "Storm Wave guard" in c and "Storm Wave: blade sheathed" not in c and "Storm Wave recharging" in c
    # the guard: 3 less damage per hit
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 10})
    assert next(x for x in st["combatants"] if x["id"] == by["Aria"]["id"])["hp"] == 33
    fresh_turn(api, eid, by)
    assert "Storm Wave guard" not in conds(api.get(f"/api/encounters/{eid}"), by["Aria"]["id"]), "only until his next turn"


def test_clone_calling_brings_them_back_free_once_a_round(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch)
    m = api.get(f"/api/maps/{battlemap['mid']}")
    for i, t in enumerate(x for x in m["tokens"] if x["display"].startswith("Yamato clone")):
        api.post(f"/api/tokens/{t['id']}/move", {"x": 15 + i, "y": 1, "free": True})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 2"]["id"]})  # not even his turn
    st = tech(api, eid, by, "clone_calling")
    m = api.get(f"/api/maps/{battlemap['mid']}")
    for t in (x for x in m["tokens"] if x["display"].startswith("Yamato clone")):
        assert abs(t["x"] - 5) <= 1 and abs(t["y"] - 5) <= 1, "beside him"
    tech(api, eid, by, "clone_calling", 400)  # once a round
    me = next(c for c in st["combatants"] if c["id"] == by["Aria"]["id"])
    assert me["actions"] is None or me["actions"]["left"] == me["actions"]["limit"]


def test_chain_attack_needs_them_surrounded_and_each_clone_joins_one_enemy(api, battlemap, monkeypatch):
    eid, by, loaded = fight(api, battlemap, monkeypatch)
    b1, b2 = by["Bandit 1"]["id"], by["Bandit 2"]["id"]
    m = api.get(f"/api/maps/{battlemap['mid']}")
    ks = [x for x in m["tokens"] if x["display"].startswith("Yamato clone")]
    api.post(f"/api/tokens/{ks[0]['id']}/move", {"x": 7, "y": 5, "free": True})   # next to Bandit 1 (6,5)
    api.post(f"/api/tokens/{ks[1]['id']}/move", {"x": 18, "y": 1, "free": True})  # far away
    err = tech(api, eid, by, "chain_attack", 400, targets=[b1, b2])
    assert "Surround them first" in err["error"] and "Bandit 2" in err["error"]
    loaded.rest = "min"
    st = tech(api, eid, by, "chain_attack", targets=[b1])
    s = st["technique"]["summary"]
    assert "Bandit 1 ← Aria, Yamato clone" in s and "(DC 16)" in s  # 8 + 2 + 4 = 14, +2 for the second attacker
    assert len(clones_of(st, by)) == 2, "clones join in but aren't used up"


def test_mirage_on_spot_check_and_it_ends_with_the_last_clone(api, battlemap, monkeypatch):
    eid, by, loaded = fight(api, battlemap, monkeypatch)
    st = tech(api, eid, by, "mirage")
    assert conds(st, by["Aria"]["id"])["Mirage"]["note"].endswith("DC 14 to pick out the real one")
    loaded.rest = "min"
    r = api.post(f"/api/encounters/{eid}/mirage-spot", {"caster_id": by["Aria"]["id"], "enemy_id": by["Bandit 1"]["id"]})
    assert "fooled" in r["spot"]
    for k in clones_of(r, by):
        api.post(f"/api/encounters/{eid}/damage", {"targets": [k["id"]], "amount": 5})
    st = api.get(f"/api/encounters/{eid}")
    assert "Mirage" not in conds(st, by["Aria"]["id"]), "no clones left: the Mirage is over"


def test_phone_uses_techniques_on_his_turn_only(api, battlemap, monkeypatch):
    eid, by, _ = fight(api, battlemap, monkeypatch, clones=0)
    pa = battlemap["pa"]
    me = pa.get("/api/play/state")["character"]
    t = {m["key"]: m for m in me["techniques"]["moves"]}
    assert t["upper_slash"]["ready"] and me["techniques"]["foes"]
    r = pa.post("/api/play/me/technique", {"index": t["upper_slash"]["index"], "targets": [by["Bandit 1"]["id"]], "op_id": "u1"})
    assert r["technique"]["name"] == "Upper Slash"
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 2"]["id"]})
    err = pa.post("/api/play/me/technique", {"index": t["phantom_blade"]["index"], "targets": [by["Bandit 1"]["id"]], "op_id": "u2"}, 403)
    assert "your turn" in err["error"]
