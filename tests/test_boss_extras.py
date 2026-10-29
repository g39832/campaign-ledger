"""Boss extras: legendary actions (at the end of other turns, back at the start of its own),
phase 2 attacks from half HP, legendary resistance (a failed save becomes a success; Take it back
gives it back), and the players' boss bar in quarters (never the HP)."""
from app import dice
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

DRAGON = {"name": "Young dragon", "max_hp": 100, "ac": 17, "boss": True, "attacks": "Bite: +8 to hit, 2d10+4 piercing damage",
          "legendary": "Tail: +8 to hit, 1d8+4 bludgeoning damage\nWing beat: +8 to hit, 1d6 damage", "legendary_per_round": 2,
          "phase2": "Fire breath: 8d6 fire damage, 30 ft cone", "legendary_resistance": 2}


def fight(api, bm):
    cr = api.post("/api/creatures", dict(DRAGON, campaign_id=bm["camp"]["id"]), 201)["creature"]
    eid = bm["eid"]
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"], "count": 1})
    st = api.get(f"/api/encounters/{eid}")
    by = {c["name"]: c for c in st["combatants"]}
    api.post(f"/api/encounters/{eid}/start")
    return eid, by


def dragon(api, eid):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == "Young dragon")


def test_legendary_actions(api, battlemap):
    eid, by = fight(api, battlemap)
    d = dragon(api, eid)
    assert d["boss"]["legendary"].startswith("Tail") and d["boss"]["left"] == 2 and d["boss"]["phase"] == 1
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": d["id"]})
    err = api.post(f"/api/combatants/{d['id']}/legendary", {}, 400)               # not on its own turn
    assert "other creatures' turns" in err["error"]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Aria"]["id"]})
    st = api.post(f"/api/combatants/{d['id']}/legendary", {"name": "Tail"})
    assert next(c for c in st["combatants"] if c["id"] == d["id"])["boss"]["left"] == 1
    api.post(f"/api/combatants/{d['id']}/legendary", {})
    err = api.post(f"/api/combatants/{d['id']}/legendary", {}, 400)               # used both
    assert "used all 2" in err["error"]
    assert any("uses a legendary action: Tail" in x["message"] for x in api.get(f"/api/encounters/{eid}")["log"])
    for _ in range(6):                                                              # round the table to its turn
        st = api.post(f"/api/encounters/{eid}/next")
        if st["encounter"]["current_id"] == d["id"]:
            break
    assert dragon(api, eid)["boss"]["left"] == 2                                    # back at the start of its turn


def test_phase_two_from_half_hp(api, battlemap):
    eid, by = fight(api, battlemap)
    d = dragon(api, eid)
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 49})
    assert dragon(api, eid)["boss"]["phase"] == 1
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 1})
    assert dragon(api, eid)["boss"]["phase"] == 2


def test_legendary_resistance_and_take_it_back(api, battlemap, monkeypatch):
    loaded = Loaded()
    monkeypatch.setattr(dice, "_rng", loaded)
    eid, by = fight(api, battlemap)
    d = dragon(api, eid)
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Bandit 1"]["id"]})
    hold = {"name": "Hold monster", "effect": "debuff", "condition": "Paralyzed", "hit": "wis", "force_save": True, "level": 0, "dc": 30}  # a save even with the roll-to-hit house rule
    loaded.next(1)                                                                  # the dragon's save: a 1, fails
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": hold, "targets": [d["id"]]})
    t = st["cast"]["targets"][0]
    assert t["how"] == "saved" and "Legendary Resistance" in t["text"]
    after = next(c for c in st["combatants"] if c["id"] == d["id"])
    assert after["boss"]["lr_left"] == 1 and not any(x["name"] == "Paralyzed" for x in after["conditions"])
    st = api.post(f"/api/encounters/{eid}/casts/{st['cast']['undo']}/undo", {})    # Take it back: the resistance comes back
    assert dragon(api, eid)["boss"]["lr_left"] == 2
    for _ in range(2):                                                              # use them up: then it fails
        loaded.next(1)
        api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": hold, "targets": [d["id"]]})
    loaded.next(1)
    st = api.post(f"/api/encounters/{eid}/cast", {"caster_id": by["Bandit 1"]["id"], "spell": hold, "targets": [d["id"]]})
    assert st["cast"]["targets"][0]["how"] == "failed"
    assert any(x["name"] == "Paralyzed" for x in dragon(api, eid)["conditions"])


def test_players_see_the_bar_in_quarters(api, battlemap):
    eid, by = fight(api, battlemap)
    d = dragon(api, eid)
    api.post(f"/api/campaigns/{battlemap['camp']['id']}/live-map", {"map_id": battlemap["mid"]})
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 60})
    o = next(x for x in battlemap["pa"].get("/api/play/state")["encounter"]["order"] if x["name"] == "Young dragon")
    assert o["boss"] and o["quarters"] == 2 and o["phase"] == 2
    assert "hp" not in o and "max_hp" not in o                                      # never the numbers
    # a plain enemy isn't a boss
    b1 = next(x for x in battlemap["pa"].get("/api/play/state")["encounter"]["order"] if x["name"] == "Bandit 1")
    assert not b1.get("boss")
