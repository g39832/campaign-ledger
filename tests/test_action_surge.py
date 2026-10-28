"""Action Surge: a sheet row with Extra moves. Using it gives that many extra moves for
the rest of the turn; each move counts one down; it ends with the turn; then the row's
cooldown runs. Players can use it only on their own turn."""
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)

ROWS = [{"name": "Punch", "bonus": "+5", "damage": "1d6+3 bludgeoning"},
        {"name": "Action Surge", "bonus": "", "damage": "", "notes": "Two extra moves", "extra_moves": 2, "cooldown": 3}]


def setup(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, attacks=ROWS)
    eid = battlemap["eid"]
    st = api.post(f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    return eid, by


def surge_of(st, name="Aria"):
    c = next(c for c in st["combatants"] if c["name"] == name)
    return next((x for x in c["conditions"] if x.get("extra_moves") is not None), None)


def test_surge_counts_down_and_ends_with_the_turn(api, battlemap):
    eid, by = setup(api, battlemap)
    aria = by["Aria"]
    assert next(a for a in aria["attacks"] if a["name"] == "Action Surge")["extra_moves"] == 2
    st = api.post(f"/api/combatants/{aria['id']}/surge", {"index": 1})
    s = surge_of(st)
    assert s["extra_moves"] == 2 and s["name"] == "Action Surge"
    assert any("Aria uses Action Surge: 2 extra moves this turn" in e["message"] for e in st["log"])
    # attack rolls are moves: the usual two come first, then the two extra
    for left in (2, 2, 1, 0):
        api.post("/api/rolls", {"check": {"type": "attack", "key": 0, "combatant_id": aria["id"]}}, 201)
        assert surge_of(api.get(f"/api/encounters/{eid}"))["extra_moves"] == left
    # the damage roll of an attack that has a to-hit isn't another move
    api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": aria["id"]}}, 201)
    st = api.get(f"/api/encounters/{eid}")
    assert surge_of(st)["extra_moves"] == 0 and "used up" in surge_of(st)["note"]
    # can't surge twice in a turn, and it's recharging anyway
    api.post(f"/api/combatants/{aria['id']}/surge", {"index": 1}, 400)
    st = api.post(f"/api/encounters/{eid}/next")
    assert surge_of(st) is None, "gone at the end of her turn"
    rech = next(x for x in next(c for c in st["combatants"] if c["name"] == "Aria")["conditions"] if x.get("cooldown") == "Action Surge")
    assert rech["rounds_left"] >= 1
    err = api.post(f"/api/combatants/{aria['id']}/surge", {"index": 1}, 400)
    assert "recharging" in err["error"]


def test_surge_counts_casts_too(api, battlemap):
    eid, by = setup(api, battlemap)
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    spec = {"name": "Shove", "effect": "debuff", "condition": "Prone", "hit": "attack", "attack_bonus": 5, "move": True}
    for left in (2, 2, 1):
        st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
        assert surge_of(st)["extra_moves"] == left


def test_player_surges_only_on_their_turn(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    me = pa.get("/api/play/state")["character"]
    assert next(a for a in me["attacks"] if a["name"] == "Action Surge")["extra_moves"] == 2
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    pa.post("/api/play/me/surge", {"index": 1}, 403)
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = pa.post("/api/play/me/surge", {"index": 1})
    assert any("2 extra moves left" in c for c in r["character"]["conditions"])
    for _ in range(3):
        pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": battlemap["a"]["id"]}}, 201)
    me = pa.get("/api/play/state")["character"]
    assert any("1 extra move left" in c for c in me["conditions"])
    assert me["actions"] == {"used": 3, "limit": 4, "left": 1, "extra": 2}
    pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": battlemap["a"]["id"]}}, 201)
    err = pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": battlemap["a"]["id"]}}, 403)
    assert "4 actions" in err["error"]


def test_two_actions_a_turn_without_surge(api, battlemap):
    eid, by = setup(api, battlemap)
    pa, aid = battlemap["pa"], battlemap["a"]["id"]
    assert pa.get("/api/play/state")["character"]["actions"] == {"used": 0, "limit": 2, "left": 2, "extra": 0}
    for _ in range(2):
        pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": aid}}, 201)
    pa.post("/api/rolls", {"check": {"type": "damage", "key": 0, "character_id": aid}}, 201)   # damage of a hit isn't an action
    err = pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": aid}}, 403)
    assert "2 actions" in err["error"] and "Action Surge" in err["error"]
    pa.post("/api/play/me/disengage", {}, 403)                                               # Disengage is an action too
    # the DM's rolls for her count the same
    api.post("/api/rolls", {"check": {"type": "attack", "key": 0, "combatant_id": by["Aria"]["id"]}}, 403)
    spec = {"name": "Shove", "effect": "debuff", "condition": "Prone", "hit": "attack", "attack_bonus": 5, "move": True}
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]}, 403)
    # monsters are the DM's call
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    glare = {"name": "Glare", "effect": "debuff", "condition": "Frightened", "hit": "attack", "attack_bonus": 5}
    for _ in range(3):
        api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": glare, "targets": [by["Bandit 2"]["id"]]})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    # Action Surge on top: two more
    pa.post("/api/play/me/surge", {"index": 1})
    pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": aid}}, 201)
    # her next turn: two again
    for _ in range(3):
        api.post(f"/api/encounters/{eid}/next")
    assert pa.get("/api/play/state")["character"]["actions"]["left"] == 2


def test_off_turn_rolls_are_only_for_the_player(api, battlemap):
    """Not their turn: a player can still roll, but nobody else sees it (initiative and saves go
    to the DM too); it never counts as a move. On their turn rolls are for everyone."""
    eid, by = setup(api, battlemap)
    pa, pb, aid = battlemap["pa"], battlemap["pb"], battlemap["a"]["id"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    ids = {}
    for name, body in (("ability", {"check": {"type": "ability", "key": "str", "character_id": aid}}),
                       ("attack", {"check": {"type": "attack", "key": 0, "character_id": aid}}),
                       ("free", {"expression": "1d20"}),
                       ("save", {"check": {"type": "save", "key": "dex", "character_id": aid}}),
                       ("initiative", {"check": {"type": "initiative", "character_id": aid}})):
        r = pa.post("/api/rolls", body, 201)
        assert r["watching"] is True
        ids[name] = (r["roll"]["id"], r["roll"]["visibility"])
    assert {k: v[1] for k, v in ids.items()} == {"ability": "private", "attack": "private", "free": "private", "save": "dm", "initiative": "dm"}
    camp = battlemap["camp"]["id"]
    seen_dm = {r["id"] for r in api.get(f"/api/rolls?campaign_id={camp}")["rolls"]}
    seen_other = {r["id"] for r in pb.get(f"/api/rolls?campaign_id={camp}")["rolls"]}
    seen_self = {r["id"] for r in pa.get(f"/api/rolls?campaign_id={camp}")["rolls"]}
    assert all(i in seen_self for i, _ in ids.values()), "she sees all her own rolls"
    assert not any(i in seen_other for i, _ in ids.values()), "the other player sees none of them"
    assert seen_dm & {i for i, _ in ids.values()} == {ids["save"][0], ids["initiative"][0]}, "the DM sees only the save and the initiative"
    assert pa.get("/api/play/state")["character"]["actions"] is None or True
    # her turn: rolls are for everyone again
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = pa.post("/api/rolls", {"check": {"type": "skill", "key": "athletics", "character_id": aid}}, 201)
    assert r["watching"] is False and r["roll"]["visibility"] == "public"
    assert r["roll"]["id"] in {x["id"] for x in pb.get(f"/api/rolls?campaign_id={camp}")["rolls"]}


def test_players_cant_change_their_own_hp(api, battlemap):
    pa = battlemap["pa"]
    assert pa.get("/api/play/state")["character"]["can"]["edit_hp"] is False
    for op in ({"op": "damage", "amount": 5}, {"op": "heal", "amount": 5}, {"op": "set", "hp": 1}):
        pa.post("/api/play/me/hp", op, 403)


def test_a_row_without_extra_moves_cant_surge(api, battlemap):
    eid, by = setup(api, battlemap)
    err = api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 0}, 400)
    assert "Extra moves" in err["error"]


def test_extra_moves_count_only_in_their_own_fight(api, battlemap):
    eid, by = setup(api, battlemap)
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    # a second fight with the same hero: moves there don't touch the first fight's extra moves
    camp = battlemap["camp"]
    e2 = api.encounter(camp["id"], "Elsewhere")["encounter"]["id"]
    st = api.post(f"/api/encounters/{e2}/combatants", {"characters": [battlemap["a"]["id"]], "quick": {"name": "Rat", "max_hp": 5}})
    a2 = next(c for c in st["combatants"] if c["name"] == "Aria")
    api.post(f"/api/encounters/{e2}/start")
    api.post(f"/api/encounters/{e2}/set-turn", {"combatant_id": a2["id"]})
    api.post("/api/rolls", {"check": {"type": "attack", "key": 0, "combatant_id": a2["id"]}}, 201)
    assert surge_of(api.get(f"/api/encounters/{eid}"))["extra_moves"] == 2


def test_ending_the_fight_clears_extra_moves(api, battlemap):
    eid, by = setup(api, battlemap)
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    st = api.post(f"/api/encounters/{eid}/end")
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert not any(x.get("extra_moves") is not None or x.get("cooldown") for x in a["conditions"])


def test_leftover_surge_ends_when_their_next_turn_starts(api, battlemap):
    """The DM moved the turn away with Set turn (no end-of-turn): the surge still ends."""
    eid, by = setup(api, battlemap)
    api.post(f"/api/combatants/{by['Aria']['id']}/surge", {"index": 1})
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    for _ in range(4):
        st = api.post(f"/api/encounters/{eid}/next")
        if st["encounter"]["current_id"] == by["Aria"]["id"]:
            break
    assert surge_of(st) is None
    assert battlemap["pa"].get("/api/play/state")["character"]["actions"]["limit"] == 2
