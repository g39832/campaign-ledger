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
        "roll_to_hit": True,  # every attack and harmful spell rolls d20 + bonus against the target's AC (house rule; off = saves)
    },
    "players": {
        "edit_hp": True,      # players may apply damage/healing/temp HP to their own character
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
    skills = {}
    for key, _label, ab in SKILLS:
        level = int(skill_profs.get(key) or 0)  # 0 none, 1 proficient, 2 expertise
        skills[key] = mods[ab] + prof * level + int(skill_bonus.get(key) or 0)
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


SPELL_EFFECTS = ("", "damage", "heal", "effect")  # "" = just notes, nothing to roll


def spell_info(spell):
    """Normalise one spell row from the sheet. Rows written before spells could roll
    have only prepared/level/name/notes; they come back as plain notes."""
    if not isinstance(spell, dict):
        spell = {}
    effect = spell.get("effect") if spell.get("effect") in SPELL_EFFECTS else ""
    hit = spell.get("hit") if spell.get("hit") in ("attack", *ABILITIES) else ""
    try:
        rounds = int(spell.get("rounds")) if spell.get("rounds") not in (None, "") else None
    except (TypeError, ValueError):
        rounds = None
    try:
        ac = max(-10, min(30, int(spell.get("ac") or 0)))
    except (TypeError, ValueError):
        ac = 0
    return {"name": (str(spell.get("name") or "").strip() or "Spell")[:80], "level": spell.get("level"), "ac": ac,
            "effect": effect, "dice": str(spell.get("dice") or "").strip()[:60], "hit": hit,
            "condition": str(spell.get("condition") or "").strip()[:60],
            "rounds": rounds if rounds and 0 < rounds <= 1000 else None}


HELP_EXCEPTIONS = {"sleep": False, "sanctuary": True}


def spell_helps(sp):
    """Does a spell help whoever it lands on (healing, +AC, Bless) rather than work
    against them (Bane, Hold Person)? Effect spells with no save are help; a few
    spells don't follow that. Same rule as L.spellHelps in core.js."""
    key = sp["name"].lower()
    if key in HELP_EXCEPTIONS:
        return HELP_EXCEPTIONS[key]
    return sp["effect"] == "heal" or sp["ac"] > 0 or (sp["effect"] == "effect" and not sp["hit"])


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

