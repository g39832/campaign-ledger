"""Loot: the five rarities, the things you find in the abandoned prison, what each kind of chest
holds, what enemies drop, and magic items from the DM's own list (app/magic_items.json: Grayson's
500 homebrew items in five d100 tiers, Common to Legendary).

An item in a chest: {id, name, qty, rarity, type, desc, weight, unique?, coins?}
  - coins: {"gp": 12} instead of a thing to carry (it goes into the sheet's coins)
  - unique: keycards and one-of-a-kind gear: nobody can hold two of the same

Taking an item puts it on the character's sheet (Equipment, or Coins), as long as they can carry
it: 15 lb per point of Strength, like the Player's Handbook.
"""
import json
import os
import random

RARITIES = ["common", "uncommon", "rare", "epic", "legendary"]
RARITY_NAME = {"common": "Common", "uncommon": "Uncommon", "rare": "Rare", "epic": "Epic", "legendary": "Legendary"}
# the Word list's tiers: Tier 4 is "Very rare", which is Epic here
MAGIC_TIER = {"common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}

PRISON_ONLY = "Found only in the abandoned prison."


def _i(name, type_, rarity, weight, desc, unique=False, only=False):
    return {"name": name, "type": type_, "rarity": rarity, "weight": weight,
            "desc": desc + (" " + PRISON_ONLY if only else ""), "unique": unique}


# key -> item. type picks which chests it turns up in.
ITEMS = {
    # --- common ---------------------------------------------------------------------------------
    "ration": _i("Ration bar", "supply", "common", 0.5, "A day's food in a foil brick. Tastes like cardboard and vanilla."),
    "cell": _i("Energy cell", "ammo", "common", 0.2, "Powers energy weapons: 10 shots per cell."),
    "rounds": _i("Slug rounds (20)", "ammo", "common", 1, "Ammunition for slug throwers and scrap launchers."),
    "patch": _i("Med-gel patch", "med", "common", 0.1, "Action: press it on a wound to regain 1d4 + 1 hit points."),
    "torch": _i("Flashlight", "supply", "common", 1, "Bright light in a 30-ft cone, dim for another 30 ft."),
    "tape": _i("Duct tape roll", "supply", "common", 0.5, "Fixes almost anything, for a while."),
    "cuffs": _i("Zip cuffs (5)", "supply", "common", 0.2, "Restrains a creature (DC 15 Strength to break)."),
    "baton": _i("Stun baton", "weapon", "common", 2, "Melee weapon: 1d6 lightning damage, light."),
    "helmet": _i("Riot helmet", "armor", "common", 3, "Advantage on saves against being stunned by noise or flashes."),
    "bandage": _i("Sterile bandages", "med", "common", 0.2, "Stabilise a dying creature without a Medicine check."),
    "multitool": _i("Multitool", "gear", "common", 1, "Counts as thieves' tools and tinker's tools."),
    # --- uncommon -------------------------------------------------------------------------------
    "stim": _i("Stim injector", "med", "uncommon", 0.1, "Bonus action: regain 2d4 + 2 hit points."),
    "pistol": _i("Pulse pistol", "weapon", "uncommon", 2, "Ranged weapon (40/120 ft): 1d8 radiant damage. Uses energy cells."),
    "vest": _i("Kevlar vest", "armor", "uncommon", 4, "+1 AC while worn over light or no armor."),
    "shiv": _i("Plasma shiv", "weapon", "uncommon", 1, "Melee weapon, finesse, light: 1d6 fire damage.", only=True),
    "jammer": _i("Signal jammer", "gadget", "uncommon", 1, "Action: cameras and turrets within 30 ft go dark for 1 minute. One use."),
    "frag": _i("Frag grenade", "grenade", "uncommon", 1, "Action, thrown 60 ft: 10-ft radius, DC 13 Dexterity save, 3d6 fire damage (half on a save)."),
    "emp": _i("EMP grenade", "grenade", "uncommon", 1, "Action, thrown 60 ft: 15-ft radius, constructs take 3d6 lightning damage and can't take reactions."),
    "seckey": _i("Security keycard", "key", "uncommon", 0, "Opens doors and vaults marked SECURITY.", unique=True),
    "labkey": _i("Lab keycard", "key", "uncommon", 0, "Opens the Experimental lab.", unique=True),
    "goggles": _i("Thermal goggles", "gadget", "uncommon", 0.5, "Darkvision 60 ft; you see cloaked creatures as heat outlines."),
    "smoke": _i("Smoke canister", "grenade", "uncommon", 1, "Action: a 20-ft radius of heavy smoke for 1 minute."),
    # --- rare -----------------------------------------------------------------------------------
    "rifle": _i("Pulse rifle", "weapon", "rare", 8, "Ranged weapon (60/180 ft), two-handed: 2d6 radiant damage. Uses energy cells."),
    "trauma": _i("Trauma kit", "med", "rare", 3, "Action: a creature regains 4d4 + 4 hit points and ends one poison or disease. Three uses."),
    "shield": _i("Reinforced riot shield", "armor", "rare", 8, "+2 AC. Reaction: give yourself half cover against one ranged attack.", only=True),
    "cloak": _i("Cloaking module", "gadget", "rare", 1, "Bonus action: you are Invisible until the end of your next turn or until you attack. Once per long rest.", only=True),
    "neural": _i("Neural stim", "med", "rare", 0.1, "Action: advantage on Intelligence and Wisdom checks and saves for 1 hour."),
    "servo": _i("Sentinel servo arm", "gear", "rare", 6, "Strapped on: advantage on Strength checks and your carrying capacity doubles.", only=True),
    "medkit": _i("Medical drone", "gadget", "rare", 4, "Bonus action: a creature within 30 ft regains 2d6 hit points. Three charges, all back at dawn."),
    # --- epic -----------------------------------------------------------------------------------
    "cannon": _i("Prototype arm cannon", "experimental", "epic", 9, "Ranged weapon (60/180 ft): 2d8 fire damage, and the target catches fire (1d6 at the start of its turn until it uses an action to put it out).", only=True),
    "weave": _i("Adaptive armor weave", "armor", "epic", 6, "+2 AC. After you take damage, you resist that damage type until the end of your next turn.", only=True),
    "serum": _i("Gene-splice serum", "experimental", "epic", 0.1, "Action: for 1 minute you regain 5 hit points at the start of each of your turns. One dose.", only=True),
    "dronecore": _i("Drone companion core", "experimental", "epic", 3, "Unfolds into a security drone that follows your orders (use the Security Drone's stats; it acts on your turn).", only=True),
    "phaseknife": _i("Phase knife", "weapon", "epic", 1, "Melee weapon, finesse: 1d8 force damage that ignores cover and armor bonuses from shields."),
    # --- legendary ------------------------------------------------------------------------------
    "wrifle": _i("Warden's energy rifle", "weapon", "legendary", 10, "Ranged weapon (120/360 ft): +2 to hit and damage, 2d10 radiant damage. Overcharge (recharge 6): 4d10 instead.", unique=True, only=True),
    "xblade": _i("Execution blade", "weapon", "legendary", 12, "Melee weapon, two-handed, reach: +2 to hit and damage, 2d10 slashing damage, and 2d10 more against a creature at half HP or less.", unique=True, only=True),
    "omega": _i("Omega clearance badge", "key", "legendary", 0, "Every door, vault and turret in the prison treats you as the warden.", unique=True, only=True),
    "phasebelt": _i("Quantum phase belt", "experimental", "legendary", 1, "Bonus action: teleport up to 30 ft to a space you can see. Three times per long rest.", unique=True, only=True),
    "wardenkey": _i("Warden's access card", "key", "legendary", 0, "The warden's own card. Opens the Restricted vault.", unique=True, only=True),
}

# Each kind of chest: what it's called, how many things, how likely each rarity is, what sort of
# things, some coins, the card that opens it (if locked), and how likely a magic item from your list is.
CHESTS = {
    "supply": {"name": "Standard Supply Crate", "items": (2, 3), "odds": {"common": 70, "uncommon": 25, "rare": 5},
               "types": ["supply", "ammo", "gear", "med"], "coins": ("2d6", "sp"), "magic": 0,
               "about": "Basic supplies, a little money and common gear."},
    "military": {"name": "Military Weapons Crate", "items": (2, 3), "odds": {"common": 35, "uncommon": 40, "rare": 20, "epic": 5},
                 "types": ["weapon", "ammo", "armor", "grenade"], "coins": None, "magic": 2,
                 "about": "Weapons, ammunition, armor and combat gear."},
    "medical": {"name": "Medical Storage Chest", "items": (2, 4), "odds": {"common": 45, "uncommon": 35, "rare": 17, "epic": 3},
                "types": ["med"], "coins": None, "magic": 0, "about": "Healing items and medical supplies."},
    "vault": {"name": "Restricted Security Vault", "items": (2, 3), "odds": {"uncommon": 30, "rare": 45, "epic": 20, "legendary": 5},
              "types": ["weapon", "armor", "key", "gadget"], "coins": ("3d10", "gp"), "magic": 5, "lock": "Security keycard",
              "about": "Rare weapons, access cards and valuable equipment. Needs a Security keycard."},
    "experimental": {"name": "Experimental Container", "items": (2, 3), "odds": {"uncommon": 15, "rare": 45, "epic": 30, "legendary": 10},
                     "types": ["experimental", "gadget", "med"], "coins": None, "magic": 10,
                     "about": "Futuristic experimental equipment and rare oddities."},
    "legendary": {"name": "Legendary Supply Cache", "items": (3, 4), "odds": {"rare": 25, "epic": 45, "legendary": 30},
                  "types": ["weapon", "armor", "experimental", "gadget"], "coins": ("10d10", "gp"), "magic": 20, "lock": "Warden's access card",
                  "about": "Extremely rare equipment, powerful weapons, high-value rewards. Needs the Warden's access card."},
    # the laboratory (app/lab.py): three lockers a floor with only healing items and money, and on the
    # top floor one safe with a single rare magic item from the DM's list (it ignores the magic-items switch)
    "lab": {"name": "Medical Supply Locker", "items": (1, 3), "odds": {"common": 60, "uncommon": 32, "rare": 8},
            "types": [], "pool": ["patch", "stim", "trauma"], "coins": ("2d8", "gp"), "magic": 0, "money": "lab",
            "about": "Healing items and some lab credits."},
    "labprize": {"name": "The Director's Safe", "items": (0, 0), "odds": {"rare": 100}, "types": [], "coins": None,
                 "magic": 100, "magic_rarity": "rare", "magic_always": True, "about": "One rare magic item."},
    # loose papers in the laboratory (app/lab_papers.py): what they say is set when they're put down
    "papers": {"name": "Loose papers", "items": (0, 0), "odds": {"common": 100}, "types": [], "coins": None, "magic": 0,
               "about": "Notes and clues to read (the reader gets them as a handout)."},
    # the missile silo's launch bay (app/silo.py): the three abort keys and Steven's escape lift (nothing inside)
    "abort": {"name": "Launch abort key", "items": (0, 0), "odds": {"common": 100}, "types": [], "coins": None, "magic": 0,
              "about": "Turn all three to stop the launch."},
    "escape": {"name": "Steven's escape lift", "items": (0, 0), "odds": {"common": 100}, "types": [], "coins": None, "magic": 0,
               "about": "Reach it to stop Steven getting away (the missiles launch)."},
    "drop": {"name": "Dropped gear", "items": (0, 0), "odds": {"common": 100}, "types": [], "coins": None, "magic": 0,
             "about": "What a fallen enemy was carrying."},
}
CARDS = ["Security keycard", "Lab keycard", "Warden's access card"]

# What each prison enemy may drop when it falls: [(chance in %, item key or "coins:2d6:gp")]
DROPS = {
    "Cybernetic Prison Guard": [(60, "cell"), (30, "seckey"), (20, "stim"), (8, "pistol"), (100, "coins:1d6:gp")],
    "Riot Suppressor": [(50, "baton"), (25, "helmet"), (15, "seckey"), (10, "shield"), (100, "coins:2d6:gp")],
    "Inmate Enforcer": [(50, "shiv"), (40, "rounds"), (15, "tape"), (10, "labkey"), (60, "coins:2d6:sp")],
    "Experimental Prisoner": [(40, "serum"), (35, "labkey"), (30, "neural")],
    "Stealth Infiltrator": [(40, "cloak"), (35, "goggles"), (25, "smoke"), (25, "labkey"), (100, "coins:3d6:gp")],
    "Security Drone": [(60, "cell"), (30, "jammer"), (25, "seckey"), (10, "dronecore")],
    "Sentinel Unit": [(70, "cell"), (40, "servo"), (20, "weave"), (30, "emp")],
    "Prototype Cyborg": [(45, "cannon"), (30, "medkit"), (25, "phaseknife"), (40, "labkey")],
    "Prison Warden": [(100, "wardenkey"), (60, "wrifle"), (35, "omega"), (100, "coins:6d10:gp")],
    "Execution Unit": [(50, "xblade"), (35, "phasebelt"), (40, "weave"), (100, "cell")],
    # the laboratory: only healing items and money
    "Lab Assistant Drone": [(30, "patch"), (40, "coins:1d6:sp")],
    "Escaped Test Subject": [(25, "patch"), (30, "coins:1d6:sp")],
    "Hazmat Trooper": [(30, "stim"), (70, "coins:1d6:gp")],
    "Bio-Ooze": [(40, "coins:2d6:gp")],
    "Chimera Specimen": [(35, "stim"), (60, "coins:2d8:gp")],
    "Head Researcher": [(100, "trauma"), (100, "coins:6d10:gp")],
    "The Director": [(100, "trauma"), (100, "coins:8d10:gp")],
}
LAB_ENEMIES = {"Lab Assistant Drone", "Escaped Test Subject", "Hazmat Trooper", "Bio-Ooze", "Chimera Specimen", "Head Researcher", "The Director"}


# ---- magic items from the DM's list ---------------------------------------------------------------

_MAGIC = None


def magic_items():
    global _MAGIC
    if _MAGIC is None:
        path = os.path.join(os.path.dirname(__file__), "magic_items.json")
        try:
            with open(path, encoding="utf-8") as f:
                _MAGIC = json.load(f)
        except (OSError, ValueError):
            _MAGIC = []
    return _MAGIC


def magic_item(rarity=None, rnd=random):
    """A random magic item from the list: roll a d100 on the tier for that rarity (any tier if none)."""
    items = magic_items()
    if not items:
        return None
    tier = MAGIC_TIER.get(rarity) or rnd.randint(1, 5)
    pool = [m for m in items if m["tier"] == tier] or items
    m = rnd.choice(pool)
    r = RARITIES[m["tier"] - 1]
    return {"name": m["name"], "qty": 1, "rarity": r, "type": "magic", "weight": 1,
            "desc": f"{m['type']} · {m['rarity']} magic item (d100 roll {m['roll']} on tier {m['tier']}). {m['effect']}",
            "magic": True}


# ---- rolling ---------------------------------------------------------------------------------------

def _dice(expr, rnd):
    n, s = expr.split("d")
    return sum(rnd.randint(1, int(s)) for _ in range(int(n or 1)))


def _new_id(rnd):
    return "%08x" % rnd.getrandbits(32)


def make(key, rnd, qty=1):
    it = dict(ITEMS[key], qty=qty, key=key, id=_new_id(rnd))
    if not it["unique"]:
        it.pop("unique")
    return it


def coins(expr, unit, rnd, where="prison"):
    n = _dice(expr, rnd)
    if where == "lab":
        return {"id": _new_id(rnd), "name": f"Lab credits ({n} {unit})", "qty": 1, "rarity": "common", "type": "coins",
                "weight": 0, "desc": f"Research credit chips, worth {n} {unit}. They go straight into your coins.", "coins": {unit: n}}
    return {"id": _new_id(rnd), "name": f"Credit chips ({n} {unit})", "qty": 1, "rarity": "common", "type": "coins",
            "weight": 0, "desc": f"Prison scrip, worth {n} {unit}. It goes straight into your coins.", "coins": {unit: n}}


def _pick_rarity(odds, rnd):
    total = sum(odds.values())
    r = rnd.uniform(0, total)
    for k in RARITIES:
        if k in odds:
            r -= odds[k]
            if r <= 0:
                return k
    return max(odds, key=lambda k: RARITIES.index(k))


def roll_chest(kind, seed, magic_on=True):
    """What's in a chest of this kind. The same seed always gives the same loot."""
    c = CHESTS[kind]
    rnd = random.Random(seed)
    out = []
    def fits(k, v):  # a chest with its own list of things (the lab's lockers) only holds those
        return (k in c["pool"]) if c.get("pool") else v["type"] in c["types"]
    for _ in range(rnd.randint(*c["items"])):
        rarity = _pick_rarity(c["odds"], rnd)
        pool = [k for k, v in ITEMS.items() if fits(k, v) and v["rarity"] == rarity and k != "wardenkey"]
        if not pool:  # nothing of that rarity of this sort: the nearest rarity down
            for r in reversed(RARITIES[:RARITIES.index(rarity)]):
                pool = [k for k, v in ITEMS.items() if fits(k, v) and v["rarity"] == r and k != "wardenkey"]
                if pool:
                    break
        if not pool:
            continue
        key = rnd.choice(pool)
        if any(x.get("key") == key for x in out):
            have = next(x for x in out if x.get("key") == key)
            if not have.get("unique"):
                have["qty"] += 1
            continue
        out.append(make(key, rnd, qty=rnd.randint(2, 4) if ITEMS[key]["type"] == "ammo" else 1))
    if c["coins"]:
        out.append(coins(*c["coins"], rnd, c.get("money", "prison")))
    if (magic_on or c.get("magic_always")) and c["magic"] and rnd.randint(1, 100) <= c["magic"]:
        best = c.get("magic_rarity") or max((x["rarity"] for x in out), key=RARITIES.index, default="rare")
        m = magic_item(best, rnd)
        if m:
            m["id"] = _new_id(rnd)
            out.append(m)
    return out


def roll_drop(name, seed, carries=()):
    """What an enemy drops: its own table, plus anything it was given to carry (a keycard)."""
    rnd = random.Random(seed)
    out = []
    for chance, what in DROPS.get(name, []):
        if rnd.randint(1, 100) > chance:
            continue
        if what.startswith("coins:"):
            _, expr, unit = what.split(":")
            out.append(coins(expr, unit, rnd, "lab" if name in LAB_ENEMIES else "prison"))
        elif not any(x.get("key") == what for x in out):
            out.append(make(what, rnd))
    for key in carries:
        if key in ITEMS and not any(x.get("key") == key for x in out):
            out.append(make(key, rnd))
    return out


# ---- putting it on the sheet --------------------------------------------------------------------

def carry_capacity(char):
    try:
        st = int((char.get("abilities") or {}).get("str") or 10)
    except (TypeError, ValueError):
        st = 10
    cap = st * 15
    if any(str(r.get("name") or "").lower() == "sentinel servo arm" for r in char.get("equipment") or []):
        cap *= 2
    return cap


def carried(char):
    total = 0.0
    for r in char.get("equipment") or []:
        try:
            total += float(r.get("weight") or 0) * float(r.get("qty") or 1)
        except (TypeError, ValueError):
            pass
    return round(total, 1)


def has_item(char, name):
    name = name.lower().strip()
    return any(str(r.get("name") or "").lower().strip() == name and (r.get("qty") in (None, "") or float(r.get("qty") or 0) > 0)
               for r in char.get("equipment") or [])


def give(char, item):
    """Put an item on a character (a decoded characters row). Returns (equipment, currency) to save,
    or raises ValueError with why they can't take it."""
    eq = [dict(r) for r in (char.get("equipment") or []) if isinstance(r, dict)]
    cur = dict(char.get("currency") or {})
    if item.get("coins"):
        for unit, n in item["coins"].items():
            cur[unit] = int(cur.get(unit) or 0) + int(n)
        return eq, cur
    qty = int(item.get("qty") or 1)
    if item.get("unique") and has_item(char, item["name"]):
        raise ValueError(f"You already have a {item['name']} — you can only carry one")
    w = float(item.get("weight") or 0) * qty
    if w and carried(char) + w > carry_capacity(char):
        raise ValueError(f"Too heavy: you're carrying {carried(char):g} of {carry_capacity(char)} lb, "
                         f"and the {item['name']} weighs {w:g} lb. Drop something first")
    notes = f"{RARITY_NAME.get(item.get('rarity'), 'Common')} · {item.get('desc') or ''}".strip()[:600]
    same = next((r for r in eq if str(r.get("name") or "").lower() == item["name"].lower() and not item.get("unique")), None)
    if same:
        try:
            same["qty"] = int(float(same.get("qty") or 1)) + qty
        except (TypeError, ValueError):
            same["qty"] = qty
    else:
        eq.append({"qty": qty, "name": item["name"], "weight": item.get("weight") or None, "notes": notes})
    return eq, cur
