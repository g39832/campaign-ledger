"""Relay drones (Steven Voss, the artificer): small summoned drones that work with spells.

A summon spell line with the word "relay" ("Deploy Drones: summon 2 Voss Drone, relay, ...")
makes drones that:

* echo their owner's spells: when the owner casts a spell, each drone casts it again from
  where it hovers, on everyone the spell picked who is within RELAY_FT of that drone (no battle
  map: on all of them). It uses the owner's spell attack and save DC, and costs no action.
* copy other people's spells: when anyone else casts a spell within RELAY_FT of a drone (of the
  caster or of anyone it's cast on), the owner learns it and can cast it back ONCE. The owner
  keeps up to COPY_MAX of them (statblock "copied"); the oldest goes first.

spells.cast calls echo() and record_copies() after a cast lands, and use_copied() before a
copied spell is cast. None of this runs for an echo itself, so a drone never echoes an echo.
"""
import json

from . import fields as F

RELAY_FT = 30
COPY_MAX = 3
DOWN = ("dead", "defeated", "fled")
# what a drone won't echo or copy: these aren't simple "hit them / help them" spells
SPECIAL = ("summon", "terrain", "zone", "aura", "rewind", "clone_swap", "reaction", "death_ward", "parry")
AREA_WORD = {"circle": "radius", "square": "square", "cone": "cone", "line": "line"}
KEEP = ("level", "dice", "hit", "damage_type", "save_half", "upcast", "condition", "rounds", "concentration", "temp_hp",
        "max_hp", "roll_mod", "dmg_mod", "adv", "ongoing", "ongoing_kind", "ongoing_type", "ongoing_save", "repeat_save",
        "targets", "escape", "dmg_mult", "force_save", "ac", "notes")


def can_relay(sp, data):
    """A plain spell a drone can echo or copy (not a summon, a zone, a reaction, a grapple...)."""
    if sp.get("kind") not in ("damage", "heal", "buff", "debuff"):
        return False
    if any(sp.get(k) for k in SPECIAL):
        return False
    return not (isinstance(data.get("spell"), dict) and data["spell"].get("move"))


def spec_of(sp):
    """The normalised spell (rules.spell_info) as a spell line the browser and spell_from take back."""
    out = {"name": sp["name"], "effect": sp["kind"]}
    for k in KEEP:
        v = sp.get(k)
        if v not in (None, "", False, 0) or k in ("level",):
            out[k] = v
    a = sp.get("area")
    if isinstance(a, dict) and a.get("size"):
        out["area"] = f"{a['size']} ft {AREA_WORD.get(a['kind'], 'radius')}" + (f", range {a['range']}" if a.get("range") else "")
    return out


LOOK_BY_TYPE = {"fire": "flames", "cold": "frost", "lightning": "sparks", "thunder": "sparks", "radiant": "holy",
                "poison": "venom", "acid": "venom", "necrotic": "arcane", "psychic": "arcane", "force": "arcane",
                "bludgeoning": "punch", "slashing": "slash", "piercing": "arrow"}


def look_for(sp, data):
    """How the spell looks on the map: the look it was cast with, else one from its damage type."""
    raw = data.get("spell")
    if isinstance(raw, dict) and raw.get("look"):
        return str(raw["look"])
    if sp["kind"] == "heal" or sp["kind"] == "buff":
        return "holy"
    return LOOK_BY_TYPE.get(sp.get("damage_type") or "", "arcane")


def drones_of(ctx, owner_id):
    """The owner's relay drones still standing in this fight."""
    return [c for c in ctx.combatants() if c.get("follows") == owner_id and (c["statblock"] or {}).get("relay")
            and c["status"] not in DOWN]


def _near(ctx, a, b):
    from .movement import distance_ft
    d = distance_ft(ctx.conn, ctx.enc["id"], a, b)
    return d is None or d <= RELAY_FT


def echo(ctx, caster, sp, data, nums, results, viewer=None):
    """Each of the caster's drones casts the spell again. Returns the drones' cast results."""
    from .spells import cast
    if data.get("echo") or not can_relay(sp, data):
        return []
    drones = drones_of(ctx, caster["id"])
    if not drones:
        return []
    spec = spec_of(sp)
    # the owner's numbers, not the drone's: a drone is only a relay
    if nums.get("dc"):
        spec["dc"] = nums["dc"]
    if nums.get("attack") is not None:
        spec["attack_bonus"] = nums["attack"]
    spec["name"] = sp["name"]
    spec["relayed"] = True
    hit_ids = [r["id"] for r in results]
    out = []
    for d in drones:
        targets = []
        for t in hit_ids:
            try:
                tc = ctx.combatant(t)
            except F.NotFound:
                continue
            if tc["status"] in DOWN and sp["kind"] != "heal":
                continue
            if _near(ctx, d["id"], t):
                targets.append(t)
        if not targets:
            continue
        out.append(cast(ctx, d["id"], {"spell": dict(spec, look=str((data.get("spell") or {}).get("look") or "") if isinstance(data.get("spell"), dict) else ""),
                                       "targets": targets, "echo": True, "force": True, "free": True}, viewer))
    return out


def record_copies(ctx, caster, sp, data, target_ids):
    """Someone cast a spell near a drone: its owner learns it (to cast back once). Returns log lines."""
    if data.get("echo") or not can_relay(sp, data):
        return []
    lines = []
    owners = {}
    for c in ctx.combatants():
        sb = c["statblock"] or {}
        if not sb.get("relay") or c["status"] in DOWN or c.get("follows") in (None, caster["id"]) or c["id"] == caster["id"]:
            continue
        if caster.get("follows") == c.get("follows"):
            continue  # one of the owner's own drones
        if any(_near(ctx, c["id"], x) for x in [caster["id"], *target_ids]):
            owners.setdefault(c["follows"], c)
    for owner_id, drone in owners.items():
        try:
            owner = ctx.combatant(owner_id)
        except F.NotFound:
            continue
        if owner["linked"] or owner["status"] in DOWN:
            continue  # only a stat block keeps copied spells
        sb = dict(owner["statblock"] or {})
        spec = spec_of(sp)
        spec.pop("dc", None)
        spec["name"] = f"{sp['name']} (copied)"
        spec["copied"] = True
        spec["copied_from"] = caster["name"]
        spec["look"] = look_for(sp, data)  # so it still has its animation on the map
        kept = [s for s in (sb.get("copied") or []) if isinstance(s, dict) and s.get("name") != spec["name"]]
        kept.append(spec)
        sb["copied"] = kept[-COPY_MAX:]
        ctx.conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), owner["id"]))
        lines.append(f"{drone['name']} records {sp['name']} — {owner['name']} can cast it back once")
    return lines


def use_copied(ctx, caster, data):
    """Casting a copied spell uses it up. Raises when it was already used."""
    raw = data.get("spell")
    if not (isinstance(raw, dict) and raw.get("copied")) or data.get("echo"):
        return
    sb = dict(caster["statblock"] or {})
    have = [s for s in (sb.get("copied") or []) if isinstance(s, dict)]
    left = [s for s in have if s.get("name") != raw.get("name")]
    if len(left) == len(have):
        raise F.ApiError(f"{raw.get('name') or 'That spell'} has already been cast back — a drone has to copy it again")
    sb["copied"] = left
    ctx.conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), caster["id"]))
