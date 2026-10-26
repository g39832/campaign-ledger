"""The spell engine: damage, healing, buffs and debuffs cast in a fight, with their
effects (saves for half, resistances, crits, upcasting, slots, concentration, roll
bonuses, advantage, more max HP, damage or healing every turn, saves to end an effect).

Dice are loaded per test so every outcome is exact."""
import pytest

from app import dice
from app.spell_book import SPELLS, find
from app.rules import spell_info

BOOK = {s["name"]: s for s in SPELLS}


class Loaded:
    """Stands in for the dice. Values queued with .next() come out first (in order);
    after that every die rolls `rest` (a number, or 'max' / 'min')."""

    def __init__(self):
        self.queue, self.rest = [], "max"

    def next(self, *values):
        self.queue.extend(values)
        return self

    def randint(self, lo, hi):
        if self.queue:
            return max(lo, min(hi, self.queue.pop(0)))
        return hi if self.rest == "max" else lo if self.rest == "min" else max(lo, min(hi, self.rest))


@pytest.fixture
def loaded(monkeypatch):
    d = Loaded()
    monkeypatch.setattr(dice, "_rng", d)
    return d


def book(name, **over):
    return dict(BOOK[name], **over)


@pytest.fixture
def table(api):
    """A cleric and a wizard (level 5, slots) against goblins and a fire-resistant imp."""
    camp = api.campaign("Spells")
    cid = camp["id"]
    cleric = api.character(cid, name="Bram", max_hp=30, ac=14, level=5)
    cleric = api.set_char(cleric, spellcasting_ability="wis", current_hp=30,
                          abilities={"str": 10, "dex": 10, "con": 14, "int": 10, "wis": 16, "cha": 10}, save_profs=["wis", "cha"],
                          spell_slots={"1": {"max": 4, "used": 0}, "2": {"max": 3, "used": 0}, "3": {"max": 2, "used": 0}},
                          spells=[book("Cure Wounds"), book("Bless"), book("Shield of Faith"), book("Hold Person"),
                                  book("Spirit Guardians"), book("Mass Healing Word"), book("Aid"), book("Sacred Flame"),
                                  {"name": "Old notes spell", "level": 1, "notes": "just words"}])
    wizard = api.character(cid, name="Ilse", max_hp=22, ac=12, level=5)
    wizard = api.set_char(wizard, spellcasting_ability="int", current_hp=22,
                          abilities={"str": 8, "dex": 14, "con": 12, "int": 18, "wis": 10, "cha": 10},
                          spell_slots={"1": {"max": 4, "used": 0}, "2": {"max": 3, "used": 0}, "3": {"max": 2, "used": 0}},
                          spells=[book("Fireball"), book("Fire Bolt"), book("Magic Missile"), book("False Life"), book("Faerie Fire"),
                                  book("Moonbeam"), book("Heroism"), book("Shield")])
    imp = api.post("/api/creatures", {"name": "Imp", "max_hp": 40, "ac": 13, "resistances": "cold; bludgeoning, piercing, and slashing from nonmagical attacks",
                                       "immunities": "fire, poison", "vulnerabilities": "radiant",
                                       "abilities": {"str": 6, "dex": 17, "con": 13, "int": 11, "wis": 12, "cha": 14}}, 201)["creature"]
    mage = api.post("/api/creatures", {"name": "Cult mage", "max_hp": 30, "ac": 12, "traits": "Spellcasting. Wisdom (spell save DC 13, +5 to hit with spell attacks).",
                                        "spells": "Hold person\nFire bolt +7 2d10", "abilities": {"wis": 14}}, 201)["creature"]
    eid = api.encounter(cid, "Crypt")["encounter"]["id"]
    api.post(f"/api/encounters/{eid}/combatants", {"characters": [cleric["id"], wizard["id"]],
                                                    "quick": {"name": "Goblin", "max_hp": 40, "ac": 13, "count": 2}})
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": imp["id"]})
    st = api.post(f"/api/encounters/{eid}/combatants", {"creature_id": mage["id"]})
    by = {c["name"]: c for c in st["combatants"]}
    return {"api": api, "camp": camp, "eid": eid, "by": by, "cleric": cleric, "wizard": wizard}


def settings(api, camp, **combat):
    s = next(c for c in api.get("/api/campaigns")["campaigns"] if c["id"] == camp["id"])["settings"]
    s["combat"].update(combat)
    api.patch(f"/api/campaigns/{camp['id']}", {"changes": {"settings": {"to": s}}})


def cast(t, caster, spell, targets, expect=200, **kw):
    body = {"caster_id": t["by"][caster]["id"], "spell": spell, "targets": [t["by"][n]["id"] for n in targets], **kw}
    return t["api"].post(f"/api/encounters/{t['eid']}/cast", body, expect)


def who(st, name):
    return next(c for c in st["combatants"] if c["name"] == name)


def eff(c, name):
    return next((x for x in c["conditions"] if x["name"] == name), None)


# ---- the book -------------------------------------------------------------------

def test_every_book_spell_normalises_and_has_a_kind():
    assert len(SPELLS) >= 60
    for s in SPELLS:
        sp = spell_info(s)
        assert sp["kind"] in ("damage", "heal", "buff", "debuff"), s["name"]
        if sp["kind"] in ("damage", "heal"):
            assert sp["dice"] or sp["temp_hp"], s["name"]
        for k in ("dice", "upcast", "roll_mod", "ongoing", "temp_hp"):
            if s.get(k) and k != "dice":
                assert sp[k], (s["name"], k)
    assert find("hold person DC 13")["name"] == "Hold Person"
    assert find("Fireball (3rd level)")["name"] == "Fireball"
    assert find("not a spell") is None


def test_book_is_served_to_the_sheet(api):
    camp = api.campaign()
    ch = api.character(camp["id"])
    page = api.c.get(f"/characters/{ch['id']}").get_data(as_text=True)
    assert '"Spirit Guardians"' in page and "window.SPELL_BOOK" in page
    assert api.get("/api/spell-book")["spells"][0]["name"]


# ---- damage -----------------------------------------------------------------------

def test_fireball_save_for_half_one_roll_for_everyone(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    # 8d6 all 6s = 48; Goblin 1 rolls a 1 on its Dex save (fails), Goblin 2 a 20 (saves)
    loaded.next(*[6] * 8, 1, 20)
    st = cast(t, "Ilse", 0, ["Goblin 1", "Goblin 2"])
    res = {r["name"]: r for r in st["cast"]["targets"]}
    assert res["Goblin 1"]["how"] == "failed" and res["Goblin 1"]["amount"] == 48
    assert who(st, "Goblin 1")["hp"] == 0 and who(st, "Goblin 1")["status"] == "defeated"
    assert res["Goblin 2"]["how"] == "saved" and res["Goblin 2"]["amount"] == 24 and who(st, "Goblin 2")["hp"] == 16
    assert st["cast"]["spent"] and st["cast"]["slot"] == 3
    ilse = t["api"].get(f"/api/characters/{t['wizard']['id']}")["character"]
    assert ilse["spell_slots"]["3"]["used"] == 1
    assert any(e["message"].startswith("Ilse casts Fireball with a level 3 slot: Goblin 1 failed the save") for e in st["log"])
    kinds = [r["kind"] for r in st["cast"]["rolls"]]
    assert kinds == ["damage", "save", "save"], "every roll goes to the dice tray"
    assert st["cast"]["rolls"][0]["result"]["applied"], "the tray won't offer to apply it a second time"


def test_upcasting_adds_dice_and_slots_run_out(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    loaded.rest = "min"
    st = cast(t, "Ilse", 0, ["Goblin 1"], slot=3)
    assert st["cast"]["rolls"][0]["expression"] == "8d6"
    # one level 3 slot left; then none
    cast(t, "Ilse", 0, ["Goblin 1"])
    err = cast(t, "Ilse", 0, ["Goblin 1"], expect=400)
    assert "no level 3 slots left" in err["error"]
    st = cast(t, "Ilse", 0, ["Goblin 1"], free=True)
    assert not st["cast"]["spent"], "the DM can cast it without a slot"
    # Magic Missile from a level 2 slot: 3d4+3 and 1d4+1 more
    st = cast(t, "Ilse", 2, ["Goblin 2"], slot=2)
    assert st["cast"]["rolls"][0]["expression"] == "3d4+3+1d4+1"
    assert st["cast"]["targets"][0]["how"] == "auto", "Magic Missile always hits"
    cast(t, "Ilse", 2, ["Goblin 2"], slot=0, expect=400)


def test_fire_bolt_rolls_to_hit_and_crits_double_dice(table, loaded):
    t = table
    loaded.next(20, 5, 5)  # natural 20, then 2d10 for the crit
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    r = st["cast"]["targets"][0]
    assert r["how"] == "crit" and r["amount"] == 10
    assert [x["kind"] for x in st["cast"]["rolls"]] == ["attack", "damage"]
    assert st["cast"]["rolls"][1]["expression"] == "2d10", "a crit doubles Fire Bolt's 1d10"
    loaded.next(1)
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    assert st["cast"]["targets"][0]["how"] == "miss" and who(st, "Goblin 1")["hp"] == 30
    loaded.next(9, 5)  # 9 + 7 (int 18 + prof 3) = 16 vs AC 13
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    assert st["cast"]["targets"][0]["how"] == "hit" and who(st, "Goblin 1")["hp"] == 25
    assert not st["cast"]["spent"], "cantrips use no slot"


def test_resistance_immunity_and_vulnerability(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    loaded.next(*[3] * 8, 1)  # Fireball 24, imp fails
    st = cast(t, "Ilse", 0, ["Imp"])
    assert st["cast"]["targets"][0]["amount"] == 0 and "immune fire" in st["cast"]["targets"][0]["text"]
    loaded.next(8, 1)  # Sacred Flame 1d8 = 8, radiant, imp fails its Dex save
    st = cast(t, "Bram", 7, ["Imp"])
    assert st["cast"]["targets"][0]["amount"] == 16 and who(st, "Imp")["hp"] == 24


def test_cantrip_save_does_nothing_on_a_success(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    loaded.next(8, 20)
    st = cast(t, "Bram", 7, ["Goblin 1"])
    assert st["cast"]["targets"][0]["how"] == "saved" and st["cast"]["targets"][0]["amount"] is None
    assert who(st, "Goblin 1")["hp"] == 40


def test_house_rule_on_harmful_save_spells_roll_against_ac(table, loaded):
    t = table  # roll_to_hit is on by default
    loaded.next(2)  # 2 + 6 = 8 vs AC 13: miss
    st = cast(t, "Ilse", 0, ["Goblin 1"])
    assert st["cast"]["lands"] == "attack" and st["cast"]["targets"][0]["how"] == "miss"


# ---- healing --------------------------------------------------------------------------

def test_cure_wounds_and_mass_healing_word(table, loaded):
    t = table
    api = t["api"]
    api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "damage", "amount": 20})
    api.post(f"/api/combatants/{t['by']['Ilse']['id']}/hp", {"op": "damage", "amount": 15})
    loaded.next(5)
    st = cast(t, "Bram", 0, ["Bram"])
    assert st["cast"]["targets"][0]["amount"] == 8 and who(st, "Bram")["hp"] == 18, "1d8 + Wisdom 3"
    loaded.next(4)
    st = cast(t, "Bram", 5, ["Bram", "Ilse"])
    assert who(st, "Bram")["hp"] == 25 and who(st, "Ilse")["hp"] == 14, "one roll heals everyone it reaches"
    assert st["cast"]["slot"] == 3
    loaded.rest = "max"
    st = cast(t, "Bram", 0, ["Ilse"], slot=2)
    assert st["cast"]["rolls"][0]["expression"] == "1d8+3+1d8"
    assert who(st, "Ilse")["hp"] == 22, "never over max"


def test_too_many_targets_and_notes_only(table):
    t = table
    err = cast(t, "Bram", 2, ["Bram", "Ilse"], expect=400)
    assert "at most 1 creature" in err["error"]
    err = cast(t, "Bram", 8, ["Goblin 1"], expect=400)
    assert "only notes" in err["error"]


# ---- buffs ----------------------------------------------------------------------------

def test_bless_adds_1d4_to_attacks_and_concentration_moves_on(table, loaded):
    t = table
    api = t["api"]
    st = cast(t, "Bram", 1, ["Bram", "Ilse"])
    blessed = eff(who(st, "Ilse"), "Blessed")
    assert blessed["roll_mod"] == "1d4" and blessed["rounds_left"] == 10 and blessed["source"]["conc"]
    assert eff(who(st, "Bram"), "Concentrating")["spell"] == "Bless"
    # Ilse's Fire Bolt attack now rolls d20 + 7 + 1d4
    loaded.next(10, 4, 1)  # d20 10, bless 4 -> 21; damage 1
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    assert st["cast"]["rolls"][0]["expression"] == "1d20+7+1d4" and st["cast"]["rolls"][0]["total"] == 21
    # the dice tray's attack button for a blessed hero adds it too
    roll = api.post("/api/rolls", {"check": {"type": "spell_attack", "combatant_id": t["by"]["Ilse"]["id"]}}, 201)["roll"]
    assert roll["expression"].endswith("+1d4") and "Blessed" in roll["label"]
    # a new concentration spell ends Bless on everyone
    st = cast(t, "Bram", 2, ["Ilse"])
    assert eff(who(st, "Ilse"), "Blessed") is None and eff(who(st, "Bram"), "Blessed") is None
    assert eff(who(st, "Ilse"), "Shield of Faith")["ac"] == 2 and who(st, "Ilse")["ac"] == 14
    assert any("loses concentration on Bless" in e["message"] for e in st["log"])


def test_concentration_save_when_hurt(table, loaded):
    t = table
    api = t["api"]
    cast(t, "Bram", 2, ["Ilse"])
    loaded.next(15)  # Con save 15 + 2 vs DC 10: keeps it
    st = api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "damage", "amount": 6})
    assert eff(who(st, "Ilse"), "Shield of Faith") and any("keeps concentrating" in e["message"] for e in st["log"])
    loaded.next(3)  # 3 + 2 vs DC 11 (22 damage): loses it
    st = api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "damage", "amount": 22})
    assert eff(who(st, "Ilse"), "Shield of Faith") is None and eff(who(st, "Bram"), "Concentrating") is None
    assert who(st, "Ilse")["ac"] == 12


def test_dropping_to_zero_and_removing_concentrating_end_it(table, loaded):
    t = table
    api = t["api"]
    cast(t, "Bram", 1, ["Ilse"])
    st = api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "damage", "amount": 99})
    assert eff(who(st, "Ilse"), "Blessed") is None and any("dropped to 0 HP" in e["message"] for e in st["log"])
    api.post(f"/api/combatants/{t['by']['Bram']['id']}/hp", {"op": "heal", "amount": 30})
    st = cast(t, "Bram", 1, ["Ilse"])
    mark = eff(who(st, "Bram"), "Concentrating")
    st = api.delete(f"/api/combatants/{t['by']['Bram']['id']}/conditions/{mark['id']}")
    assert eff(who(st, "Ilse"), "Blessed") is None


def test_aid_raises_max_hp_and_gives_it_back(table):
    t = table
    api = t["api"]
    st = cast(t, "Bram", 6, ["Ilse", "Bram"])
    ilse = who(st, "Ilse")
    assert ilse["max_hp"] == 27 and ilse["hp"] == 27
    st = api.delete(f"/api/combatants/{ilse['id']}/conditions/{eff(ilse, 'Aided')['id']}")
    assert who(st, "Ilse")["max_hp"] == 22 and who(st, "Ilse")["hp"] == 22
    sheet = api.get(f"/api/characters/{t['wizard']['id']}")["character"]
    assert sheet["max_hp"] == 22, "the sheet is back to normal too"


def test_false_life_temp_hp_and_shield_lasts_one_round(table, loaded):
    t = table
    api = t["api"]
    loaded.next(4)
    st = cast(t, "Ilse", 3, ["Ilse"])
    assert who(st, "Ilse")["temp_hp"] == 8
    st = cast(t, "Ilse", 7, ["Ilse"])
    assert who(st, "Ilse")["ac"] == 17
    api.post(f"/api/encounters/{t['eid']}/start")
    st = api.post(f"/api/encounters/{t['eid']}/set-turn", {"combatant_id": t["by"]["Goblin 1"]["id"]})
    while who(st, "Ilse")["id"] != st["encounter"]["current_id"]:
        st = api.post(f"/api/encounters/{t['eid']}/next")
    assert eff(who(st, "Ilse"), "Shield") is None and who(st, "Ilse")["ac"] == 12, "gone at the start of her next turn"


def test_heroism_gives_temp_hp_every_turn(table, loaded):
    t = table
    api = t["api"]
    cast(t, "Ilse", 6, ["Bram"])
    api.post(f"/api/encounters/{t['eid']}/start")
    st = api.post(f"/api/encounters/{t['eid']}/set-turn", {"combatant_id": t["by"]["Ilse"]["id"]})
    st = api.post(f"/api/encounters/{t['eid']}/next")
    while st["encounter"]["current_id"] != t["by"]["Bram"]["id"]:
        st = api.post(f"/api/encounters/{t['eid']}/next")
    assert who(st, "Bram")["temp_hp"] == 4, "Intelligence modifier at the start of his turn"
    assert any("Heroism: Bram gets 4 temp HP" in e["message"] for e in st["log"])


# ---- debuffs -----------------------------------------------------------------------------

def test_hold_person_paralyzes_auto_fails_dex_and_ends_on_a_save(table, loaded):
    t = table
    api = t["api"]
    settings(api, t["camp"], roll_to_hit=False)
    loaded.next(2)  # Wis save 2 + 1 vs DC 14
    st = cast(t, "Bram", 3, ["Goblin 1"])
    held = eff(who(st, "Goblin 1"), "Paralyzed")
    assert held["save"] == {"ability": "wis", "dc": 14} and held["source"]["spell"] == "Hold Person"
    # Fireball: a paralyzed creature fails Dex saves automatically, so no d20 for it
    loaded.next(*[1] * 8)
    st = cast(t, "Ilse", 0, ["Goblin 1"])
    assert st["cast"]["targets"][0]["how"] == "failed" and "auto-fail, Paralyzed" in st["cast"]["targets"][0]["text"]
    assert [r["kind"] for r in st["cast"]["rolls"]] == ["damage"]
    # attacks against it have advantage: two d20s
    settings(api, t["camp"], roll_to_hit=True)
    loaded.next(3, 15, 1)
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    assert st["cast"]["rolls"][0]["mode"] == "advantage" and st["cast"]["targets"][0]["how"] == "hit"
    # at the end of its turn it saves again: a 20 breaks free
    api.post(f"/api/encounters/{t['eid']}/start")
    api.post(f"/api/encounters/{t['eid']}/set-turn", {"combatant_id": t["by"]["Goblin 1"]["id"]})
    loaded.next(20)
    st = api.post(f"/api/encounters/{t['eid']}/next")
    assert eff(who(st, "Goblin 1"), "Paralyzed") is None
    assert any("Goblin 1 shakes off Paralyzed" in e["message"] for e in st["log"])
    assert eff(who(st, "Bram"), "Concentrating") is None, "nobody is held any more, so the spell is over"


def test_faerie_fire_gives_advantage_and_saves_stop_it(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    loaded.next(1, 20)  # Goblin 1 fails, Goblin 2 saves
    st = cast(t, "Ilse", 4, ["Goblin 1", "Goblin 2"])
    assert eff(who(st, "Goblin 1"), "Outlined")["adv"] == "attacked_adv"
    assert eff(who(st, "Goblin 2"), "Outlined") is None
    loaded.next(2, 18, 1)
    st = cast(t, "Ilse", 1, ["Goblin 1"])
    assert st["cast"]["rolls"][0]["mode"] == "advantage"


def test_moonbeam_burns_at_the_start_of_each_turn(table, loaded):
    t = table
    api = t["api"]
    settings(api, t["camp"], roll_to_hit=False)
    loaded.next(5, 5, 1)  # 2d10 = 10, Goblin 1 fails
    st = cast(t, "Ilse", 5, ["Goblin 1"])
    assert who(st, "Goblin 1")["hp"] == 30
    beam = eff(who(st, "Goblin 1"), "In the moonbeam")
    assert beam["ongoing"] == {"dice": "2d10", "kind": "damage", "type": "radiant", "save": "con", "dc": 15, "half": True}
    api.post(f"/api/encounters/{t['eid']}/start")
    api.post(f"/api/encounters/{t['eid']}/set-turn", {"combatant_id": t["by"]["Ilse"]["id"]})
    loaded.next(4, 4, 20)  # its turn: 8 radiant, saves for half
    st = api.post(f"/api/encounters/{t['eid']}/next")
    while st["encounter"]["current_id"] != t["by"]["Goblin 1"]["id"]:
        st = api.post(f"/api/encounters/{t['eid']}/next")
    assert who(st, "Goblin 1")["hp"] == 26
    assert any("Moonbeam: Goblin 1 takes 4 radiant damage (saved" in e["message"] for e in st["log"])


# ---- monsters casting -----------------------------------------------------------------------

def test_monster_casts_a_book_spell_by_name_with_its_own_dc(table, loaded):
    t = table
    settings(t["api"], t["camp"], roll_to_hit=False)
    loaded.next(1)
    st = cast(t, "Cult mage", {"name": "Hold person"}, ["Bram"])
    held = eff(who(st, "Bram"), "Paralyzed")
    assert held["save"]["dc"] == 13, "spell save DC 13 from its stat block"
    assert eff(who(st, "Cult mage"), "Concentrating")
    loaded.next(10, 5, 5, 5)  # Bram is paralyzed: advantage, 10 + 7 = 17 vs AC 14; 2d10 = 10
    st = cast(t, "Cult mage", {"name": "Fire bolt", "dice": "2d10", "effect": "damage", "hit": "attack", "attack_bonus": 7}, ["Bram"])
    assert st["cast"]["rolls"][0]["expression"] == "2d20kh1+7" and who(st, "Bram")["hp"] == 20
    st = cast(t, "Goblin 1", None, ["Bram"], book="Bane")
    assert st["cast"]["spell"] == "Bane"


def test_legacy_effect_rows_still_cast(table):
    t = table
    api = t["api"]
    ch = api.get(f"/api/characters/{t['cleric']['id']}")["character"]
    ch = api.set_char(ch, spells=ch["spells"] + [{"name": "Shield of Faith", "effect": "effect", "dice": "", "hit": "", "condition": "Shield of Faith", "rounds": 100, "ac": 2}])
    st = cast(t, "Bram", len(ch["spells"]) - 1, ["Bram"])
    assert who(st, "Bram")["ac"] == 16 and st["cast"]["kind"] == "buff"


def test_cast_is_idempotent_and_dm_only(table, app):
    t = table
    api = t["api"]
    body = {"caster_id": t["by"]["Bram"]["id"], "spell": 0, "targets": [t["by"]["Ilse"]["id"]], "op_id": "same-cast"}
    api.c.post(f"/api/encounters/{t['eid']}/cast", json=body)
    api.c.post(f"/api/encounters/{t['eid']}/cast", json=body)
    bram = api.get(f"/api/characters/{t['cleric']['id']}")["character"]
    assert bram["spell_slots"]["1"]["used"] == 1, "a double click casts once"
    from tests.test_dice_map_players import remote
    p = remote(app, "192.168.1.50")
    r = p.c.post(f"/api/encounters/{t['eid']}/cast", json=body)
    assert r.status_code in (401, 403)


# ---- players, the sheet, and ordinary rolls ---------------------------------------------------

def test_player_casts_in_a_fight_through_the_engine(table, app, loaded):
    t = table
    api = t["api"]
    from tests.test_dice_map_players import remote
    code = api.post(f"/api/campaigns/{t['camp']['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.61")
    p.post("/api/join", {"code": code, "name": "Jo", "character_id": t["cleric"]["id"]})
    api.post(f"/api/combatants/{t['by']['Ilse']['id']}/hp", {"op": "damage", "amount": 15})
    loaded.next(2)
    r = p.post("/api/play/cast", {"spell": 0, "targets": [t["wizard"]["id"]], "slot": 2})
    assert r["cast"]["slot"] == 2 and r["roll"]["expression"] == "1d8+3+1d8"
    ilse = api.get(f"/api/characters/{t['wizard']['id']}")["character"]
    assert ilse["current_hp"] == 7 + 2 + 3 + 8
    bram = api.get(f"/api/characters/{t['cleric']['id']}")["character"]
    assert bram["spell_slots"]["2"]["used"] == 1
    r = p.post("/api/play/cast", {"spell": 6, "targets": [t["wizard"]["id"], t["cleric"]["id"]]})  # Aid
    assert r["added"] == ["Ilse", "Bram"]
    st = api.get(f"/api/encounters/{t['eid']}")
    assert eff(who(st, "Ilse"), "Aided")["max_hp"] == 5 and who(st, "Ilse")["max_hp"] == 27
    p.post("/api/play/cast", {"spell": 3, "targets": [t["wizard"]["id"]]}, 400)  # Hold Person: the DM's call


def test_aid_outside_a_fight_and_taking_it_off_the_sheet(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Sol", max_hp=20)
    ch = api.set_char(ch, current_hp=20, spellcasting_ability="wis", spells=[book("Aid")])
    from tests.test_dice_map_players import remote
    from flask import current_app  # noqa: F401
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(api.c.application, "192.168.1.62")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": ch["id"]})
    r = p.post("/api/play/cast", {"spell": 0, "targets": [ch["id"]]})
    assert r["added"] == ["Sol"]
    ch = api.get(f"/api/characters/{ch['id']}")["character"]
    assert ch["max_hp"] == 25 and ch["current_hp"] == 25
    aided = [x for x in ch["conditions"] if x["name"] == "Aided"]
    assert aided and aided[0]["max_hp"] == 5
    ch = api.patch(f"/api/characters/{ch['id']}", {"changes": {"conditions": {"from": ch["conditions"], "to": []}}})["character"]
    assert ch["max_hp"] == 20 and ch["current_hp"] == 20


def test_sheet_ac_row_casts_like_a_buff_and_keeps_its_cooldown(table):
    t = table
    api = t["api"]
    api.post(f"/api/encounters/{t['eid']}/start")
    spec = {"name": "Sheild of faith", "effect": "buff", "condition": "Sheild of faith", "ac": 2, "cooldown": 3}
    st = cast(t, "Bram", spec, ["Ilse"])
    assert who(st, "Ilse")["ac"] == 14
    assert eff(who(st, "Bram"), "Sheild of faith recharging"), "the row's 3-turn cooldown starts"


def test_effects_change_ordinary_rolls(table):
    t = table
    api = t["api"]
    st = api.post(f"/api/combatants/{t['by']['Goblin 1']['id']}/conditions", {"name": "Poisoned"})
    roll = api.post("/api/rolls", {"check": {"type": "save", "key": "dex", "combatant_id": t["by"]["Goblin 1"]["id"]}}, 201)["roll"]
    assert roll["mode"] == "normal", "poison doesn't touch saves"
    cast(t, "Bram", 1, ["Ilse"])  # Bless
    roll = api.post("/api/rolls", {"check": {"type": "save", "key": "con", "character_id": t["wizard"]["id"]}}, 201)["roll"]
    assert roll["expression"].endswith("+1d4") and "Blessed" in roll["label"]
    api.post(f"/api/combatants/{t['by']['Ilse']['id']}/conditions", {"name": "Frightened"})
    roll = api.post("/api/rolls", {"check": {"type": "spell_attack", "character_id": t["wizard"]["id"]}}, 201)["roll"]
    assert roll["mode"] == "disadvantage" and "Frightened" in roll["label"]
    roll = api.post("/api/rolls", {"check": {"type": "spell_attack", "character_id": t["wizard"]["id"]}, "mode": "advantage"}, 201)["roll"]
    assert roll["mode"] == "normal", "advantage and disadvantage cancel out"
