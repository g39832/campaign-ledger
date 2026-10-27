"""D&D 5e rules helpers. Kept free of Flask/DB so they are easy to test.

The character sheet mirrors these formulas in static/js/rules.js for instant
feedback while typing; tests cover this Python version.
"""
import random
import re

ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]
ABILITY_NAMES = {
    "str": "Strength", "dex": "Dexterity", "con": "Constitution",
    "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma",
}

SKILLS = [
    ("acrobatics", "Acrobatics", "dex"),
    ("animal_handling", "Animal Handling", "wis"),
    ("arcana", "Arcana", "int"),
    ("athletics", "Athletics", "str"),
    ("deception", "Deception", "cha"),
    ("history", "History", "int"),
    ("insight", "Insight", "wis"),
    ("intimidation", "Intimidation", "cha"),
    ("investigation", "Investigation", "int"),
    ("medicine", "Medicine", "wis"),
    ("nature", "Nature", "int"),
    ("perception", "Perception", "wis"),
    ("performance", "Performance", "cha"),
    ("persuasion", "Persuasion", "cha"),
    ("religion", "Religion", "int"),
    ("sleight_of_hand", "Sleight of Hand", "dex"),
    ("stealth", "Stealth", "dex"),
    ("survival", "Survival", "wis"),
]
SKILL_KEYS = {s[0] for s in SKILLS}

CONDITIONS = [
    "Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated",
    "Invisible", "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained",
    "Stunned", "Unconscious",
]

ALIGNMENTS = [
    "Lawful Good", "Neutral Good", "Chaotic Good",
    "Lawful Neutral", "True Neutral", "Chaotic Neutral",
    "Lawful Evil", "Neutral Evil", "Chaotic Evil",
]

STATUSES = ["ok", "unconscious", "stable", "defeated", "dead", "fled", "incapacitated"]

DEFAULT_CAMPAIGN_SETTINGS = {
    "morality": {
        "scale": 100,          # scores run from -scale to +scale, 0 is neutral
        "law_threshold": 34,   # law >= +t is Lawful, <= -t is Chaotic
        "good_threshold": 34,  # good >= +t is Good, <= -t is Evil
    },
    "combat": {
        "temp_hp_stacking": False,   # RAW: temp HP doesn't stack, keep the higher
        "tie_break": "modifier",     # modifier | pc_first | enemy_first | manual
        "auto_sort": True,
        "skip_statuses": ["dead", "defeated", "fled"],
        "roll_to_hit": True,
        "auto_concentration": True,
        "spell_slots": False,  # house rule: no spell slots; spells are used like attacks and only have their cooldown  # a concentrating caster who takes damage rolls the Constitution save automatically
        "ally_death_save_bonus": 2,  # house rule: a downed hero with an ally standing next to them adds this to death saves  # every attack and harmful spell rolls d20 + bonus against the target's AC (house rule; off = saves)
    },
    "players": {
        "edit_hp": False,     # players may apply damage/healing/temp HP to their own character (the DM's call)
        "spend_slots": True,  # players may spend and regain their own spell slots
        "hit_dice": True,     # players may spend hit dice (short rest healing)
        "cast_spells": True,  # players may cast their healing and buff spells on the party
    },
}


def merged_settings(stored):
    """Campaign settings with defaults filled in for any missing keys."""
    out = {}
    for section, defaults in DEFAULT_CAMPAIGN_SETTINGS.items():
        out[section] = dict(defaults)
        out[section].update((stored or {}).get(section, {}) or {})
    return out


def ability_mod(score):
    if score is None:
        return 0
    return (int(score) - 10) // 2


def proficiency_bonus(level, override=None):
    if override is not None:
        return override
    level = max(1, min(20, int(level or 1)))
    return 2 + (level - 1) // 4


def derived(char):
    """Computed values for a character dict (decoded JSON fields)."""
    abilities = {a: (char.get("abilities") or {}).get(a, 10) for a in ABILITIES}
    mods = {a: ability_mod(abilities[a]) for a in ABILITIES}
    prof = proficiency_bonus(char.get("level"), char.get("prof_override"))
    save_profs = set(char.get("save_profs") or [])
    save_bonus = char.get("save_bonus") or {}
    saves = {
        a: mods[a] + (prof if a in save_profs else 0) + int(save_bonus.get(a) or 0)
        for a in ABILITIES
    }
    skill_profs = char.get("skill_profs") or {}
    skill_bonus = char.get("skill_bonus") or {}
    skill_set = char.get("skill_set") or {}
    skills = {}
    for key, _label, ab in SKILLS:
        level = int(skill_profs.get(key) or 0)  # 0 none, 1 proficient, 2 expertise
        skills[key] = mods[ab] + prof * level + int(skill_bonus.get(key) or 0)
        try:
            if skill_set.get(key) not in (None, ""):
                skills[key] = int(skill_set[key])  # typed in by hand
        except (TypeError, ValueError):
            pass
    if char.get("initiative_override") is not None:
        initiative = char["initiative_override"]
    else:
        initiative = mods["dex"] + int(char.get("initiative_bonus") or 0)
    sa = char.get("spellcasting_ability") or ""
    spell = None
    if sa in ABILITIES:
        spell = {"dc": 8 + prof + mods[sa], "attack": prof + mods[sa], "ability": sa}
    return {
        "mods": mods,
        "prof": prof,
        "saves": saves,
        "skills": skills,
        "initiative": initiative,
        "passive_perception": 10 + skills["perception"],
        "passive_insight": 10 + skills["insight"],
        "passive_investigation": 10 + skills["investigation"],
        "spell": spell,
    }


# ---- HP ---------------------------------------------------------------------

def apply_damage(hp, temp, amount):
    """Damage drains temporary HP first, then current HP (floored at 0).
    Returns (hp, temp, absorbed_by_temp, overflow_below_zero)."""
    amount = max(0, int(amount))
    absorbed = min(temp, amount)
    temp -= absorbed
    rest = amount - absorbed
    overflow = max(0, rest - hp)
    hp = max(0, hp - rest)
    return hp, temp, absorbed, overflow


def apply_heal(hp, max_hp, amount):
    amount = max(0, int(amount))
    if max_hp > 0:
        return min(max_hp, hp + amount)
    return hp + amount


def apply_temp(temp, amount, stacking=False):
    amount = max(0, int(amount))
    return temp + amount if stacking else max(temp, amount)


# ---- Initiative -------------------------------------------------------------

def roll_d20(rng=random):
    return rng.randint(1, 20)


def initiative_sort_key(c, tie_break):
    roll = c["init_roll"]
    primary = -roll if roll is not None else float("inf")
    if tie_break == "modifier":
        tb = -(c.get("init_mod") or 0)
    elif tie_break == "pc_first":
        tb = 0 if c["kind"] in ("pc", "npc") else 1
    elif tie_break == "enemy_first":
        tb = 0 if c["kind"] == "enemy" else 1
    else:
        tb = 0
    return (primary, tb, c["sort_order"], c["id"])


# ---- Morality ---------------------------------------------------------------

def axis_label(score, threshold, positive, negative):
    if score >= threshold:
        return positive
    if score <= -threshold:
        return negative
    return "Neutral"


def alignment_for(law, good, cfg):
    l = axis_label(law, cfg["law_threshold"], "Lawful", "Chaotic")
    g = axis_label(good, cfg["good_threshold"], "Good", "Evil")
    if l == "Neutral" and g == "Neutral":
        return "True Neutral"
    return f"{l} {g}"


def alignment_axes(alignment):
    """Map a named alignment to (law_sign, good_sign) in {-1, 0, 1}."""
    if not alignment:
        return None
    a = alignment.strip().lower()
    if a in ("true neutral", "neutral"):
        return (0, 0)
    parts = a.split()
    if len(parts) != 2:
        return None
    law = {"lawful": 1, "neutral": 0, "chaotic": -1}.get(parts[0])
    good = {"good": 1, "neutral": 0, "evil": -1}.get(parts[1])
    if law is None or good is None:
        return None
    return (law, good)


def morality_timeline(start_law, start_good, events, cfg):
    """Replay events in order. Scores are a plain running sum of the deltas;
    they are only clamped to the scale for plotting, so removing or editing an
    event always changes the totals by exactly that event's amount."""
    scale = cfg["scale"]
    law, good = start_law, start_good
    points = [{
        "event_id": None, "law": law, "good": good,
        "alignment": alignment_for(law, good, cfg),
    }]
    for ev in events:
        law += ev["law_delta"]
        good += ev["good_delta"]
        points.append({
            "event_id": ev["id"], "law": law, "good": good,
            "plot_law": max(-scale, min(scale, law)),
            "plot_good": max(-scale, min(scale, good)),
            "alignment": alignment_for(law, good, cfg),
        })
    points[0]["plot_law"] = max(-scale, min(scale, start_law))
    points[0]["plot_good"] = max(-scale, min(scale, start_good))
    return points


# ---- Rests ------------------------------------------------------------------

HIT_DICE = re.compile(r"(\d+)\s*d\s*(\d+)", re.I)


def parse_hit_dice(text):
    """'5d10' or '3d8 + 2d10' -> [(5, 10)] / [(3, 8), (2, 10)]."""
    return [(int(n), int(s)) for n, s in HIT_DICE.findall(text or "") if int(n) > 0 and int(s) in (6, 8, 10, 12)]


def long_rest_changes(char):
    """What a long rest restores (5e 2014): all HP, spent hit dice up to half
    the character's total (minimum one), all spell slots, one level of
    exhaustion, and death saves. Temporary HP ends. Conditions are left for the DM."""
    total_dice = sum(n for n, _ in parse_hit_dice(char.get("hit_dice")))
    regain = max(1, total_dice // 2) if total_dice else char.get("hit_dice_used", 0)
    slots = {k: dict(v, used=0) for k, v in (char.get("spell_slots") or {}).items()}
    changes = {
        "current_hp": char["max_hp"],
        "temp_hp": 0,
        "hit_dice_used": max(0, (char.get("hit_dice_used") or 0) - regain),
        "spell_slots": slots,
        "exhaustion": max(0, (char.get("exhaustion") or 0) - 1),
        "death_successes": 0,
        "death_failures": 0,
    }
    if char.get("status") in ("unconscious", "stable", "incapacitated"):
        changes["status"] = "ok"
    return changes


# ---- Saints & Sinners -------------------------------------------------------
# A simple -100..+100 reputation score per character, adjusted one point at a time.

SAINTS_SINNERS_MIN, SAINTS_SINNERS_MAX = -100, 100

SAINTS_SINNERS_LEVELS = [
    (-100, -76, "Absolute Sinner",
     "A merciless individual known for cruelty, destruction, and having little regard for innocent life."),
    (-75, -51, "Notorious Villain",
     "A feared individual whose selfish or brutal actions have earned them a dangerous reputation."),
    (-50, -26, "Corrupted",
     "Someone who frequently puts personal gain above the well-being of others."),
    (-25, -1, "Morally Questionable",
     "Someone whose choices are often selfish or questionable, but who has not fully embraced evil."),
    (0, 0, "Unproven",
     "Someone whose moral reputation has not yet been established."),
    (1, 25, "Virtuous",
     "Someone who generally acts with fairness, compassion, and integrity."),
    (26, 50, "Hero",
     "Someone who regularly stands up for others and takes meaningful risks to do what is right."),
    (51, 75, "Saint",
     "Someone known for extraordinary kindness, sacrifice, and dedication to helping others."),
    (76, 100, "Paragon of Good",
     "A legendary example of compassion and selflessness whose actions inspire others."),
]


# What each level means at the table: pros and cons (from the DM's table), suggested
# roll modifiers (applied by the DM, not automatically), story examples, and
# table rolls the DM can click to roll in the dice tray.
SAINTS_SINNERS_DETAILS = {
    "Absolute Sinner": {
        "pros": ["Feared by enemies", "Ruthless criminals may respect you", "Intimidation is easier"],
        "cons": ["Authorities hunt you", "Civilians distrust you", "Companions may abandon you"],
        "modifiers": ["+5 to Intimidation checks", "−5 to Persuasion checks with ordinary people"],
        "examples": [
            "Wanted posters with the party's faces hang in every town square, and the guards attack on sight.",
            "A crime lord offers the party a seat at his table instead of a fight, because crossing you is bad for business.",
            "A frightened companion slips away in the night and leaves a note behind.",
        ],
        "rolls": [
            {"label": "Enemy morale: do they flee? (10 or less: they run)", "expression": "1d20"},
            {"label": "Bounty hunters this session? (1–3: they find you)", "expression": "1d6"},
            {"label": "Companion loyalty after a cruel act (8 or less: they leave)", "expression": "1d20"},
        ],
    },
    "Notorious Villain": {
        "pros": ["Criminal factions may offer deals", "Threats carry weight", "Darker quest options open up"],
        "cons": ["Higher scrutiny from law enforcement", "Merchants may refuse service", "Bounties become more likely"],
        "modifiers": ["+3 to Intimidation checks", "−3 to Persuasion checks with honest people"],
        "examples": [
            "The thieves' guild sends a messenger with a job and a fat purse.",
            "A shopkeeper slams the shutters closed the moment the party walks up.",
            "A captain of the watch starts asking questions about the party around town.",
        ],
        "rolls": [
            {"label": "Will this merchant serve you? (1–2: they refuse)", "expression": "1d6"},
            {"label": "Criminal job offer (12 or more: a faction reaches out)", "expression": "1d20"},
            {"label": "Is a bounty posted? (1: a hunter is on your trail)", "expression": "1d6"},
        ],
    },
    "Corrupted": {
        "pros": ["Easier access to shady contacts", "Fewer qualms about morally questionable solutions", "Ruthless allies may approve"],
        "cons": ["Honest NPCs become wary", "Trustworthy allies may question your motives", "Some quests become harder"],
        "modifiers": ["+2 to Intimidation and Deception checks", "−2 to Persuasion checks with honest NPCs"],
        "examples": [
            "You know a fence who can move the stolen goods, no questions asked.",
            "The temple's priest asks the party to leave before the evening service.",
            "A loyal ally pulls one of you aside and asks what's really going on.",
        ],
        "rolls": [
            {"label": "Know a shady contact for this? (10 or more: yes)", "expression": "1d20"},
            {"label": "An ally doubts you (1: they confront the party)", "expression": "1d6"},
        ],
    },
    "Morally Questionable": {
        "pros": ["Flexibility to negotiate with either side", "Fewer expectations", "Pragmatic choices remain available"],
        "cons": ["People may hesitate to trust you", "Your reputation can shift quickly", "Neither side fully embraces you"],
        "modifiers": ["+1 to Deception checks", "−1 to Persuasion checks when asking for trust"],
        "examples": [
            "Both the bandits and the town council are willing to hear the party out.",
            "A farmer counts their coins twice after the party pays.",
            "A rumour spreads that the party took a bribe, and it might even be true.",
        ],
        "rolls": [
            {"label": "Does this NPC trust you? (10 or more: yes)", "expression": "1d20"},
            {"label": "Rumours about the party (1: a bad one · 6: a good one)", "expression": "1d6"},
        ],
    },
    "Unproven": {
        "pros": ["No established reputation", "A clean slate with most groups", "Maximum flexibility"],
        "cons": ["No reputation-based favors", "People judge you by your actions", "You lack established allies"],
        "modifiers": ["No bonuses or penalties yet"],
        "examples": [
            "Nobody in town knows the party's names, so the first few choices will shape everything.",
            "The innkeeper is polite but asks for payment up front.",
        ],
        "rolls": [
            {"label": "First impression (11 or more: friendly · 10 or less: wary)", "expression": "1d20"},
        ],
    },
    "Virtuous": {
        "pros": ["Civilians are more welcoming", "Honest merchants may offer small favors", "Charitable groups are receptive"],
        "cons": ["Criminals may see you as an obstacle", "People may expect you to help", "Refusing requests can disappoint NPCs"],
        "modifiers": ["+1 to Persuasion checks with ordinary people"],
        "examples": [
            "The baker slips the party a fresh loaf for the road.",
            "A pickpocket gang marks the party as do-gooders worth robbing.",
            "A villager asks for help finding a lost child and looks crushed if you say no.",
        ],
        "rolls": [
            {"label": "Small favour from a merchant (5–6: a discount or gift)", "expression": "1d6"},
            {"label": "Do criminals target you? (1: they mark the party)", "expression": "1d6"},
        ],
    },
    "Hero": {
        "pros": ["Better cooperation from communities", "Access to heroic quests", "Possible discounts, shelter, or local support"],
        "cons": ["Enemies may target you to damage your reputation", "People expect you to intervene", "Mistakes attract attention"],
        "modifiers": ["+2 to Persuasion checks", "10% off at friendly shops"],
        "examples": [
            "The village offers the party free rooms and a hot meal after the rescue.",
            "A rival spreads lies to turn the town against the party.",
            "When trouble starts in the market, everyone turns to look at you.",
        ],
        "rolls": [
            {"label": "Local support: free shelter or supplies (10 or more: yes)", "expression": "1d20"},
            {"label": "A rival schemes against you (1–2: a smear campaign starts)", "expression": "1d6"},
        ],
    },
    "Saint": {
        "pros": ["Strong community support", "Influential allies may offer help", "Access to sanctuaries and special missions"],
        "cons": ["Greater scrutiny", "Enemies may exploit your compassion", "Morally gray decisions can damage your standing"],
        "modifiers": ["+3 to Persuasion checks", "Temples heal the party for free"],
        "examples": [
            "A high priest grants the party sanctuary inside the cathedral walls.",
            "A con artist fakes a sob story, knowing the party can't refuse.",
            "One small lie gets back to the temple, and whispers start.",
        ],
        "rolls": [
            {"label": "An influential ally offers help (14 or more: yes)", "expression": "1d20"},
            {"label": "Someone exploits your kindness (1–2: it's a trick)", "expression": "1d6"},
        ],
    },
    "Paragon of Good": {
        "pros": ["Legendary reputation", "Widespread support", "Exceptional opportunities to inspire, unite, or rally allies"],
        "cons": ["Major enemies take notice", "Expectations become enormous", "Compromise may alienate supporters"],
        "modifiers": ["+5 to Persuasion checks", "Once per day, rally the party: each ally gains 1d6 temporary hit points"],
        "examples": [
            "Bards sing of the party, and strangers offer to join the cause.",
            "The lich-king sends assassins specifically for the party.",
            "Agreeing to a truce with the orcs costs the party half its supporters.",
        ],
        "rolls": [
            {"label": "Rally the party: temporary hit points for each ally", "expression": "1d6"},
            {"label": "A major enemy takes notice (1–3: they send someone)", "expression": "1d6"},
            {"label": "Inspire: bonus to an ally's next saving throw", "expression": "1d4"},
        ],
    },
}


def saints_sinners_level(score):
    """Title and description for a score (clamped to -100..+100)."""
    score = max(SAINTS_SINNERS_MIN, min(SAINTS_SINNERS_MAX, int(score)))
    for lo, hi, title, description in SAINTS_SINNERS_LEVELS:
        if lo <= score <= hi:
            side = "saint" if score > 0 else "sinner" if score < 0 else "neutral"
            return {"score": score, "title": title, "description": description, "side": side,
                    "range": [lo, hi], **SAINTS_SINNERS_DETAILS[title]}
    raise ValueError(score)


def saints_sinners_all():
    """Every level with its details, highest first (for the 'All levels' list)."""
    return [dict(saints_sinners_level(lo), score=None) for lo, _hi, _t, _d in reversed(SAINTS_SINNERS_LEVELS)]


_HEAL_WORDS = re.compile(r"\b(heal|heals|healing|cure|cures)\b", re.I)


def is_healing(attack):
    """A sheet attack row that restores HP instead of dealing damage: its damage or
    notes column says "heal" (e.g. Mend · 1d8 · Heal), or its name does (Healing Word)."""
    if not isinstance(attack, dict):
        return False
    text = " ".join(str(attack.get(k) or "") for k in ("name", "damage", "notes"))
    return bool(_HEAL_WORDS.search(text))


SPELL_EFFECTS = ("", "damage", "heal", "buff", "debuff", "effect")  # "" = just notes; "effect" = older rows (buff or debuff)
SPELL_KINDS = ("damage", "heal", "buff", "debuff")
DAMAGE_TYPES = ("acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison",
                "psychic", "radiant", "slashing", "thunder")
# advantage a lasting effect gives: on the bearer's own attacks, or on attacks made against the bearer
SPELL_ADV = ("", "attacks_adv", "attacks_dis", "attacked_adv", "attacked_dis")
ONGOING_KINDS = ("damage", "heal", "temp")
SPELL_TERRAIN = ("", "rock", "mend")  # what a spell does to the battle map: raise solid rock, or mend the ground
HELP_EXCEPTIONS = {"sleep": False, "sanctuary": True}
DICE_TEXT = re.compile(r"^[-+]?\s*(?:\d*d\d+|\d+|mod)(?:\s*[-+]\s*(?:\d*d\d+|\d+|mod))*$", re.I)


def _dice_text(v):
    """A short dice field ('1d4', '-1d4', '2d8+mod', '5'). Anything else is dropped."""
    v = str(v if v is not None else "").strip()[:40]
    return v if v and DICE_TEXT.match(v) else ""


def _num(v, lo, hi, default=None):
    if v is None or v == "" or isinstance(v, bool):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _flag(spell, key, default):
    v = spell.get(key)
    return default if v is None or v == "" else bool(v)


def spell_info(spell):
    """Normalise one spell row from the sheet (or the spell book). Rows written before
    spells could do anything have only prepared/level/name/notes; they come back as
    plain notes. Rows from before buffs and debuffs were separate say "effect"; they
    become a buff or a debuff by the old rule (no save = it helps)."""
    if not isinstance(spell, dict):
        spell = {}
    name = (str(spell.get("name") or "").strip() or "Spell")[:80]
    notes = str(spell.get("notes") or "")
    effect = spell.get("effect") if spell.get("effect") in SPELL_EFFECTS else ""
    hit = spell.get("hit") if spell.get("hit") in ("attack", *ABILITIES) else ""
    rounds = _num(spell.get("rounds"), 1, 100000)
    ac = _num(spell.get("ac"), -10, 30, 0)
    level = _num(spell.get("level"), 0, 9, 0)
    kind = effect
    if effect == "effect":
        helps = HELP_EXCEPTIONS.get(name.lower(), ac > 0 or not hit)
        kind = "buff" if helps else "debuff"
    return {
        "name": name, "level": level, "kind": kind, "effect": effect, "ac": ac,
        "area": parse_area(spell.get("area") or notes),
        "dice": str(spell.get("dice") or "").strip()[:60], "hit": hit,
        "damage_type": spell.get("damage_type") if spell.get("damage_type") in DAMAGE_TYPES else "",
        # a save for half: most levelled damage spells; cantrips do nothing on a save
        "save_half": _flag(spell, "save_half", kind == "damage" and hit in ABILITIES and level > 0),
        "upcast": _dice_text(spell.get("upcast")),
        "condition": str(spell.get("condition") or "").strip()[:60],
        "rounds": rounds,
        "concentration": _flag(spell, "concentration", bool(re.search(r"\bconcentration\b", notes, re.I))),
        "temp_hp": _dice_text(spell.get("temp_hp")),
        "max_hp": _num(spell.get("max_hp"), 0, 100, 0),
        "roll_mod": _dice_text(spell.get("roll_mod")),
        "dmg_mod": _dice_text(spell.get("dmg_mod")),
        "adv": spell.get("adv") if spell.get("adv") in SPELL_ADV else "",
        "ongoing": _dice_text(spell.get("ongoing")),
        "ongoing_kind": spell.get("ongoing_kind") if spell.get("ongoing_kind") in ONGOING_KINDS else "damage",
        "ongoing_type": spell.get("ongoing_type") if spell.get("ongoing_type") in DAMAGE_TYPES else "",
        "ongoing_save": _flag(spell, "ongoing_save", False),
        "repeat_save": _flag(spell, "repeat_save", False),
        "targets": _num(spell.get("targets"), 1, 50),
        "terrain": spell.get("terrain") if spell.get("terrain") in SPELL_TERRAIN else "",
        # a grapple: the target makes this save at the end of each of its turns to break free
        "escape": spell.get("escape") if spell.get("escape") in ABILITIES else "",
        # brings a creature from the library into the fight on the caster's side, acting right after them
        "summon": str(spell.get("summon") or "").strip()[:200],
        "summon_count": _num(spell.get("summon_count"), 1, 10, 1),
        # a reaction: when they're hit, a d20 roll-off against the DM; win and the hit does half
        "parry": bool(spell.get("parry")),
        # Reckless attack: on a hit the damage is multiplied (2 = double)
        "dmg_mult": _num(spell.get("dmg_mult"), 1, 10, 1),
        # a real saving throw even with the "everything rolls to hit" house rule on
        "force_save": bool(spell.get("force_save")),
        # switched on and off (a magic item's aura): lasts until switched off, reaches allies in its area
        "aura": bool(spell.get("aura")),
        "speed_mult": _num(spell.get("speed_mult"), 1, 10, 1),
        "cooldown": parse_cooldown(spell),
        "notes": notes.strip()[:300],
    }


def spell_lasts(sp):
    """Does the spell leave something on whoever it lands on (a condition, AC, a roll
    bonus, damage every turn...)? Then it becomes an effect on them."""
    return bool(sp["condition"] or sp["ac"] or sp["roll_mod"] or sp["dmg_mod"] or sp["adv"]
                or sp["ongoing"] or sp["max_hp"])


def spell_does_something(sp):
    """Worth a Cast button in a fight (rows that are only notes aren't)."""
    return bool(sp["kind"])


def spell_helps(sp):
    """Does a spell help whoever it lands on (healing, +AC, Bless) rather than work
    against them (Bane, Hold Person)? Same rule as L.spellHelps in core.js."""
    return sp["kind"] in ("heal", "buff")


# ---- what conditions do to rolls ------------------------------------------------------
# 5e: attacking while blinded, frightened, poisoned, prone or restrained has disadvantage;
# attacks against someone blinded, paralyzed, restrained, stunned, unconscious... have advantage.
ATTACKER_DIS = {"blinded", "frightened", "poisoned", "prone", "restrained"}
ATTACKER_ADV = {"invisible"}
TARGET_ADV = {"blinded", "paralyzed", "petrified", "restrained", "stunned", "unconscious"}
TARGET_DIS = {"invisible"}
AUTO_FAIL_STR_DEX = {"paralyzed", "petrified", "stunned", "unconscious"}


def active_effects(conditions):
    return [x for x in (conditions or []) if isinstance(x, dict) and not x.get("expired")]


def _names(conditions):
    return {str(x.get("name") or "").strip().lower() for x in active_effects(conditions)}


def attack_mode(attacker_conds, target_conds=None, melee=False):
    """('advantage' | 'disadvantage' | 'normal', [reasons]) for an attack. Advantage and
    disadvantage cancel out, like the rules say."""
    adv, dis = [], []
    for n in sorted(_names(attacker_conds)):
        if n in ATTACKER_DIS:
            dis.append(n.capitalize())
        if n in ATTACKER_ADV:
            adv.append(n.capitalize())
    for x in active_effects(attacker_conds):
        if x.get("adv") == "attacks_adv":
            adv.append(x["name"])
        elif x.get("adv") == "attacks_dis":
            dis.append(x["name"])
    if target_conds is not None:
        names = _names(target_conds)
        for n in sorted(names):
            if n in TARGET_ADV:
                adv.append("target " + n)
            if n in TARGET_DIS:
                dis.append("target " + n)
        if "prone" in names:
            (adv if melee else dis).append("target prone")
        for x in active_effects(target_conds):
            if x.get("adv") == "attacked_adv":
                adv.append("target " + x["name"])
            elif x.get("adv") == "attacked_dis":
                dis.append("target " + x["name"])
    if adv and not dis:
        return "advantage", adv
    if dis and not adv:
        return "disadvantage", dis
    return "normal", adv + dis


def save_mode(conditions, ability):
    """('auto_fail' | 'disadvantage' | 'normal', reason) for a saving throw."""
    names = _names(conditions)
    if ability in ("str", "dex"):
        for n in sorted(AUTO_FAIL_STR_DEX):
            if n in names:
                return "auto_fail", n.capitalize()
    if ability == "dex" and "restrained" in names:
        return "disadvantage", "Restrained"
    return "normal", ""


def roll_mods(conditions, key="roll_mod"):
    """Dice that effects add to rolls: Bless '+1d4' and Bane '-1d4' on attacks and saves
    (roll_mod), Divine Favor '+1d4' on damage (dmg_mod). Returns [(text, effect name)]."""
    out = []
    for x in active_effects(conditions):
        v = str(x.get(key) or "").strip().replace(" ", "")
        if v:
            out.append((v if v[0] in "+-" else "+" + v, x.get("name") or "effect"))
    return out


def effect_mult(conditions):
    """Damage multiplier from effects on the attacker (Reckless: 2). 1 = normal."""
    m = 1
    for x in active_effects(conditions):
        try:
            m *= max(1, int(x.get("dmg_mult") or 1))
        except (TypeError, ValueError):
            pass
    return m


def with_mods(expr, mods):
    return expr + "".join(m for m, _ in mods)


def damage_multiplier(statblock, damage_type):
    """(multiplier, word) from a stat block's immunities / resistances / vulnerabilities.
    Spells are magical, so 'nonmagical' B/P/S resistance doesn't count."""
    if not damage_type or not isinstance(statblock, dict):
        return 1, ""
    for key, mult, word in (("immunities", 0, "immune"), ("resistances", 0.5, "resists"), ("vulnerabilities", 2, "vulnerable")):
        for part in re.split(r"[;\n]", str(statblock.get(key) or "")):
            if re.search(rf"\b{damage_type}\b", part, re.I) and not re.search(r"nonmagical|non-magical", part, re.I):
                return mult, word
    return 1, ""


AREA_KINDS = {"cone": "cone", "line": "line", "cube": "square", "square": "square",
              "radius": "circle", "sphere": "circle", "circle": "circle", "cylinder": "circle", "emanation": "circle"}
AREA_RE = re.compile(r"(\d+)\s*-?\s*(?:ft|foot|feet)\.?\s*(cone|line|cube|square|radius|sphere|circle|cylinder|emanation)\b", re.I)
RANGE_RE = re.compile(r"\brange\s*(?:of\s*)?(\d+)", re.I)
FEET_RE = re.compile(r"(\d+)\s*-?\s*(?:ft|foot|feet)\b", re.I)


def parse_area(text):
    """'10 ft cone, range 20' -> {'kind': 'cone', 'size': 10, 'range': 20}. Also reads
    spell notes like '1 action · 90 ft · 20 ft square' (range 90). Without a range an
    area starts at the attacker (range 0). None when the text names no area."""
    text = str(text or "")
    m = AREA_RE.search(text)
    if not m:
        return None
    size = max(5, min(500, int(m.group(1))))
    r = RANGE_RE.search(text)
    if r:
        rng = int(r.group(1))
    else:
        other = [int(f.group(1)) for f in FEET_RE.finditer(text) if not (m.start() <= f.start() < m.end())]
        rng = other[0] if other else 0
    return {"kind": AREA_KINDS[m.group(2).lower()], "size": size, "range": max(0, min(1000, rng))}


COOLDOWN_RE = re.compile(r"(\d+)\s*-?\s*(?:turns?|rounds?|rds?)\s*(?:of\s*)?cool\s*-?\s*down|cool\s*-?\s*down\s*(?:of\s*|:\s*)?(\d+)", re.I)


def parse_cooldown(row):
    """How many of their own turns a move needs to recharge after it's used: the
    Cooldown box on the sheet, or notes like '3 turn cool down'. 0 = no cooldown."""
    if not isinstance(row, dict):
        return 0
    v = row.get("cooldown")
    if v not in (None, ""):
        try:
            return max(0, min(20, int(v)))
        except (TypeError, ValueError):
            pass
    m = COOLDOWN_RE.search(" ".join(str(row.get(k) or "") for k in ("name", "notes")))
    return max(0, min(20, int(m.group(1) or m.group(2)))) if m else 0


def cooldown_left(conditions, name, encounter_id=None):
    """Rounds left on a move's cooldown (0 = ready). With encounter_id, only a
    cooldown from that fight counts."""
    for x in conditions or []:
        if isinstance(x, dict) and x.get("cooldown") == name and not x.get("expired") and (x.get("rounds_left") or 0) > 0 \
                and (encounter_id is None or x.get("encounter_id") == encounter_id):
            return x["rounds_left"]
    return 0


def knocked_prone(conditions):
    """A hero who drops to 0 HP is knocked prone. Returns the new list, or None if
    they're already prone."""
    conditions = list(conditions or [])
    if any(isinstance(x, dict) and x.get("name", "").lower() == "prone" and not x.get("expired") for x in conditions):
        return None
    import uuid
    return conditions + [{"id": uuid.uuid4().hex[:12], "name": "Prone", "note": "Knocked down at 0 HP",
                          "rounds_left": None, "expired": False}]


def spell_expression(dice_text, spell_mod):
    """'1d8+mod' -> '1d8+3' using the spellcasting modifier. Returns None when the
    text uses mod but the character has no spellcasting ability set."""
    if re.search(r"\bmod\b", dice_text, re.I):
        if spell_mod is None:
            return None
        dice_text = re.sub(r"\s*([+-])?\s*\bmod\b", lambda m: (m.group(1) or "+") + str(spell_mod), dice_text, flags=re.I)
        dice_text = dice_text.replace("+-", "-").replace("--", "+")
    return dice_text.replace(" ", "")


def ac_bonus(conditions):
    """Temporary AC from effects (Shield of Faith +2, Shield +5, cover...). An effect
    stops counting once its duration has run out, even before the DM removes it."""
    total = 0
    for x in conditions or []:
        if isinstance(x, dict) and not x.get("expired"):
            try:
                total += int(x.get("ac") or 0)
            except (TypeError, ValueError):
                pass
    return total


def effective_ac(ac, conditions):
    return (ac or 0) + ac_bonus(conditions)

