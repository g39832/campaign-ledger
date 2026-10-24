"""D&D 5e rules helpers. Kept free of Flask/DB so they are easy to test.

The character sheet mirrors these formulas in static/js/rules.js for instant
feedback while typing; tests cover this Python version.
"""
import random

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
