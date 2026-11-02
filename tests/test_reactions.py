"""Reactions: one a round for everyone in a fight, back at the start of their own turn.
Parry spends it; so do the new ones: Deflect Attacks (cut a hit by 1d10 + Dex + level, and send
it back when it drops to 0), Absorb Elements (extra dice on the next hit) and Sentinel (hit back
an enemy next to you that attacks someone else). Also: burning a reaction by hand, Yamato's
three clones with Phantasmal Killers' burst, and a spell row with extra actions."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

DEFLECT = {"name": "Deflect attacks", "level": 1, "effect": "", "reaction": "deflect", "reduce": "1d10+dex+level", "redirect": True}
ABSORB = {"name": "Absorb Elements", "level": 1, "effect": "", "reaction": "absorb", "bonus_dice": "1d12"}
PARRY = {"name": "Parry", "effect": "damage", "dice": "1d4", "hit": "attack", "level": 0, "parry": True}


def fighters(api, eid):
    return {c["name"]: c for c in api.get(f"/api/encounters/{eid}")["combatants"]}


def place(api, mid, name, x, y):
    t = tok(api.get(f"/api/maps/{mid}"), name)
    api.post(f"/api/tokens/{t['id']}/move", {"x": x, "y": y})


def start(api, battlemap, inits=None):
    eid = battlemap["eid"]
    by = fighters(api, eid)
    for name, roll in (inits or {"Bandit 1": 18, "Aria": 12, "Bandit 2": 5}).items():
        api.patch(f"/api/combatants/{by[name]['id']}", {"changes": {"init_roll": {"from": None, "to": roll}}})
    api.post(f"/api/encounters/{eid}/start")
    return eid, fighters(api, eid)


def test_parry_uses_the_reaction_and_it_comes_back_on_their_turn(api, battlemap, monkeypatch):
    monkeypatch.setattr(dice, "_rng", Loaded().next(15, 3))
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=[PARRY], current_hp=20)
    eid, by = start(api, battlemap)
    assert by["Aria"]["reaction"]["ready"] is True
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 8, "attacker_id": by["Bandit 1"]["id"]})
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["parry"]["pending"]["amount"] == 8
    st = api.post(f"/api/combatants/{by['Aria']['id']}/parry")
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 16 and a["reaction"]["ready"] is False and a["reaction"]["used"] == "Parry"
    # hit again this round: no parry offered, and asking for one is refused
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 4, "attacker_id": by["Bandit 1"]["id"]})
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["parry"]["pending"] is None
    err = api.post(f"/api/combatants/{by['Aria']['id']}/parry", {}, 409)
    assert "already used their reaction" in err["error"]
    # her turn: it's back
    st = api.post(f"/api/encounters/{eid}/next")
    assert st["encounter"]["current_id"] == by["Aria"]["id"]
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["reaction"]["ready"] is True


def test_deflect_cuts_the_hit_and_sends_it_back_when_it_drops_to_zero(api, battlemap, monkeypatch):
    rng = Loaded()
    monkeypatch.setattr(dice, "_rng", rng)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=[DEFLECT], current_hp=20, level=5, abilities={"str": 10, "dex": 12, "con": 10, "int": 10, "wis": 10, "cha": 10})
    mid = battlemap["mid"]
    place(api, mid, "Aria", 2, 2)
    place(api, mid, "Bandit 1", 3, 2)
    place(api, mid, "Bandit 2", 9, 7)
    eid, by = start(api, battlemap)
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 9, "attacker_id": by["Bandit 1"]["id"], "move": "Scimitar"})
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    offer = next(o for o in a["reaction"]["offers"] if o["kind"] == "deflect")
    assert offer["amount"] == 9 and offer["reduce"] == "1d10+1+5"   # Dex +1, level 5
    rng.next(4)  # 4 + 1 + 5 = 10: the 9 is cut to 0
    st = api.post(f"/api/combatants/{by['Aria']['id']}/react", {"kind": "deflect"})
    r = st["reaction"]
    assert r["cut"] == 10 and r["taken"] == 0
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 20 and a["reaction"]["ready"] is False
    # a melee hit goes to an enemy within 10 ft: Bandit 1 is next to her, Bandit 2 far away
    assert r["redirect"]["range"] == 10 and [t["name"] for t in r["redirect"]["targets"]] == ["Bandit 1"]
    api.post(f"/api/combatants/{by['Aria']['id']}/react", {"kind": "redirect", "target": by["Bandit 2"]["id"]}, 400)
    st = api.post(f"/api/combatants/{by['Aria']['id']}/react", {"kind": "redirect", "target": by["Bandit 1"]["id"]})
    assert next(c for c in st["combatants"] if c["name"] == "Bandit 1")["hp"] == 2
    assert not next(c for c in st["combatants"] if c["name"] == "Aria")["reaction"]["offers"]
    # a hit that isn't cut to 0 just takes less
    api.post(f"/api/encounters/{eid}/next")                       # Aria's turn: her reaction is back
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 15, "attacker_id": by["Bandit 2"]["id"]})
    rng.next(1)  # 1 + 6 = 7
    st = api.post(f"/api/combatants/{by['Aria']['id']}/react", {"kind": "deflect"})
    assert st["reaction"]["taken"] == 8 and "redirect" not in st["reaction"]
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == 12


def test_absorb_elements_adds_dice_to_the_next_hit_only(api, battlemap, monkeypatch):
    monkeypatch.setattr(dice, "_rng", Loaded())
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=[ABSORB], current_hp=20,
                 attacks=[{"name": "Punch", "bonus": "+2", "damage": "1d6+1 bludgeoning"}])
    eid, by = start(api, battlemap)
    # a slashing hit can't be absorbed; a fire one can
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 5, "attacker_id": by["Bandit 1"]["id"], "damage_type": "slashing"})
    assert not [o for o in next(c for c in st["combatants"] if c["name"] == "Aria")["reaction"]["offers"] if o["kind"] == "absorb"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 6, "attacker_id": by["Bandit 1"]["id"], "damage_type": "fire"})
    assert [o for o in next(c for c in st["combatants"] if c["name"] == "Aria")["reaction"]["offers"] if o["kind"] == "absorb"][0]["type"] == "fire"
    st = api.post(f"/api/combatants/{by['Aria']['id']}/react", {"kind": "absorb"})
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    eff = next(x for x in a["conditions"] if x["name"] == "Absorb Elements")
    assert eff["dmg_mod"] == "+1d12" and eff["once"] and "fire" in eff["note"]
    # her turn: her punch's damage roll has the +1d12, then it's gone
    api.post(f"/api/encounters/{eid}/next")
    r = api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": by["Aria"]["id"]}, "encounter_id": eid}, 201)
    assert "1d12" in r["roll"]["expression"] and r["roll"]["total"] == 6 + 1 + 12
    a = fighters(api, eid)["Aria"]
    assert not [x for x in a["conditions"] if x["name"] == "Absorb Elements"]
    r = api.post("/api/rolls", {"check": {"type": "damage", "key": 0, "combatant_id": by["Aria"]["id"]}, "encounter_id": eid}, 201)
    assert "1d12" not in r["roll"]["expression"]


def test_sentinel_hits_back_an_enemy_next_to_her_that_attacks_someone_else(api, battlemap, monkeypatch):
    monkeypatch.setattr(dice, "_rng", Loaded())
    bram = api.get(f"/api/characters/{battlemap['b']['id']}")["character"]
    api.set_char(bram, attacks=[{"name": "Pasta", "bonus": "+2", "damage": "2d20 + 15"},
                                {"name": "Sentinel", "bonus": "", "damage": "", "reaction": "sentinel", "notes": "When a creature within 5 feet..."}])
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [bram["id"]]})
    api.post(f"/api/maps/{battlemap['mid']}/tokens/from-encounter")
    mid = battlemap["mid"]
    place(api, mid, "Aria", 2, 2)
    place(api, mid, "Bram", 4, 2)
    place(api, mid, "Bandit 1", 3, 2)   # next to both
    place(api, mid, "Bandit 2", 8, 6)   # far from Bram
    eid, by = start(api, battlemap, {"Bandit 1": 18, "Aria": 12, "Bram": 10, "Bandit 2": 5})
    # Bandit 1 attacks Aria (a miss shows on the map the same way): Bram may strike it
    api.post(f"/api/maps/{mid}/fx", {"by": by["Bandit 1"]["id"], "name": "Scimitar", "kind": "damage", "targets": [{"id": by["Aria"]["id"], "how": "miss"}]})
    b = fighters(api, eid)["Bram"]
    offer = next(o for o in b["reaction"]["offers"] if o["kind"] == "sentinel")
    assert offer["vs_name"] == "Bandit 1" and offer["attack"] == "Pasta" and offer["on"] == ["Aria"]
    # Bram's player uses it from the phone, off his turn
    r = battlemap["pb"].post("/api/play/me/react", {"kind": "sentinel"})
    assert "Pasta" in r["reaction"]["summary"] and "AC" not in r["reaction"]["summary"]
    st = api.get(f"/api/encounters/{eid}")
    assert next(c for c in st["combatants"] if c["name"] == "Bandit 1")["hp"] <= 0   # 2d20+15 at max
    assert next(c for c in st["combatants"] if c["name"] == "Bram")["reaction"]["ready"] is False
    assert battlemap["pb"].post("/api/play/me/react", {"kind": "sentinel"}, 409)
    # an attack by an enemy far from him, or one on him, offers nothing
    api.post(f"/api/encounters/{eid}/next")
    api.post(f"/api/encounters/{eid}/next")   # Bram's turn: his reaction is back
    api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 2, "attacker_id": by["Bandit 2"]["id"]})
    assert not fighters(api, eid)["Bram"]["reaction"]["offers"]


def test_burning_a_reaction_by_hand_and_the_dm_giving_it_back(api, battlemap):
    eid, by = start(api, battlemap)
    st = battlemap["pa"].post("/api/play/me/react", {"kind": "burn", "what": "Opportunity attack"})
    assert st["character"]["reaction"]["ready"] is False and st["character"]["reaction"]["used"] == "Opportunity attack"
    battlemap["pa"].post("/api/play/me/react", {"kind": "burn"}, 409)
    st = api.post(f"/api/combatants/{by['Bandit 2']['id']}/react", {"kind": "burn", "what": "Parry"})
    assert next(c for c in st["combatants"] if c["name"] == "Bandit 2")["reaction"]["ready"] is False
    st = api.post(f"/api/combatants/{by['Aria']['id']}/reaction-back")
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["reaction"]["ready"] is True
    # whoever's turn it is: their actions and movement left
    cur = next(c for c in st["combatants"] if c["id"] == st["encounter"]["current_id"])
    assert cur["actions"]["left"] == 2 and cur["move"]["left"] == cur["move"]["speed"]
    assert all(c["actions"] is None for c in st["combatants"] if c["id"] != cur["id"])


YAMATO = [{"name": "Phantasaml force", "effect": "buff", "level": 0, "summon": "yamato clone", "cooldown": 2, "summon_max": 3},
          {"name": "Echo Knight", "effect": "buff", "level": 0, "summon": "yamato clone", "per_fight": True, "summon_max": 3},
          {"name": "Phantasmal Killers", "effect": "buff", "level": 1, "summon": "yamato clone", "summon_count": 2, "summon_max": 3,
           "summon_ac": 10, "summon_hp": 1, "on_death": {"save": "dex", "dc": 10, "reach": 5}},
          {"name": "Action surge", "level": 1, "effect": "", "extra_moves": 1, "cooldown": 3}]


def test_three_clones_and_the_phantasmal_killers_burst(api, battlemap, monkeypatch):
    rng = Loaded()
    monkeypatch.setattr(dice, "_rng", rng)
    api.post("/api/creatures", {"name": "yamato clone", "max_hp": 1, "ac": 5, "attacks": "Slash 2d8"}, 201)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=YAMATO, current_hp=20)
    mid = battlemap["mid"]
    place(api, mid, "Aria", 2, 2)
    place(api, mid, "Bandit 1", 6, 2)
    place(api, mid, "Bandit 2", 9, 7)
    eid, by = start(api, battlemap, {"Aria": 18, "Bandit 1": 12, "Bandit 2": 5})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 2, "targets": [], "at": {"map_id": mid, "x": 5, "y": 2}})
    clones = [c for c in st["combatants"] if c["follows"] == by["Aria"]["id"]]
    assert len(clones) == 2 and all(c["ac"] == 10 and c["hp"] == 1 for c in clones)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    assert len([c for c in st["combatants"] if c["follows"] == by["Aria"]["id"]]) == 3
    api.post(f"/api/encounters/{eid}/next")  # her two actions are used; the DM tries again off her turn
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 1, "targets": []}, 400)
    assert "3 at a time" in err["error"]
    # the clone next to Bandit 1 is destroyed: Bandit 1 fails its Dex save (a 1) and loses an action
    killer = next(c for c in clones if tok(api.get(f"/api/maps/{mid}"), c["name"])["x"] == 5)
    rng.next(1)
    st = api.post(f"/api/combatants/{killer['id']}/hp", {"op": "damage", "amount": 1})
    b1 = next(c for c in st["combatants"] if c["name"] == "Bandit 1")
    assert any(x["name"] == "Shaken" and x["lose_actions"] == 1 for x in b1["conditions"])
    assert any("bursts" in e["message"] for e in st["log"])
    assert not any(x["name"] == "Shaken" for x in next(c for c in st["combatants"] if c["name"] == "Bandit 2")["conditions"])
    while st["encounter"]["current_id"] != by["Bandit 1"]["id"]:
        st = api.post(f"/api/encounters/{eid}/next")
    assert next(c for c in st["combatants"] if c["name"] == "Bandit 1")["actions"]["limit"] == 1


def test_a_spell_row_with_extra_actions(api, battlemap):
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=YAMATO)
    eid, by = start(api, battlemap, {"Aria": 18, "Bandit 1": 12, "Bandit 2": 5})
    me = battlemap["pa"].get("/api/play/state")["character"]
    assert me["surges"] == [{"index": 3, "name": "Action surge", "extra_moves": 1, "cooldown": 3, "recharging": 0}]
    st = battlemap["pa"].post("/api/play/me/surge", {"spell": 3})
    assert st["character"]["actions"]["limit"] == 3
    battlemap["pa"].post("/api/play/me/surge", {"spell": 3}, 400)   # recharging now


def test_players_only_see_their_own_reaction_and_no_hidden_attacker(api, battlemap):
    bram = api.get(f"/api/characters/{battlemap['b']['id']}")["character"]
    api.set_char(bram, attacks=[{"name": "Pasta", "bonus": "+2", "damage": "2d20 + 15"}, {"name": "Sentinel", "reaction": "sentinel"}])
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [bram["id"]]})
    eid, by = start(api, battlemap, {"Bandit 1": 18, "Aria": 12, "Bram": 10, "Bandit 2": 5})
    api.patch(f"/api/combatants/{by['Bandit 1']['id']}", {"changes": {"hidden": {"from": False, "to": True}}})
    api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 2, "attacker_id": by["Bandit 1"]["id"]})
    assert not battlemap["pb"].get("/api/play/state")["character"]["reaction"]["offers"]
    api.patch(f"/api/combatants/{by['Bandit 1']['id']}", {"changes": {"hidden": {"from": True, "to": False}}})
    api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Aria"]["id"]], "amount": 2, "attacker_id": by["Bandit 1"]["id"]})
    assert battlemap["pb"].get("/api/play/state")["character"]["reaction"]["offers"][0]["kind"] == "sentinel"   # no map: offered
    assert not battlemap["pa"].get("/api/play/state")["character"]["reaction"]["offers"]
