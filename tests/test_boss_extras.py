"""Boss extras: legendary actions (at the end of other turns, back at the start of its own),
phase 2 attacks from half HP, legendary resistance (a failed save becomes a success; Take it back
gives it back), and the players' boss bar in quarters (never the HP)."""
from app import dice
from tests.test_dice_map_players import battlemap, joined  # noqa: F401  (fixtures)
from tests.test_spells import Loaded

DRAGON = {"name": "Young dragon", "max_hp": 100, "ac": 17, "boss": True, "attacks": "Bite: +8 to hit, 2d10+4 piercing damage",
          "legendary": "Tail: +8 to hit, 1d8+4 bludgeoning damage\nWing beat: +8 to hit, 1d6 damage", "legendary_per_round": 2,
          "has_phase2": True, "phase2": "Fire breath: 8d6 fire damage, 30 ft cone", "legendary_resistance": 2}


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


def test_no_phase_two_unless_ticked(api, battlemap):
    """Phase 2 is a tick box: with it off the boss stays in phase 1 at half HP, attacks or not."""
    cr = api.post("/api/creatures", dict(DRAGON, has_phase2=False, campaign_id=battlemap["camp"]["id"]), 201)["creature"]
    assert cr["has_phase2"] is False
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"], "count": 1})
    api.post(f"/api/encounters/{eid}/start")
    d = dragon(api, eid)
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 60})
    assert dragon(api, eid)["boss"]["phase"] == 1
    on = api.post("/api/creatures", dict(DRAGON, phase2="", campaign_id=battlemap["camp"]["id"]), 201)["creature"]  # ticked, no extra attacks
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": on["id"], "count": 1})
    d2 = [c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Young dragon")][-1]
    api.post(f"/api/combatants/{d2['id']}/hp", {"op": "damage", "amount": 50})
    assert next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["id"] == d2["id"])["boss"]["phase"] == 2


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


def test_migration_keeps_phase_two_on_for_bosses_that_had_its_attacks(data_dir):
    """v14 adds the tick box: a boss saved with phase 2 attacks comes back with it ticked."""
    import os, sqlite3
    from app import create_app, db as appdb
    from tests.conftest import Api
    api = Api(create_app({"DATA_DIR": data_dir}).test_client())
    a = api.post("/api/creatures", dict(DRAGON), 201)["creature"]
    b = api.post("/api/creatures", dict(DRAGON, phase2="", has_phase2=False, name="Ogre"), 201)["creature"]
    path = os.path.join(data_dir, "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE creatures DROP COLUMN has_phase2")
    conn.execute("ALTER TABLE creatures DROP COLUMN tagline")
    conn.execute("ALTER TABLE creatures DROP COLUMN loot")
    conn.execute("ALTER TABLE combatants DROP COLUMN reaction")
    conn.execute("PRAGMA user_version = 13")
    conn.commit(); conn.close()
    api = Api(create_app({"DATA_DIR": data_dir}).test_client())
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == appdb.SCHEMA_VERSION
    got = {x["id"]: x for x in api.get("/api/creatures")["creatures"]}
    assert got[a["id"]]["has_phase2"] is True and got[b["id"]]["has_phase2"] is False


def by_id(api, eid, name):
    return next(c for c in api.get(f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["creature_id"]


def test_a_boss_is_in_a_fight_only_once(api, battlemap):
    """Adding a boss that's already in the fight is refused (from the Combat page or the map);
    asking for several adds just one. Ordinary monsters still come in as many as you like."""
    eid, by = fight(api, battlemap)
    cr = {"id": by_id(api, eid, "Young dragon")}
    err = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"], "count": 1}, 400)
    assert "already in this fight" in err["error"]
    err = api.post(f"/api/maps/{battlemap['mid']}/monsters", {"creature_id": cr["id"], "x": 1, "y": 1}, 400)
    assert "already in this fight" in err["error"]
    names = [c["name"] for c in api.get(f"/api/encounters/{eid}")["combatants"]]
    assert names.count("Young dragon") == 1 and not any(n.startswith("Young dragon ") for n in names)
    other = api.post(f"/api/campaigns/{battlemap['camp']['id']}/encounters", {"name": "Second"}, 201)["encounter"]["id"]
    api.post(f"/api/encounters/{other}/combatants", {"creature_id": cr["id"], "count": 3})
    assert [c["name"] for c in api.get(f"/api/encounters/{other}")["combatants"]].count("Young dragon") == 1
    ogre = api.post("/api/creatures", {"name": "Ogre", "max_hp": 30, "ac": 11}, 201)["creature"]
    api.post(f"/api/encounters/{other}/combatants", {"creature_id": ogre["id"], "count": 2})
    api.post(f"/api/encounters/{other}/combatants", {"creature_id": ogre["id"], "count": 1})
    assert sum(c["name"].startswith("Ogre") for c in api.get(f"/api/encounters/{other}")["combatants"]) == 3


def test_entrance_title_and_loot_once(api, battlemap):
    """A boss's title reaches every screen (the players' list too), and its loot goes out to
    everyone as a handout once it's down: only once a fight, even if the kill is undone and redone."""
    cr = api.post("/api/creatures", dict(DRAGON, tagline="Terror of the Peaks", loot="A dragon scale shield and 300 gold",
                                         campaign_id=battlemap["camp"]["id"]), 201)["creature"]
    assert cr["tagline"] == "Terror of the Peaks" and cr["loot"].startswith("A dragon scale")
    eid = battlemap["eid"]
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"], "count": 1})
    api.post(f"/api/encounters/{eid}/start")
    d = dragon(api, eid)
    assert d["boss"]["tagline"] == "Terror of the Peaks" and d["boss"]["has_loot"] is True
    mine = next(o for o in battlemap["pa"].get("/api/play/state")["encounter"]["order"] if o["name"] == "Young dragon")
    assert mine["tagline"] == "Terror of the Peaks" and mine["fresh"] is True and "loot" not in str(mine)
    err = api.post(f"/api/combatants/{d['id']}/loot", {}, 400)
    assert "isn't defeated yet" in err["error"]
    camp = battlemap["camp"]["id"]
    count = lambda: sum(h["title"] == "Young dragon's loot" for h in api.get(f"/api/campaigns/{camp}/handouts")["handouts"])
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 100})
    assert api.post(f"/api/combatants/{d['id']}/loot", {})["sent"] is True and count() == 1
    assert api.post(f"/api/combatants/{d['id']}/loot", {})["sent"] is False and count() == 1
    api.post(f"/api/encounters/{eid}/undo", {})                                        # the kill is taken back...
    assert dragon(api, eid)["hp"] > 0
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 100})          # ...and done again
    assert api.post(f"/api/combatants/{d['id']}/loot", {})["sent"] is False and count() == 1
    h = next(h for h in api.get(f"/api/campaigns/{camp}/handouts")["handouts"] if h["title"] == "Young dragon's loot")
    assert h["body"] == "A dragon scale shield and 300 gold" and h["to"] is None
    assert any("loot was sent to everyone" in x["message"] for x in api.get(f"/api/encounters/{eid}")["log"])


def test_a_boss_without_loot_sends_nothing(api, battlemap):
    eid, by = fight(api, battlemap)
    d = dragon(api, eid)
    api.post(f"/api/combatants/{d['id']}/hp", {"op": "damage", "amount": 100})
    assert api.post(f"/api/combatants/{d['id']}/loot", {})["sent"] is False
    assert api.get(f"/api/campaigns/{battlemap['camp']['id']}/handouts")["handouts"] == []


def test_make_it_a_boss(api):
    """A boss copy scaled for the party; the original monster stays as it was."""
    from app.creatures import legendary_from
    camp = api.campaign()
    orc = api.post("/api/creatures", {"name": "Orc", "max_hp": 15, "ac": 13, "campaign_id": camp["id"],
                                      "attacks": "Greataxe: +5 to hit, 1d12+3 slashing damage\nJavelin: +5 to hit, 2d6+3 piercing damage, ranged\n"
                                                 "Roar: DC 12, Frightened, 15 ft radius\nCleave: +5 to hit, 2d8 slashing damage, 3 turn cooldown"}, 201)["creature"]
    r = api.post(f"/api/creatures/{orc['id']}/make-boss", {"campaign_id": camp["id"], "party_size": 4, "party_level": 5}, 201)
    b = r["creature"]
    assert b["name"] == "Orc (Boss)" and b["boss"] and b["has_phase2"] and b["max_hp"] == 60 and b["ac"] == 15
    assert b["legendary_per_round"] == 3 and b["legendary_resistance"] == 2
    assert b["legendary"] == "Greataxe: +5 to hit, 1d10+3 slashing damage\nJavelin: +5 to hit, 1d6+3 piercing damage, ranged"
    assert b["attacks"] == orc["attacks"] and r["from"] == {"max_hp": 15, "ac": 13}
    kept = next(c for c in api.get(f"/api/creatures?campaign_id={camp['id']}")["creatures"] if c["id"] == orc["id"])
    assert kept["max_hp"] == 15 and not kept["boss"] and kept["legendary"] == ""            # the original is untouched
    assert legendary_from("Bite: 1d4 piercing damage\nHeal: heal 2d8") == "Bite: 1d4 piercing damage"
    small = api.post(f"/api/creatures/{orc['id']}/make-boss", {"party_size": 1, "party_level": 1}, 201)["creature"]
    assert small["max_hp"] == 30 and small["ac"] == 14 and small["legendary_resistance"] == 1   # at least x2 HP


def test_make_it_a_boss_uses_the_campaign_party(api):
    camp = api.campaign()
    for n, lvl in (("A", 3), ("B", 4), ("C", 3)):
        api.character(camp["id"], name=n, level=lvl)
    assert api.get(f"/api/creatures/boss-party?campaign_id={camp['id']}") == {"size": 3, "level": 3}
    gob = api.post("/api/creatures", {"name": "Goblin", "max_hp": 7, "ac": 15, "campaign_id": camp["id"], "attacks": "Scimitar: +4 to hit, 1d6+2 slashing damage"}, 201)["creature"]
    b = api.post(f"/api/creatures/{gob['id']}/make-boss", {"campaign_id": camp["id"]}, 201)["creature"]
    assert b["max_hp"] == 21 and b["ac"] == 16 and b["legendary"] == "Scimitar: +4 to hit, 1d4+2 slashing damage"
