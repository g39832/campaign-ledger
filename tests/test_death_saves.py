"""House rules at 0 HP: heroes are knocked prone and make death saves (an ally
right next to them on the battle map adds a bonus); monsters are defeated."""
import pytest

from app import dice
from tests.test_dice_map_players import remote


@pytest.fixture
def fight(api):
    camp = api.campaign()
    lux = api.character(camp["id"], name="Lux", max_hp=13, ac=8)
    yam = api.character(camp["id"], name="Yamato", max_hp=25, ac=12)
    eid = api.encounter(camp["id"], "Tavern")["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [lux["id"], yam["id"]], "quick": {"name": "Ogre", "max_hp": 30, "count": 1}})
    r = api.post(f"/api/encounters/{eid}/map")
    api.post(f"/api/encounters/{eid}/start")
    st = api.get(f"/api/encounters/{eid}")
    by = {c["name"]: c for c in st["combatants"]}
    return {"camp": camp, "eid": eid, "map": r["map_id"], "lux": lux, "yam": yam, "by": by}


def tok(api, mid, name):
    return next(t for t in api.get(f"/api/maps/{mid}")["tokens"] if t["display"] == name)


def fixed_d20(monkeypatch, value):
    real = dice.roll
    def roll(expr, *a, **k):
        r = real(expr, *a, **k)
        if expr.startswith("1d20"):
            r["total"] += value - r["natural"]
            r["natural"] = value
        return r
    monkeypatch.setattr(dice, "roll", roll)


def test_hero_at_zero_is_knocked_prone_monster_is_defeated(api, fight):
    eid, by = fight["eid"], fight["by"]
    st = api.post(f"/api/encounters/{eid}/damage", {"targets": [by["Lux"]["id"], by["Ogre"]["id"]], "amount": 40})
    now = {c["name"]: c for c in st["combatants"]}
    assert now["Lux"]["status"] == "unconscious" and "Prone" in [x["name"] for x in now["Lux"]["conditions"]]
    assert now["Ogre"]["status"] == "defeated" and "Prone" not in [x["name"] for x in now["Ogre"]["conditions"]]
    assert any("knocked prone" in e["message"] for e in st["log"])
    # knocked prone outside a fight too (damage from the sheet)
    other = api.character(fight["camp"]["id"], name="Gnocchi", max_hp=18)
    ch = api.post(f"/api/characters/{other['id']}/hp", {"op": "damage", "amount": 30})["character"]
    assert ch["current_hp"] == 0 and [x["name"] for x in ch["conditions"]] == ["Prone"]


def test_death_saves_count_themselves(api, fight, monkeypatch):
    eid, lux = fight["eid"], fight["by"]["Lux"]
    api.post(f"/api/combatants/{lux['id']}/death-save", {}, 400)  # not at 0 HP yet
    api.post(f"/api/encounters/{eid}/damage", {"targets": [lux["id"]], "amount": 20})
    # move Yamato far away so there's no bonus
    api.post(f"/api/tokens/{tok(api, fight['map'], 'Yamato')['id']}/move", {"free": True, "x": 20, "y": 14})
    fixed_d20(monkeypatch, 12)
    st = api.post(f"/api/combatants/{lux['id']}/death-save", {})
    assert st["roll"]["expression"] == "1d20" and st["roll"]["label"] == "Death save"
    me = next(c for c in st["combatants"] if c["name"] == "Lux")
    assert (me["death_successes"], me["death_failures"]) == (1, 0)
    fixed_d20(monkeypatch, 1)
    st = api.post(f"/api/combatants/{lux['id']}/death-save", {})
    me = next(c for c in st["combatants"] if c["name"] == "Lux")
    assert me["death_failures"] == 2 and "two failures" in st["roll"]["outcome"]
    fixed_d20(monkeypatch, 4)
    st = api.post(f"/api/combatants/{lux['id']}/death-save", {})
    me = next(c for c in st["combatants"] if c["name"] == "Lux")
    assert me["death_failures"] == 3 and me["status"] == "dead" and st["roll"]["outcome"].endswith("dead")
    api.post(f"/api/combatants/{lux['id']}/death-save", {}, 400)


def test_three_successes_stable_and_natural_20_gets_up(api, fight, monkeypatch):
    eid, lux = fight["eid"], fight["by"]["Lux"]
    api.post(f"/api/encounters/{eid}/damage", {"targets": [lux["id"]], "amount": 20})
    fixed_d20(monkeypatch, 15)
    for _ in range(3):
        st = api.post(f"/api/combatants/{lux['id']}/death-save", {})
    assert next(c for c in st["combatants"] if c["name"] == "Lux")["status"] == "stable"
    api.post(f"/api/combatants/{lux['id']}/death-save", {}, 400)  # stable: no more saves
    yam = fight["by"]["Yamato"]
    api.post(f"/api/encounters/{eid}/damage", {"targets": [yam["id"]], "amount": 30})
    fixed_d20(monkeypatch, 20)
    st = api.post(f"/api/combatants/{yam['id']}/death-save", {})
    y = next(c for c in st["combatants"] if c["name"] == "Yamato")
    assert y["hp"] == 1 and y["status"] == "ok" and (y["death_successes"], y["death_failures"]) == (0, 0)


def test_an_ally_next_to_them_gives_a_bonus(api, fight, monkeypatch):
    fixed_d20(monkeypatch, 12)  # a natural 20 would get her up and end the saves
    eid, lux, mid = fight["eid"], fight["by"]["Lux"], fight["map"]
    api.post(f"/api/encounters/{eid}/damage", {"targets": [lux["id"]], "amount": 20})
    lt = tok(api, mid, "Lux")
    api.post(f"/api/tokens/{tok(api, mid, 'Yamato')['id']}/move", {"free": True, "x": lt["x"] + 1, "y": lt["y"] + 1})  # diagonal counts
    r = api.post(f"/api/combatants/{lux['id']}/death-save", {})["roll"]
    assert r["expression"] == "1d20+2" and r["label"] == "Death save +2 (Yamato beside them)"
    # two squares away: no bonus
    api.post(f"/api/tokens/{tok(api, mid, 'Yamato')['id']}/move", {"free": True, "x": lt["x"] + 2, "y": lt["y"]})
    assert api.post(f"/api/combatants/{lux['id']}/death-save", {})["roll"]["expression"] == "1d20"
    # a downed ally doesn't help
    api.post(f"/api/tokens/{tok(api, mid, 'Yamato')['id']}/move", {"free": True, "x": lt["x"] + 1, "y": lt["y"]})
    api.post(f"/api/encounters/{eid}/damage", {"targets": [fight["by"]["Yamato"]["id"]], "amount": 40})
    assert api.post(f"/api/combatants/{lux['id']}/death-save", {})["roll"]["expression"] == "1d20"


def test_bonus_size_is_a_setting(api, fight, monkeypatch):
    fixed_d20(monkeypatch, 12)
    camp = next(c for c in api.get("/api/campaigns")["campaigns"] if c["id"] == fight["camp"]["id"])
    s = camp["settings"]
    s["combat"]["ally_death_save_bonus"] = 5
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"from": {}, "to": s}}})
    lux, mid = fight["by"]["Lux"], fight["map"]
    api.post(f"/api/encounters/{fight['eid']}/damage", {"targets": [lux["id"]], "amount": 20})
    lt = tok(api, mid, "Lux")
    api.post(f"/api/tokens/{tok(api, mid, 'Yamato')['id']}/move", {"free": True, "x": lt["x"], "y": lt["y"] + 1})
    assert api.post(f"/api/combatants/{lux['id']}/death-save", {})["roll"]["expression"] == "1d20+5"
    bad = dict(s, combat=dict(s["combat"], ally_death_save_bonus=99))
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"from": s, "to": bad}}}, 400)  # checked before saving


def test_players_roll_their_own_death_saves(app, api, fight):
    code = api.post(f"/api/campaigns/{fight['camp']['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.71")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": fight["lux"]["id"]})
    p.post("/api/play/me/death-save", {}, 400)
    api.post(f"/api/encounters/{fight['eid']}/damage", {"targets": [fight["by"]["Lux"]["id"]], "amount": 20})
    d = p.post("/api/play/me/death-save", {})
    me = d["character"]
    assert d["roll"]["kind"] == "death"
    assert me["death_successes"] + me["death_failures"] >= 1 or me["current_hp"] == 1, "the save was marked (or a natural 20 got them up)"
    p.post(f"/api/characters/{fight['yam']['id']}/death-save", {}, 403)  # not their character, and DM-only route
