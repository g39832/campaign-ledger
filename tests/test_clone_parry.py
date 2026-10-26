"""Yamato: a spell that summons his clone (it acts right after him), and Parry: when
he's hit, a d20 roll-off with the DM; if he wins he takes half (rounded down)."""
from app import dice
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

SPELLS = [{"name": "Phantasmal force", "effect": "buff", "level": 0, "summon": "Yamato clone", "cooldown": 2, "notes": "Makes a copy of him"},
          {"name": "Parry", "effect": "damage", "dice": "1d4", "hit": "attack", "level": 0, "parry": True, "cooldown": 1}]


def setup(api, battlemap, rolls=None):
    api.post("/api/creatures", {"name": "Yamato clone", "max_hp": 1, "ac": 5, "attacks": "Slash 2d8"}, 201)
    aria = api.get(f"/api/characters/{battlemap['a']['id']}")["character"]
    api.set_char(aria, spells=SPELLS, current_hp=20, max_hp=20)
    eid = battlemap["eid"]
    st = api.get(f"/api/encounters/{eid}")
    by = {c["name"]: c for c in st["combatants"]}
    for name, roll in (rolls or {"Aria": 12, "Bandit 1": 18, "Bandit 2": 5}).items():
        api.patch(f"/api/combatants/{by[name]['id']}", {"changes": {"init_roll": {"from": None, "to": roll}}})
    return eid, by


def order(st):
    return [c["name"] for c in st["combatants"]]


def test_clone_appears_right_after_him_and_stays_there(api, battlemap):
    eid, by = setup(api, battlemap)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    assert order(st) == ["Bandit 1", "Aria", "Yamato clone", "Bandit 2"]
    clone = next(c for c in st["combatants"] if c["name"] == "Yamato clone")
    assert clone["kind"] == "npc" and clone["hp"] == 1 and clone["ac"] == 5 and clone["follows"] == by["Aria"]["id"]
    assert clone["statblock"]["attacks"] == "Slash 2d8"
    assert "Yamato clone appears and will act right after Aria" in st["cast"]["summary"]
    # Aria's initiative changes: the clone moves with her
    st = api.patch(f"/api/combatants/{by['Aria']['id']}", {"changes": {"init_roll": {"from": 12, "to": 2}}})
    assert order(st) == ["Bandit 1", "Bandit 2", "Aria", "Yamato clone"]
    st = api.post(f"/api/encounters/{eid}/roll", {"scope": "enemies"})
    assert order(st).index("Yamato clone") == order(st).index("Aria") + 1
    # a token next to her on the fight's map
    m = api.get(f"/api/maps/{battlemap['mid']}")
    me, cl = tok(m, "Aria"), tok(m, "Yamato clone")
    assert max(abs(me["x"] - cl["x"]), abs(me["y"] - cl["y"])) <= 1
    # one at a time while it stands; when it's beaten another can be made
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []}, 400)
    assert "still standing" in err["error"]
    api.post(f"/api/combatants/{clone['id']}/hp", {"op": "damage", "amount": 1})
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    assert "Yamato clone 2" in order(st)


def test_clone_turn_comes_right_after_his(api, battlemap):
    eid, by = setup(api, battlemap)
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": 0, "targets": []})
    st = api.post(f"/api/encounters/{eid}/start")
    seen = []
    for _ in range(5):
        seen.append(next(c["name"] for c in st["combatants"] if c["id"] == st["encounter"]["current_id"]))
        st = api.post(f"/api/encounters/{eid}/next")
    assert seen[:4] == ["Bandit 1", "Aria", "Yamato clone", "Bandit 2"]


def test_missing_clone_creature_is_explained(api, battlemap):
    eid, by = setup(api, battlemap)
    spec = {"name": "Summon", "effect": "buff", "summon": "Nothing like it"}
    err = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": []}, 400)
    assert "creature library" in err["error"]


def test_parry_won_takes_half_rounded_down(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid, by = setup(api, battlemap)
    aria = by["Aria"]
    st = api.get(f"/api/encounters/{eid}")
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["parry"] == {"name": "Parry", "ready": True, "pending": None}
    api.post(f"/api/encounters/{eid}/start")
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [aria["id"]], "amount": 9, "attacker_id": by["Bandit 1"]["id"]})
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 11 and a["parry"]["pending"]["amount"] == 9
    loaded.next(17, 4)  # Aria 17, DM 4
    r = api.post(f"/api/combatants/{aria['id']}/parry")
    assert r["parry"] == {"won": True, "me": 17, "dm": 4, "amount": 9, "taken": 4, "name": "Parry"}
    a = next(c for c in r["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 16, "takes 4 (half of 9, rounded down) instead of 9"
    assert a["parry"]["ready"] is False, "then Parry recharges"
    assert any("Aria parries: takes 4 instead of 9" in e["message"] for e in r["log"])
    # the roll-off is in the dice history, and Undo HP takes back the parry first
    labels = [x["label"] for x in api.get(f"/api/rolls?encounter_id={eid}")["rolls"]]
    assert "Parry roll-off — Aria" in labels and "Parry roll-off — DM" in labels
    st = api.post(f"/api/encounters/{eid}/undo")
    assert next(c for c in st["combatants"] if c["name"] == "Aria")["hp"] == 11
    api.post(f"/api/combatants/{aria['id']}/parry", expect=400)  # recharging


def test_parry_lost_and_ties_roll_again(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid, by = setup(api, battlemap)
    aria = by["Aria"]
    api.post(f"/api/encounters/{eid}/damage", {"targets": [aria["id"]], "amount": 7})
    loaded.next(10, 10, 3, 15)  # tie, then Aria 3 vs DM 15
    r = api.post(f"/api/combatants/{aria['id']}/parry")
    assert r["parry"]["won"] is False and r["parry"]["me"] == 3 and r["parry"]["dm"] == 15
    assert next(c for c in r["combatants"] if c["name"] == "Aria")["hp"] == 13, "the full 7"
    assert any("tied at 10" in e["message"] for e in r["log"])


def test_parry_saves_him_from_dropping(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid, by = setup(api, battlemap)
    aria = by["Aria"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [aria["id"]], "amount": 25})
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 0 and any(x["name"] == "Prone" for x in a["conditions"])
    loaded.next(20, 1)
    r = api.post(f"/api/combatants/{aria['id']}/parry")
    a = next(c for c in r["combatants"] if c["name"] == "Aria")
    assert a["hp"] == 8 and a["status"] == "ok" and not any(x["name"] == "Prone" for x in a["conditions"])


def test_only_the_last_hit_and_players_can_parry_their_own(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid, by = setup(api, battlemap)
    aria = by["Aria"]
    api.post(f"/api/combatants/{aria['id']}/parry", expect=400)  # nothing to parry
    api.post(f"/api/encounters/{eid}/damage", {"targets": [aria["id"]], "amount": 6})
    api.post(f"/api/combatants/{aria['id']}/hp", {"op": "heal", "amount": 1})
    api.post(f"/api/combatants/{aria['id']}/parry", expect=400)  # healed since: the hit isn't the last change
    api.post(f"/api/encounters/{eid}/damage", {"targets": [aria["id"]], "amount": 6})
    api.post(f"/api/encounters/{eid}/start")
    pa = battlemap["pa"]
    me = pa.get("/api/play/state")["character"]
    assert me["parry"]["pending"]["amount"] == 6
    loaded.next(19, 2)
    r = pa.post("/api/play/me/parry")
    assert r["parry"]["won"] and r["parry"]["taken"] == 3 and r["character"]["current_hp"] == 20 - 5 - 3


def test_player_summons_their_clone_on_their_turn(api, battlemap):
    eid, by = setup(api, battlemap)
    pa = battlemap["pa"]
    api.post(f"/api/encounters/{eid}/start")
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    pa.post("/api/play/cast", {"spell": 0, "targets": []}, 403)  # not her turn
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    r = pa.post("/api/play/cast", {"spell": 0, "targets": []})
    assert "Yamato clone appears" in r["cast"]["summary"]
    st = api.get(f"/api/encounters/{eid}")
    assert order(st).index("Yamato clone") == order(st).index("Aria") + 1


def test_players_never_see_monster_ac(api, battlemap):
    """Players see their own AC, but no one else's: not in the party list, the turn
    order, the map, or the dice history when the DM attacks."""
    import json as _json
    eid, by = setup(api, battlemap)
    api.patch(f"/api/combatants/{by['Bandit 1']['id']}", {"changes": {"ac": {"from": by["Bandit 1"]["ac"], "to": 17}}})
    api.post(f"/api/campaigns/{battlemap['camp']['id']}/live-map", {"map_id": battlemap["mid"]})
    api.post(f"/api/encounters/{eid}/start")
    spec = {"name": "Fire Bolt", "effect": "damage", "dice": "1d10", "hit": "attack", "attack_bonus": 5}
    api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Aria"]["id"], "spell": spec, "targets": [by["Bandit 1"]["id"]]})
    pa = battlemap["pa"]
    st = pa.get("/api/play/state")
    assert "ac" in st["character"], "their own AC is still there"
    assert all("ac" not in p for p in st["party"])
    others = _json.dumps({k: v for k, v in st.items() if k != "character"})
    assert '"ac"' not in others and "AC 17" not in others
    rolls = pa.get("/api/rolls")["rolls"]
    assert rolls and not any("17" in (r["outcome"] or "") or "AC" in (r["outcome"] or "") or "AC" in r["label"] for r in rolls)
