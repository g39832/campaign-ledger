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
    # attack rolls are moves: two of them use both extra moves
    for left in (1, 0):
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
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    assert surge_of(st)["extra_moves"] == 1


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
    pa.post("/api/rolls", {"check": {"type": "attack", "key": 0, "character_id": battlemap["a"]["id"]}}, 201)
    me = pa.get("/api/play/state")["character"]
    assert any("1 extra move left" in c for c in me["conditions"])


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
