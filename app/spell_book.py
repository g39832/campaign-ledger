"""Ready-made spells for the character sheet's "Add from spell list" and for monsters
that name a spell ("Fireball", "Hold Person DC 13"). Each entry is a spell row as the
sheet stores it (see rules.spell_info): what it does (damage / heal / buff / debuff),
its dice ("mod" = the caster's spellcasting modifier), how it lands (spell attack or a
save), what it leaves on the target (a condition, AC, a bonus to rolls, advantage,
damage or healing every turn, a save each turn to end it) and for how many rounds
(1 minute = 10). Short rules summaries only; read the full spell in your book.
"""
from .rules import spell_info

ATTRIBUTION = ("Spell summaries based on the System Reference Document 5.1 by Wizards of the Coast LLC, "
               "licensed under CC BY 4.0.")


def S(name, level, kind, notes, **kw):
    row = {"name": name, "level": level, "effect": kind, "notes": notes, "dice": "", "hit": "", "condition": "",
           "rounds": None, "ac": None}
    row.update(kw)
    return row


SPELLS = [
    # ---- damage: cantrips
    S("Acid Splash", 0, "damage", "1 action · 60 ft · one or two creatures next to each other", dice="1d6", hit="dex", damage_type="acid"),
    S("Chill Touch", 0, "damage", "1 action · 120 ft · the target can't regain HP until your next turn", dice="1d8", hit="attack",
      damage_type="necrotic", condition="Can't heal", rounds=1),
    S("Eldritch Blast", 0, "damage", "1 action · 120 ft · more beams at higher levels", dice="1d10", hit="attack", damage_type="force"),
    S("Fire Bolt", 0, "damage", "1 action · 120 ft", dice="1d10", hit="attack", damage_type="fire"),
    S("Poison Spray", 0, "damage", "1 action · 10 ft", dice="1d12", hit="con", damage_type="poison"),
    S("Produce Flame", 0, "damage", "1 action · 30 ft thrown · also sheds light", dice="1d8", hit="attack", damage_type="fire"),
    S("Ray of Frost", 0, "damage", "1 action · 60 ft · speed −10 ft until your next turn", dice="1d8", hit="attack",
      damage_type="cold", condition="Slowed (−10 ft)", rounds=1),
    S("Sacred Flame", 0, "damage", "1 action · 60 ft · no benefit from cover", dice="1d8", hit="dex", damage_type="radiant"),
    S("Shocking Grasp", 0, "damage", "1 action · touch · advantage against metal armor · no reactions until its next turn",
      dice="1d8", hit="attack", damage_type="lightning", condition="No reactions", rounds=1),
    S("Vicious Mockery", 0, "damage", "1 action · 60 ft · disadvantage on its next attack", dice="1d4", hit="wis",
      damage_type="psychic", condition="Mocked", adv="attacks_dis", rounds=1),
    # ---- damage: levelled
    S("Burning Hands", 1, "damage", "1 action · 15 ft cone · half on a save", dice="3d6", hit="dex", damage_type="fire", upcast="1d6"),
    S("Guiding Bolt", 1, "damage", "1 action · 120 ft · the next attack on the target has advantage", dice="4d6", hit="attack",
      damage_type="radiant", upcast="1d6", condition="Glittering", adv="attacked_adv", rounds=1),
    S("Hellish Rebuke", 1, "damage", "1 reaction · 60 ft · when you're damaged · half on a save", dice="2d10", hit="dex",
      damage_type="fire", upcast="1d10"),
    S("Inflict Wounds", 1, "damage", "1 action · touch", dice="3d10", hit="attack", damage_type="necrotic", upcast="1d10", targets=1),
    S("Magic Missile", 1, "damage", "1 action · 120 ft · three darts that always hit, split them as you like", dice="3d4+3",
      damage_type="force", upcast="1d4+1"),
    S("Ray of Sickness", 1, "damage", "1 action · 60 ft · poisoned until the end of your next turn on a hit", dice="2d8", hit="attack",
      damage_type="poison", upcast="1d8", condition="Poisoned", rounds=1),
    S("Thunderwave", 1, "damage", "1 action · 15 ft cube · pushed 10 ft on a fail, half on a save", dice="2d8", hit="con",
      damage_type="thunder", upcast="1d8"),
    S("Acid Arrow", 2, "damage", "1 action · 90 ft · 2d4 more acid at its next turn", dice="4d4", hit="attack", damage_type="acid",
      upcast="1d4", condition="Acid burns", ongoing="2d4", ongoing_type="acid", rounds=1),
    S("Flaming Sphere", 2, "damage", "1 action · 60 ft · 5 ft radius · concentration · ram it again as a bonus action", dice="2d6",
      hit="dex", damage_type="fire", upcast="1d6", concentration=True),
    S("Heat Metal", 2, "damage", "1 action · 60 ft · concentration · 2d8 again each turn (bonus action) · drops it or has disadvantage",
      dice="2d8", damage_type="fire", upcast="1d8", concentration=True, condition="Searing metal", adv="attacks_dis",
      ongoing="2d8", ongoing_type="fire", rounds=10),
    S("Moonbeam", 2, "damage", "1 action · 120 ft · 5 ft radius · concentration · Con save each turn it starts there, half on a save",
      dice="2d10", hit="con", damage_type="radiant", upcast="1d10", concentration=True, condition="In the moonbeam",
      ongoing="2d10", ongoing_type="radiant", ongoing_save=True, rounds=10),
    S("Scorching Ray", 2, "damage", "1 action · 120 ft · three rays, each rolls to hit (cast it once per ray)", dice="2d6", hit="attack",
      damage_type="fire"),
    S("Shatter", 2, "damage", "1 action · 60 ft · 10 ft sphere · half on a save", dice="3d8", hit="con", damage_type="thunder", upcast="1d8"),
    S("Spiritual Weapon", 2, "damage", "1 bonus action · 60 ft · lasts 1 minute, attack again as a bonus action", dice="1d8+mod",
      hit="attack", damage_type="force"),
    S("Call Lightning", 3, "damage", "1 action · 120 ft · 5 ft radius · concentration · call a new bolt each turn", dice="3d10",
      hit="dex", damage_type="lightning", upcast="1d10", concentration=True),
    S("Fireball", 3, "damage", "1 action · 150 ft · 20 ft sphere · half on a save", dice="8d6", hit="dex", damage_type="fire", upcast="1d6"),
    S("Lightning Bolt", 3, "damage", "1 action · 100 ft line · half on a save", dice="8d6", hit="dex", damage_type="lightning", upcast="1d6"),
    S("Spirit Guardians", 3, "damage", "1 action · 15 ft emanation · concentration · Wis save each turn, half on a save · speed halved",
      dice="3d8", hit="wis", damage_type="radiant", upcast="1d8", concentration=True, condition="Spirit guardians",
      ongoing="3d8", ongoing_type="radiant", ongoing_save=True, rounds=100),
    S("Vampiric Touch", 3, "damage", "1 action · touch · concentration · you heal half the damage", dice="3d6", hit="attack",
      damage_type="necrotic", upcast="1d6", concentration=True),
    S("Blight", 4, "damage", "1 action · 30 ft · half on a save · plants take more", dice="8d8", hit="con", damage_type="necrotic", upcast="1d8"),
    S("Ice Storm", 4, "damage", "1 action · 300 ft · 20 ft radius · 2d8 bludgeoning + 4d6 cold · half on a save", dice="2d8+4d6",
      hit="dex", damage_type="cold", upcast="1d8"),
    S("Cone of Cold", 5, "damage", "1 action · 60 ft cone · half on a save", dice="8d8", hit="con", damage_type="cold", upcast="1d8"),
    S("Flame Strike", 5, "damage", "1 action · 60 ft · 10 ft radius · 4d6 fire + 4d6 radiant · half on a save", dice="8d6",
      hit="dex", damage_type="fire", upcast="1d6"),
    S("Chain Lightning", 6, "damage", "1 action · 150 ft · the target and up to three more · half on a save", dice="10d8", hit="dex",
      damage_type="lightning", targets=4),
    S("Disintegrate", 6, "damage", "1 action · 60 ft · nothing on a save · turns to dust at 0 HP", dice="10d6+40", hit="dex",
      damage_type="force", upcast="3d6", save_half=False),
    # ---- healing
    S("Cure Wounds", 1, "heal", "1 action · touch", dice="1d8+mod", upcast="1d8", targets=1),
    S("Healing Word", 1, "heal", "1 bonus action · 60 ft", dice="1d4+mod", upcast="1d4", targets=1),
    S("Prayer of Healing", 2, "heal", "10 minutes · 30 ft · up to six creatures · not in combat", dice="2d8+mod", upcast="1d8", targets=6),
    S("Aura of Vitality", 3, "heal", "1 action · 30 ft emanation · concentration · heal 2d6 again each turn (bonus action)",
      dice="2d6", concentration=True, condition="Aura of vitality", ongoing="2d6", ongoing_kind="heal", rounds=10),
    S("Mass Healing Word", 3, "heal", "1 bonus action · 60 ft · up to six creatures", dice="1d4+mod", upcast="1d4", targets=6),
    S("Mass Cure Wounds", 5, "heal", "1 action · 60 ft · up to six creatures in a 30 ft sphere", dice="3d8+mod", upcast="1d8", targets=6),
    S("Heal", 6, "heal", "1 action · 60 ft · also ends blindness, deafness and diseases", dice="70", upcast="10"),
    S("Regenerate", 7, "heal", "1 minute · touch · 1 HP back at the start of each of its turns for an hour", dice="4d8+15",
      condition="Regenerating", ongoing="1", ongoing_kind="heal", rounds=600),
    # ---- buffs
    S("Bless", 1, "buff", "1 action · 30 ft · up to three creatures · concentration · add 1d4 to attacks and saves",
      condition="Blessed", roll_mod="1d4", rounds=10, concentration=True, targets=3),
    S("Divine Favor", 1, "buff", "1 bonus action · self · concentration · weapon hits deal 1d4 radiant more",
      condition="Divine favor", dmg_mod="1d4", rounds=10, concentration=True, targets=1),
    S("False Life", 1, "buff", "1 action · self · 1 hour", temp_hp="1d4+4", upcast="5", targets=1),
    S("Heroism", 1, "buff", "1 action · touch · concentration · can't be frightened · temp HP equal to your modifier each turn",
      condition="Heroic", ongoing="mod", ongoing_kind="temp", rounds=10, concentration=True),
    S("Mage Armor", 1, "buff", "1 action · touch · 8 hours · AC becomes 13 + Dex (about +3 over no armor)", condition="Mage armor",
      ac=3, rounds=4800),
    S("Sanctuary", 1, "buff", "1 bonus action · 30 ft · attackers must make a Wis save or pick a new target", condition="Sanctuary", rounds=10),
    S("Shield", 1, "buff", "1 reaction · self · +5 AC until the start of your next turn · no damage from Magic Missile",
      condition="Shield", ac=5, rounds=1, targets=1),
    S("Shield of Faith", 1, "buff", "1 bonus action · 60 ft · concentration, up to 10 minutes", condition="Shield of Faith", ac=2,
      rounds=100, concentration=True, targets=1),
    S("Aid", 2, "buff", "1 action · 30 ft · up to three creatures · 8 hours · +5 max HP and current HP", condition="Aided",
      max_hp=5, rounds=4800, targets=3),
    S("Blur", 2, "buff", "1 action · self · concentration · attacks against you have disadvantage", condition="Blurred",
      adv="attacked_dis", rounds=10, concentration=True, targets=1),
    S("Invisibility", 2, "buff", "1 action · touch · concentration · 1 hour · ends when it attacks or casts", condition="Invisible",
      rounds=600, concentration=True),
    S("Warding Bond", 2, "buff", "1 action · touch · 1 hour · +1 AC and saves, resistance · you take the same damage",
      condition="Warding bond", ac=1, rounds=600),
    S("Haste", 3, "buff", "1 action · 30 ft · concentration · double speed, advantage on Dex saves, one extra action",
      condition="Hasted", ac=2, rounds=10, concentration=True, targets=1),
    S("Greater Invisibility", 4, "buff", "1 action · touch · concentration · stays invisible while attacking", condition="Invisible",
      rounds=10, concentration=True, targets=1),
    S("Guidance", 0, "buff", "1 action · touch · concentration · add 1d4 to one ability check", condition="Guidance", rounds=10,
      concentration=True, targets=1),
    S("Resistance", 0, "buff", "1 action · touch · concentration · add 1d4 to one saving throw", condition="Resistance", rounds=10,
      concentration=True, targets=1),
    # ---- changing the battlefield (homebrew, from Moni Easter's sheet): aim it on the battle map
    S("Mend Earth: Raise Rocks", 0, "buff", "1 action · 20 ft square, range 30 · solid rock rises from the ground and blocks movement (not where anyone stands)",
      terrain="rock", area="20 ft square, range 30"),
    S("Mend Earth: Mend", 0, "buff", "1 action · 20 ft square, range 30 · rock, rubble, pits and broken ground go back to plain earth",
      terrain="mend", area="20 ft square, range 30"),
    # ---- debuffs
    S("Bane", 1, "debuff", "1 action · 30 ft · up to three creatures · concentration · subtract 1d4 from attacks and saves",
      hit="cha", condition="Baned", roll_mod="-1d4", rounds=10, concentration=True, targets=3),
    S("Charm Person", 1, "debuff", "1 action · 30 ft · 1 hour · advantage on the save if you're fighting it", hit="wis",
      condition="Charmed", rounds=600),
    S("Command", 1, "debuff", "1 action · 60 ft · one-word command, e.g. grovel (prone), flee, halt", hit="wis", condition="Prone", rounds=1),
    S("Entangle", 1, "debuff", "1 action · 90 ft · 20 ft square · concentration · difficult terrain · Str save each turn to break free",
      hit="str", condition="Restrained", rounds=10, concentration=True, repeat_save=True),
    S("Faerie Fire", 1, "debuff", "1 action · 60 ft · 20 ft cube · concentration · attacks against them have advantage", hit="dex",
      condition="Outlined", adv="attacked_adv", rounds=10, concentration=True),
    S("Hideous Laughter", 1, "debuff", "1 action · 30 ft · concentration · falls prone laughing, incapacitated · Wis save each turn",
      hit="wis", condition="Incapacitated", rounds=10, concentration=True, repeat_save=True, targets=1),
    S("Sleep", 1, "debuff", "1 action · 90 ft · 20 ft radius · roll 5d8: creatures with that many HP or fewer fall asleep, lowest first",
      condition="Unconscious", rounds=10),
    S("Blindness/Deafness", 2, "debuff", "1 action · 30 ft · 1 minute · Con save at the end of each of its turns", hit="con",
      condition="Blinded", rounds=10, repeat_save=True, targets=1),
    S("Hold Person", 2, "debuff", "1 action · 60 ft · humanoid · concentration · Wis save at the end of each of its turns", hit="wis",
      condition="Paralyzed", rounds=10, concentration=True, repeat_save=True, targets=1),
    S("Web", 2, "debuff", "1 action · 60 ft · 20 ft cube · concentration · 1 hour · difficult terrain", hit="dex",
      condition="Restrained", rounds=600, concentration=True),
    S("Bestow Curse", 3, "debuff", "1 action · touch · concentration · disadvantage on attacks (or another curse)", hit="wis",
      condition="Cursed", adv="attacks_dis", rounds=10, concentration=True, targets=1),
    S("Fear", 3, "debuff", "1 action · 30 ft cone · concentration · must drop what it holds and run · Wis save when out of sight",
      hit="wis", condition="Frightened", rounds=10, concentration=True),
    S("Hypnotic Pattern", 3, "debuff", "1 action · 120 ft · 30 ft cube · concentration · charmed and incapacitated, speed 0",
      hit="wis", condition="Incapacitated", rounds=10, concentration=True),
    S("Slow", 3, "debuff", "1 action · 120 ft · 40 ft cube · up to six · concentration · −2 AC and Dex saves, half speed · Wis save each turn",
      hit="wis", condition="Slowed", ac=-2, rounds=10, concentration=True, repeat_save=True, targets=6),
    S("Banishment", 4, "debuff", "1 action · 60 ft · concentration · sent to a harmless plane for up to a minute", hit="cha",
      condition="Banished", rounds=10, concentration=True, targets=1),
    S("Hold Monster", 5, "debuff", "1 action · 90 ft · any creature · concentration · Wis save at the end of each of its turns",
      hit="wis", condition="Paralyzed", rounds=10, concentration=True, repeat_save=True, targets=1),
]

BY_NAME = {s["name"].lower(): s for s in SPELLS}


def find(name):
    """The book spell a name means: 'Fireball', 'fireball (3rd level)', 'Hold person DC 13'."""
    key = str(name or "").strip().lower()
    if key in BY_NAME:
        return BY_NAME[key]
    for n in sorted(BY_NAME, key=len, reverse=True):
        if key.startswith(n + " ") or key.startswith(n + ":") or key.startswith(n + "("):
            return BY_NAME[n]
    return None


def book():
    """What the browser gets: the rows plus a short summary of what each one does."""
    return {"attribution": ATTRIBUTION, "spells": SPELLS}


def _check():
    for s in SPELLS:
        sp = spell_info(s)
        assert sp["kind"] == s["effect"], s["name"]


_check()
