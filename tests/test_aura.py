"""Moni's magic item: switched on, every ally in 60 ft (or the whole party when there's no
battle map) gets double speed and +20 max HP and HP until it's switched off."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

ITEM = {"name": "Magic item", "effect": "buff", "level": 0, "aura": True, "speed_mult": 2, "max_hp": 20,
        "area": "60 ft radius", "notes": "Allies in 60 ft: double speed and +20 HP"}


def chars(api, camp):
    return {c["name"]: c for c in api.get(f"/api/campaigns/{camp['id']}/characters")["characters"]}


def test_switch_on_and_off_outside_a_fight(api, battlemap):
    camp = battlemap["camp"]
    by = chars(api, camp)
    aria = api.get(f"/api/characters/{by['Aria']['id']}")["character"]
    api.set_char(aria, spells=[ITEM])
    hp0 = {n: (c["current_hp"], c["max_hp"]) for n, c in chars(api, camp).items()}
    r = api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": True})
    assert set(r["aura"]["who"]) == set(hp0), "the whole party, Aria included"
    for n, c in chars(api, camp).items():
        assert (c["current_hp"], c["max_hp"]) == (hp0[n][0] + 20, hp0[n][1] + 20)
        full = api.get(f"/api/characters/{c['id']}")["character"]
        item = next(x for x in full["conditions"] if x.get("aura"))
        assert item["speed_mult"] == 2 and item["max_hp"] == 20 and item["rounds_left"] is None
    # on again: nobody gets it twice
    r = api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": True})
    assert r["aura"]["who"] == []
    # someone takes damage while it's on, then it's switched off: max HP back, HP never above max
    bo = chars(api, camp)["Bram"]
    bo = api.set_char(api.get(f"/api/characters/{bo['id']}")["character"], current_hp=bo["max_hp"] - 5)
    r = api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": False})
    assert set(r["aura"]["who"]) == set(hp0)
    now = chars(api, camp)
    for n in hp0:
        assert now[n]["max_hp"] == hp0[n][1] and now[n]["current_hp"] <= now[n]["max_hp"]
        assert not any(x.get("aura") for x in api.get(f"/api/characters/{now[n]['id']}")["character"]["conditions"])


def test_in_a_fight_only_allies_within_60_ft(api, battlemap):
    camp, eid, mid = battlemap["camp"], battlemap["eid"], battlemap["mid"]
    by = chars(api, camp)
    aria = api.get(f"/api/characters/{by['Aria']['id']}")["character"]
    api.set_char(aria, spells=[ITEM])
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [by["Bram"]["id"]]})
    api.post(f"/api/maps/{mid}/tokens/from-encounter")
    api.patch(f"/api/maps/{mid}", {"changes": {"cols": {"to": 40}}})
    m = api.get(f"/api/maps/{mid}")
    api.post(f"/api/tokens/{tok(m, 'Aria')['id']}/move", {"free": True, "x": 0, "y": 0})
    api.post(f"/api/tokens/{tok(m, 'Bram')['id']}/move", {"free": True, "x": 30, "y": 0})      # 150 ft away
    api.post(f"/api/tokens/{tok(m, 'Bandit 1')['id']}/move", {"free": True, "x": 2, "y": 0})  # an enemy right beside her
    api.post(f"/api/encounters/{eid}/start")
    r = api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": True})
    assert r["aura"]["who"] == ["Aria"], "Bram is too far; the bandit is an enemy"
    api.post(f"/api/tokens/{tok(m, 'Bram')['id']}/move", {"free": True, "x": 12, "y": 0})      # 60 ft away
    r = api.post(f"/api/characters/{aria['id']}/aura", {"index": 0, "on": True})
    assert r["aura"]["who"] == ["Bram"]
    st = api.get(f"/api/encounters/{eid}")
    a = next(c for c in st["combatants"] if c["name"] == "Aria")
    assert a["spells"][0]["aura_on"] is True
    b1 = next(c for c in st["combatants"] if c["name"] == "Bandit 1")
    assert not any(x.get("aura") for x in b1["conditions"])
    # it lasts: next turns and the end of the fight don't take it off
    for _ in range(4):
        api.post(f"/api/encounters/{eid}/next")
    api.post(f"/api/encounters/{eid}/end")
    assert any(x.get("aura") for x in api.get(f"/api/characters/{by['Bram']['id']}")["character"]["conditions"])


def test_the_player_switches_it_from_their_phone(api, battlemap):
    camp = battlemap["camp"]
    by = chars(api, camp)
    api.set_char(api.get(f"/api/characters/{by['Aria']['id']}")["character"], spells=[ITEM])
    pa = battlemap["pa"]
    me = pa.get("/api/play/state")["character"]
    assert me["spells"][0]["aura"] and me["spells"][0]["aura_on"] is False
    r = pa.post("/api/play/me/aura", {"index": 0, "on": True})
    assert r["character"]["spells"][0]["aura_on"] is True
    assert any("speed ×2" in c and "+20 max HP" in c for c in r["character"]["conditions"])
    r = pa.post("/api/play/me/aura", {"index": 0, "on": False})
    assert r["character"]["spells"][0]["aura_on"] is False
