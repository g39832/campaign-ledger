"""Yamato's techniques (2026-11-15 rework): a clone-based swordsman of misdirection, battlefield
control and combos. Seven moves, each a spell row on his sheet with `technique: <key>`:

  key             name             cooldown  clones                       action
  phantom_blade   Phantom Blade    2         -                            1 action
  storm_wave      Storm Wave       5         USES UP every clone out      1 action to sheathe, 1 to release (a later turn)
  upper_slash     Upper Slash      1         -                            1 action
  guard_break     Guard Break      3         USES UP the clone it sends   1 action
  clone_calling   Clone Calling    1/round   MOVES clones (no harm done)  free, any time in the fight
  chain_attack    Chain Attack     4         clones join (not used up)    1 action
  mirage          Mirage           5         hides among clones           1 action (ending it is free)

His weapon is his "Slash" attack row (+2 to hit, 2d8+4): every "weapon damage" below is that.
His technique save DC is 8 + proficiency + Dexterity.

- Phantom Blade: a sweep at every enemy picked within 10 ft (one attack roll each). Each one hit is
  knocked back 10 ft or Slowed (half speed until the end of its next turn). The DM picks per enemy;
  left on "by size" it goes: Medium or smaller knocked back, Large slowed, Huge or bigger only hurt.
- Upper Slash: one enemy within 5 ft. On a hit it's Launched until its own next turn starts:
  attacks against it have advantage (Yamato's clones act right after him: that's the combo).
  Huge or bigger can't be launched; Large makes a Strength save to stay down.
- Guard Break: one clone charges an enemy within 30 ft of it and rams it (attack roll). On a hit the
  enemy is Staggered: -2 AC until its next turn starts. The clone is used up either way.
- Storm Wave: first Yamato sheathes his blade (he's committed: it can't be released the same turn).
  On a later turn he releases it at one enemy within 10 ft: every clone out is used up, each adds the
  weapon dice again (at most 3 clones: up to 4x the dice). Dexterity save, half on a success. Until
  his next turn he takes 3 less damage from every hit.
- Clone Calling: every clone (or the ones picked) comes back to the squares around Yamato. They keep
  their HP. Once a round, any time in the fight, no action.
- Chain Attack: Yamato and his clones strike enemies they've surrounded. On the map only clones (and
  Yamato) right next to a picked enemy join in, each clone at ONE enemy only; at least two of them in
  all. Each enemy makes a Dexterity save (DC +2 for every attacker past the first, at most +4); it
  takes the weapon dice once per attacker on it (at most 4), half on a success.
- Mirage: while it's on, an enemy trying to pick out the real Yamato makes a flat Perception check
  (its Perception bonus from its stat block only) against DC 10 + 2 per clone out (max 16). It ends
  when Yamato ends it, when his last clone is gone, or when the DM takes it off (exposed).

Cooldowns use the usual cooldown effects (start_cooldown): they count down at the end of his own
turns and show on every screen. No clone ever counts towards two attacks at once: clones used up are
gone at once, and in a Chain Attack each clone is given to one enemy only.
"""
import json
import random
import re
import uuid

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import claim_op, get_db, now_iso, tx

bp = Blueprint("yamato", __name__)

MAX_CLONES = 3          # clones that can add to one Storm Wave / one enemy's Chain Attack
STORM_DR = 3            # damage he doesn't take per hit until his next turn after Storm Wave
SHEATHED = "Storm Wave: blade sheathed"
MIRAGE = "Mirage"

TECHNIQUES = {
    "phantom_blade": {"name": "Phantom Blade", "cooldown": 2, "clones": "", "targets": "many", "action": True,
                      "info": "Wide slash at every enemy you pick within 10 ft · knocks back or slows (DM picks; by size)"},
    "storm_wave": {"name": "Storm Wave", "cooldown": 5, "clones": "uses up all", "targets": "one", "action": True,
                   "info": "Ultimate · turn 1 sheathe, a later turn release at an enemy within 10 ft · every clone out adds the weapon dice (max 3) · Dex save for half · -3 damage taken per hit until your next turn"},
    "upper_slash": {"name": "Upper Slash", "cooldown": 1, "clones": "", "targets": "one", "action": True,
                    "info": "Weapon hit within 5 ft · launches it: attacks against it have advantage until its next turn (Huge+ immune, Large Str save)"},
    "guard_break": {"name": "Guard Break", "cooldown": 3, "clones": "uses up one", "targets": "one", "action": True,
                    "info": "A clone rams an enemy within 30 ft of it · hit: Staggered, -2 AC until its next turn · the clone is used up"},
    "clone_calling": {"name": "Clone Calling", "cooldown": 0, "clones": "moves", "targets": "none", "action": False,
                      "info": "Your clones come back beside you (they keep their HP) · no action, any time, once a round"},
    "chain_attack": {"name": "Chain Attack", "cooldown": 4, "clones": "joins", "targets": "many", "action": True,
                     "info": "You and your clones hit enemies you've surrounded · each clone joins one enemy · Dex save (harder per attacker) for half"},
    "mirage": {"name": "Mirage", "cooldown": 5, "clones": "hides", "targets": "none", "action": True,
               "info": "You look just like your clones · enemies need a Perception check to find the real you · ends when you end it or your clones are gone"},
}
ORDER = ["phantom_blade", "storm_wave", "upper_slash", "guard_break", "clone_calling", "chain_attack", "mirage"]


def rows(cooldowns=True):
    """The seven sheet rows (spell rows; they do nothing through the normal Cast)."""
    return [{"name": TECHNIQUES[k]["name"], "technique": k, "level": 0, "prepared": False, "effect": "",
             "cooldown": TECHNIQUES[k]["cooldown"] or None, "notes": TECHNIQUES[k]["info"]} for k in ORDER]


# ---- reading the fight ------------------------------------------------------------------------------

def _weapon(ch):
    """His weapon: the Slash row (or the first attack with a bonus and damage). (bonus, 'NdM+K')."""
    from . import dice
    atts = [a for a in ch.get("attacks") or [] if isinstance(a, dict) and dice.damage_expression(str(a.get("damage") or ""))]
    a = next((a for a in atts if str(a.get("name") or "").strip().lower() == "slash"), atts[0] if atts else None)
    if a is None:
        raise F.ApiError("Yamato needs a weapon attack (Slash) on his sheet for his techniques")
    return dice.attack_bonus(str(a.get("bonus") or "")) or 0, dice.damage_expression(str(a.get("damage") or ""))


def _dice_times(expr, n):
    """'2d8+4' with the dice n times over: '6d8+4' for n = 3."""
    m = re.match(r"^\s*(\d*)d(\d+)(.*)$", expr)
    if not m:
        return expr
    return f"{int(m.group(1) or 1) * n}d{m.group(2)}{m.group(3)}"


def _dc(ch):
    from .rules import derived
    d = derived(ch)
    return 8 + d["prof"] + d["mods"]["dex"]


def _char(conn, char_id):
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    ch["id"] = char_id
    return ch


def _clones(ctx, me):
    return [c for c in ctx.combatants() if c.get("follows") == me["id"] and c["status"] not in ("dead", "defeated", "fled")]


def _foes(ctx, me):
    return [c for c in ctx.combatants() if c["kind"] == "enemy" and not c["hidden"] and c["status"] not in ("dead", "defeated", "fled")]


def _size(c):
    if c["linked"]:
        return "medium"
    word = str((c.get("statblock") or {}).get("creature_type") or "medium").split()[0].lower()
    return word if word in ("tiny", "small", "medium", "large", "huge", "gargantuan") else "medium"


def _map_and_tokens(ctx):
    from .movement import _live_map
    return _live_map(ctx.conn, ctx.enc["id"])


def _tok(ctx, m, cid):
    from .movement import _token_of
    return _token_of(ctx.conn, m["id"], cid) if m is not None else None


def _next_to(a, b):
    """Two tokens (any size) side by side or overlapping (5 ft)."""
    gx = max(0, b["x"] - (a["x"] + a["size"]), a["x"] - (b["x"] + b["size"]))
    gy = max(0, b["y"] - (a["y"] + a["size"]), a["y"] - (b["y"] + b["size"]))
    return max(gx, gy) < 1 + 1e-6


def _row_of(ch, key):
    for i, s in enumerate(ch.get("spells") or []):
        if isinstance(s, dict) and s.get("technique") == key:
            return i, s
    return None, None


def _cond(name, **kw):
    return dict({"id": uuid.uuid4().hex[:12], "name": name, "note": "", "rounds_left": None, "expired": False}, **kw)


def _add_cond(ctx, cid, cond):
    c = ctx.combatant(cid)
    ctx.set_vitals(c, conditions=[x for x in c["conditions"] if x.get("name") != cond["name"]] + [cond])


def _drop_named(ctx, cid, name, why=""):
    from .combat import drop_conditions
    c = ctx.combatant(cid)
    ids = {x["id"] for x in c["conditions"] if x.get("name") == name and x.get("id")}
    if ids:
        drop_conditions(ctx, c, ids, why=why)


def _has(c, name):
    return next((x for x in c["conditions"] if x.get("name") == name and not x.get("expired")), None)


def _until_their_turn(ctx, cast_id, target_id):
    """An effect from a technique lasts until the start of the target's own next turn."""
    t = ctx.combatant(target_id)
    changed = False
    for x in t["conditions"]:
        if (x.get("source") or {}).get("cast") == cast_id:
            x.update(tick="start", tick_on=target_id, rounds_left=1)
            changed = True
    if changed:
        ctx.set_vitals(t, conditions=t["conditions"])


def consume(ctx, clone, why):
    """A clone is used up by a technique: gone from the fight and the map, with no death burst."""
    from .maps import _bump
    conn = ctx.conn
    conn.execute("UPDATE hp_changes SET combatant_id = NULL WHERE combatant_id = ?", (clone["id"],))
    for m in conn.execute("SELECT DISTINCT map_id FROM map_tokens WHERE combatant_id = ?", (clone["id"],)).fetchall():
        conn.execute("DELETE FROM map_tokens WHERE map_id = ? AND combatant_id = ?", (m["map_id"], clone["id"]))
        _bump(conn, m["map_id"])
    conn.execute("DELETE FROM combatants WHERE id = ?", (clone["id"],))


def check_mirage(ctx, owner_id):
    """Mirage ends by itself once the last clone is gone."""
    try:
        me = ctx.combatant(owner_id)
    except F.NotFound:
        return
    if _has(me, MIRAGE) and not _clones(ctx, me):
        _drop_named(ctx, owner_id, MIRAGE, "no clones left to hide among")


def clone_gone(ctx, clone):
    """Hook: one of someone's clones dropped or was dismissed."""
    owner = (clone.get("statblock") or {}).get("follows")
    if owner:
        check_mirage(ctx, owner)


# ---- what the screens show ----------------------------------------------------------------------------

def state(conn, eid, cb_id, ch):
    """The techniques on this sheet, with whether each one can be used right now (and why not)."""
    from .combat import Ctx
    from .rules import cooldown_left
    have = [(i, s) for i, s in enumerate(ch.get("spells") or []) if isinstance(s, dict) and s.get("technique") in TECHNIQUES]
    if not have:
        return None
    ctx = me = None
    if eid:
        ctx = Ctx(conn, eid)
        try:
            me = ctx.combatant(cb_id)
        except F.NotFound:
            me = None
    live = bool(me and ctx.enc["status"] == "active")
    clones = _clones(ctx, me) if live else []
    my_turn = bool(live and ctx.enc["current_id"] == me["id"])
    try:
        bonus, dmg = _weapon(ch)
    except F.ApiError:
        bonus, dmg = 0, ""
    out = []
    for i, s in have:
        key = s["technique"]
        t = TECHNIQUES[key]
        name = (str(s.get("name") or "").strip() or t["name"])
        cd = int(s.get("cooldown") or t["cooldown"] or 0)
        left = cooldown_left(me["conditions"], name, eid) if live else 0
        why, stage = "", ""
        if not live:
            why = "in a fight"
        elif left:
            why = f"recharging · ready in {max(1, left - 1)} turn{'s' if max(1, left - 1) != 1 else ''}"
        elif key == "clone_calling":
            if (me["statblock"] or {}).get("called_round") == ctx.enc["round"]:
                why = "used this round"
            elif not clones:
                why = "no clones out"
        elif key == "mirage" and _has(me, MIRAGE):
            stage = "on"
        elif key == "storm_wave" and _has(me, SHEATHED):
            prep = _has(me, SHEATHED)
            stage = "release" if prep.get("prep_round") != ctx.enc["round"] else "sheathed"
            if stage == "sheathed":
                why = "sheathed: release it on your next turn"
        if not why and t["action"] and not my_turn and not (key == "mirage" and stage == "on"):
            why = "on your turn"
        if not why and key in ("guard_break",) and not clones:
            why = "needs a clone out"
        if not why and key == "mirage" and stage != "on" and not clones:
            why = "needs a clone out"
        if not why and key == "chain_attack" and not clones:
            why = "needs a clone out"
        out.append({"index": i, "key": key, "name": name, "cooldown": cd, "recharging": left, "clones": t["clones"],
                    "targets": "one" if stage == "release" else ("none" if key == "storm_wave" else t["targets"]),
                    "pick_clone": key == "guard_break", "action": t["action"] and not (key == "mirage" and stage == "on"),
                    "info": t["info"], "stage": stage, "ready": not why, "why": why,
                    "button": {"storm_wave": {"": "Sheathe", "sheathed": "Sheathed", "release": "Release Storm Wave"}[stage],
                               "mirage": "End Mirage" if stage == "on" else "Use"}.get(key, "Use"),
                    "mirage_dc": mirage_dc(len(clones)) if key == "mirage" else None})
    return {"moves": out, "weapon": {"bonus": bonus, "damage": dmg}, "dc": _dc(ch),
            "clones": [{"id": k["id"], "name": k["name"], "hp": k["hp"], "max_hp": k["max_hp"]} for k in clones],
            "foes": [{"id": f["id"], "name": f["name"]} for f in _foes(ctx, me)] if live else [],
            "mirage": bool(live and _has(me, MIRAGE))}


def mirage_dc(n):
    return min(16, 10 + 2 * n)


# ---- using one --------------------------------------------------------------------------------------

def use(ctx, me, index, data, player=False, viewer=None):
    """Use technique `index` (Yamato's sheet row). Returns {name, summary, cast?}."""
    from .combat import start_cooldown, used_a_move
    from .movement import check_action
    from .rules import cooldown_left
    if ctx.enc["status"] != "active":
        raise F.ApiError("Techniques are for a running fight")
    if not me["linked"]:
        raise F.ApiError("Only a character with techniques on their sheet can use them")
    ch = _char(ctx.conn, me["character_id"])
    rows_ = ch.get("spells") or []
    try:
        row = rows_[int(index)]
    except (TypeError, ValueError, IndexError):
        raise F.ApiError("That technique isn't on the sheet any more")
    key = row.get("technique") if isinstance(row, dict) else None
    if key not in TECHNIQUES:
        raise F.ApiError("That isn't one of the techniques")
    t = TECHNIQUES[key]
    name = str(row.get("name") or "").strip() or t["name"]
    cd = int(row.get("cooldown") or t["cooldown"] or 0)
    my_turn = ctx.enc["current_id"] == me["id"]
    targets = [int(x) for x in (data.get("targets") or []) if isinstance(x, int) and not isinstance(x, bool)]
    picked_clones = [int(x) for x in (data.get("clones") or []) if isinstance(x, int) and not isinstance(x, bool)]
    ending_mirage = key == "mirage" and _has(me, MIRAGE)
    if cooldown_left(me["conditions"], name, ctx.enc["id"]) and not ending_mirage:
        raise F.ApiError(f"{name} is still recharging")
    prep = _has(me, SHEATHED) if key == "storm_wave" else None
    if prep and prep.get("prep_round") == ctx.enc["round"]:
        raise F.ApiError(f"{name} can't be released the same turn it's sheathed — release it on the next turn")
    if t["action"] and not ending_mirage:
        if player and not my_turn:
            raise F.ApiError(f"{name} is used on your turn", status=403)
        check_action(ctx.conn, me["id"], name)
    if me["hp"] <= 0 and me["linked"] and not ending_mirage:
        raise F.ApiError(f"{me['name']} is down and can't use {name}")
    fn = {"phantom_blade": _phantom_blade, "storm_wave": _storm_wave, "upper_slash": _upper_slash, "guard_break": _guard_break,
          "clone_calling": _clone_calling, "chain_attack": _chain_attack, "mirage": _mirage}[key]
    out = fn(ctx, me, ch, name, cd, targets, picked_clones, data, viewer)
    if out.get("spend") and not out.get("spent"):
        used_a_move(ctx, me["id"], name)
    if out.get("cooldown"):
        start_cooldown(ctx, me["id"], name, out["cooldown"])
    ctx.conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["id"]))
    return {"name": name, "summary": out["summary"], "cast": out.get("cast")}


def _need_targets(ctx, me, targets, name, one=False):
    foes = {f["id"] for f in _foes(ctx, me)}
    if not targets:
        raise F.ApiError(f"Pick who {name} is aimed at")
    if one and len(targets) != 1:
        raise F.ApiError(f"{name} is aimed at one enemy")
    if not set(targets) <= foes:
        raise F.ApiError("Pick enemies who are in the fight (and showing)")
    return targets


def _engine(ctx, caster_id, spec, targets, viewer, free=True):
    """One attack or save through the spell engine (dice, effects, log, map fx). free: no action used
    here (the technique spends Yamato's one action itself)."""
    from .spells import cast
    spec = dict({"level": 0, "cooldown": 0, "move": True, "notes": "", "damage_type": ""}, **spec)
    return cast(ctx, caster_id, {"spell": spec, "targets": targets, "free": True, "force": True, "_no_action": free}, viewer)


def _phantom_blade(ctx, me, ch, name, cd, targets, clones, data, viewer):
    from .movement import check_reach, shove
    _need_targets(ctx, me, targets, name)
    check_reach(ctx.conn, ctx.enc["id"], me["id"], targets, 10, name)
    bonus, dmg = _weapon(ch)
    res = _engine(ctx, me["id"], {"name": name, "effect": "damage", "dice": dmg, "hit": "attack", "attack_bonus": bonus,
                                  "damage_type": "slashing"}, targets, viewer)
    picks = data.get("rider") if isinstance(data.get("rider"), dict) else {}
    lines = [res["summary"]]
    for r in res["targets"]:
        if r["how"] not in ("hit", "crit"):
            continue
        t = ctx.combatant(r["id"])
        if t["status"] in ("dead", "defeated") or t["hp"] <= 0:
            continue
        size = _size(t)
        choice = str(picks.get(str(t["id"])) or picks.get(t["id"]) or "size")
        if choice == "size":
            choice = "push" if size in ("tiny", "small", "medium") else "slow" if size == "large" else "none"
        if choice == "push":
            moved = shove(ctx, me, t["id"], 10)
            lines.append(moved or f"{t['name']} is knocked back (move it 10 ft away from {me['name']})")
        elif choice == "slow":
            _add_cond(ctx, t["id"], _cond("Slowed", note=f"{name}: half speed until the end of its next turn", slowed=True,
                                          rounds_left=1, tick="end", tick_on=t["id"], encounter_id=ctx.enc["id"],
                                          auto_expire=True, applied_round=ctx.enc["round"]))
            lines.append(f"{t['name']} is Slowed (half speed until the end of its next turn)")
        else:
            lines.append(f"{t['name']} is too big to knock back" if size in ("huge", "gargantuan") else f"{t['name']} holds its ground")
    summary = "; ".join(lines)
    ctx.log("spell", "↳ " + "; ".join(lines[1:])) if len(lines) > 1 else None
    return {"summary": summary, "cast": res, "spend": True, "cooldown": cd}


def _upper_slash(ctx, me, ch, name, cd, targets, clones, data, viewer):
    from .movement import check_reach
    from .spells import Roller, roll_save
    targets = _need_targets(ctx, me, targets, name, one=True)
    check_reach(ctx.conn, ctx.enc["id"], me["id"], targets, 5, name)
    bonus, dmg = _weapon(ch)
    t = ctx.combatant(targets[0])
    size = _size(t)
    res = _engine(ctx, me["id"], {"name": name, "effect": "damage", "dice": dmg, "hit": "attack", "attack_bonus": bonus,
                                  "damage_type": "slashing", "condition": "Launched", "adv": "attacked_adv", "rounds": 1}, targets, viewer)
    lines = [res["summary"]]
    r = res["targets"][0]
    if r["how"] in ("hit", "crit") and _has(ctx.combatant(t["id"]), "Launched"):
        stays = size in ("huge", "gargantuan")
        why = f"{t['name']} is too big to launch"
        if size == "large":
            made, total, how = roll_save(Roller(ctx, viewer), ctx.combatant(t["id"]), "str", _dc(ch), name)
            stays, why = made, f"{t['name']} makes a Strength save against the launch ({how})"
        if stays:
            _drop_named(ctx, t["id"], "Launched", "it wasn't launched")
            lines.append(why)
        else:
            _until_their_turn(ctx, res["cast_id"], t["id"])
            lines.append(f"{t['name']} is Launched: attacks against it have advantage until its next turn")
    if len(lines) > 1:
        ctx.log("spell", "↳ " + "; ".join(lines[1:]))
    return {"summary": "; ".join(lines), "cast": res, "spend": True, "cooldown": cd}


def _guard_break(ctx, me, ch, name, cd, targets, clones, data, viewer):
    from .movement import check_reach
    from .spells import clone_attacks
    targets = _need_targets(ctx, me, targets, name, one=True)
    mine = {k["id"]: k for k in _clones(ctx, me)}
    if len(clones) != 1 or clones[0] not in mine:
        raise F.ApiError(f"Pick the clone that charges ({name} uses up one clone)")
    k = mine[clones[0]]
    check_reach(ctx.conn, ctx.enc["id"], k["id"], targets, 30, f"{k['name']}'s charge")
    bonus, _ = _weapon(ch)
    own = [a["bonus"] for a in clone_attacks(k)]
    res = _engine(ctx, k["id"], {"name": name, "effect": "debuff", "dice": "", "hit": "attack", "attack_bonus": max([bonus] + own),
                                 "condition": "Staggered", "ac": -2, "rounds": 1}, targets, viewer)
    if res["targets"] and res["targets"][0]["how"] in ("hit", "crit"):
        _until_their_turn(ctx, res["cast_id"], targets[0])
    consume(ctx, k, name)
    line = f"{k['name']} is used up by {name}"
    ctx.log("spell", "↳ " + line)
    check_mirage(ctx, me["id"])
    return {"summary": res["summary"] + "; " + line, "cast": res, "spend": True, "cooldown": cd}


def _storm_wave(ctx, me, ch, name, cd, targets, clones, data, viewer):
    from .movement import check_reach
    prep = _has(me, SHEATHED)
    if not prep:  # turn 1: sheathe the blade (committed: no release this turn)
        if ctx.enc["current_id"] != me["id"]:
            raise F.ApiError(f"Sheathe for {name} on {me['name']}'s turn")
        _add_cond(ctx, me["id"], _cond(SHEATHED, note="Release Storm Wave on a later turn", prep_round=ctx.enc["round"],
                                       encounter_id=ctx.enc["id"], applied_round=ctx.enc["round"]))
        line = f"{me['name']} sheathes his blade: {name} is coming (release it on his next turn)"
        ctx.log("spell", line)
        return {"summary": line, "spend": True, "cooldown": 0}
    if prep.get("prep_round") == ctx.enc["round"]:
        raise F.ApiError(f"{name} can't be released the same turn it's sheathed — next turn")
    if ctx.enc["current_id"] != me["id"]:
        raise F.ApiError(f"Release {name} on {me['name']}'s turn")
    targets = _need_targets(ctx, me, targets, name, one=True)
    check_reach(ctx.conn, ctx.enc["id"], me["id"], targets, 10, name)
    used = _clones(ctx, me)[:MAX_CLONES]
    bonus, dmg = _weapon(ch)
    for k in used:  # they turn into the wave: gone before the hit, so none of them is counted twice
        consume(ctx, k, name)
    n = len(used)
    res = _engine(ctx, me["id"], {"name": name, "effect": "damage", "dice": _dice_times(dmg, 1 + n), "hit": "dex", "force_save": True,
                                  "save_half": True, "dc": _dc(ch), "damage_type": "slashing"}, targets, viewer)
    _drop_named(ctx, me["id"], SHEATHED, "released")
    _add_cond(ctx, me["id"], _cond("Storm Wave guard", note=f"takes {STORM_DR} less damage from each hit until his next turn", dr=STORM_DR,
                                   rounds_left=1, tick="start", tick_on=me["id"], encounter_id=ctx.enc["id"], auto_expire=True,
                                   applied_round=ctx.enc["round"]))
    line = f"{n} clone{'s' if n != 1 else ''} used up ({1 + n}× the weapon dice); {me['name']} takes {STORM_DR} less damage per hit until his next turn"
    ctx.log("spell", "↳ " + line)
    check_mirage(ctx, me["id"])
    return {"summary": res["summary"] + "; " + line, "cast": res, "spend": True, "cooldown": cd}


def _clone_calling(ctx, me, ch, name, cd, targets, clones, data, viewer):
    from .maps import _bump, _open_spots, map_dict
    if (me["statblock"] or {}).get("called_round") == ctx.enc["round"]:
        raise F.ApiError(f"{name} has been used this round")
    mine = _clones(ctx, me)
    pick = [k for k in mine if not clones or k["id"] in clones]
    if not pick:
        raise F.ApiError("No clones to call back")
    m = _map_and_tokens(ctx)
    line = f"{me['name']} uses {name}: " + ", ".join(k["name"] for k in pick) + " come back to him"
    if m is not None:
        md = map_dict(m)
        me_t = _tok(ctx, m, me["id"])
        if me_t is not None:
            taken = {(int(round(r["x"])), int(round(r["y"]))) for r in ctx.conn.execute(
                "SELECT x, y FROM map_tokens WHERE map_id = ? AND combatant_id NOT IN (%s)" % ",".join("?" * len(pick)),
                (m["id"], *[k["id"] for k in pick]))}
            for dx in range(me_t["size"]):
                for dy in range(me_t["size"]):
                    taken.add((int(me_t["x"]) + dx, int(me_t["y"]) + dy))
            spots = _open_spots(md, taken, me_t["x"], me_t["y"], len(pick))
            for k, (x, y) in zip(pick, spots):
                ctx.conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE map_id = ? AND combatant_id = ?",
                                 (x, y, now_iso(), m["id"], k["id"]))
            _bump(ctx.conn, m["id"])
    sb = dict(me["statblock"] or {}, called_round=ctx.enc["round"])
    ctx.conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), me["id"]))
    ctx.log("move", line + " (no action; their HP stays as it is)")
    return {"summary": line, "spend": False, "cooldown": 0}


def _chain_attack(ctx, me, ch, name, cd, targets, clones, data, viewer):
    targets = _need_targets(ctx, me, targets, name)
    mine = _clones(ctx, me)
    if not mine:
        raise F.ApiError(f"{name} needs clones around the enemies")
    m = _map_and_tokens(ctx)
    bodies = [me] + mine
    toks = {b["id"]: _tok(ctx, m, b["id"]) for b in bodies + [ctx.combatant(t) for t in targets]} if m is not None else {}
    on_map = m is not None and all(toks.get(x) is not None for x in [me["id"]] + targets)
    who = {t: [] for t in targets}   # target -> attackers (each body at ONE target only)
    if on_map:
        for b in bodies:
            bt = toks.get(b["id"])
            if bt is None:
                continue
            near = [t for t in targets if _next_to(bt, toks[t])]
            if near:
                near.sort(key=lambda t: len(who[t]))  # spread them out: the least-attacked one first
                who[near[0]].append(b)
    else:  # no battle map: the clones picked (or all), shared out in turn, and Yamato with the first
        pool = [k for k in mine if not clones or k["id"] in clones]
        who[targets[0]].append(me)
        for i, k in enumerate(pool):
            who[targets[i % len(targets)]].append(k)
    names = {t: ctx.combatant(t)["name"] for t in targets}
    alone = [names[t] for t in targets if not who[t]]
    if alone:
        raise F.ApiError(f"Surround them first: no clone (or Yamato) is right next to {', '.join(alone)}")
    if sum(len(v) for v in who.values()) < 2:
        raise F.ApiError(f"{name} needs at least two of you (Yamato and his clones) around the enemies")
    bonus, dmg = _weapon(ch)
    base = _dc(ch)
    parts, last = [], None
    for t in targets:
        n = min(4, len(who[t]))
        dc = base + min(4, 2 * (n - 1))
        res = _engine(ctx, me["id"], {"name": name, "effect": "damage", "dice": _dice_times(dmg, n), "hit": "dex", "force_save": True,
                                      "save_half": True, "dc": dc, "damage_type": "slashing"}, [t], viewer)
        last = res
        parts.append(f"{names[t]} ← {', '.join(b['name'] for b in who[t])} (DC {dc}): " + "; ".join(x["text"] for x in res["targets"]))
    summary = f"{me['name']} uses {name}: " + " | ".join(parts)
    return {"summary": summary, "cast": last, "spend": True, "cooldown": cd}


def _mirage(ctx, me, ch, name, cd, targets, clones, data, viewer):
    if _has(me, MIRAGE):  # ending it: free, any time
        _drop_named(ctx, me["id"], MIRAGE, f"{me['name']} ends it")
        return {"summary": f"{me['name']} ends {name}", "spend": False, "cooldown": 0}
    mine = _clones(ctx, me)
    if not mine:
        raise F.ApiError(f"{name} needs at least one clone to hide among")
    if ctx.enc["current_id"] != me["id"]:
        raise F.ApiError(f"{name} is used on {me['name']}'s turn")
    dc = mirage_dc(len(mine))
    _add_cond(ctx, me["id"], _cond(MIRAGE, note=f"looks just like his clones: Perception DC {dc} to pick out the real one",
                                   mirage=True, encounter_id=ctx.enc["id"], applied_round=ctx.enc["round"]))
    line = f"{me['name']} uses {name}: he blends in with his {len(mine)} clone{'s' if len(mine) != 1 else ''} (Perception DC {dc} to find the real one)"
    ctx.log("spell", line)
    return {"summary": line, "spend": True, "cooldown": cd}


def _perception_bonus(c):
    sb = c.get("statblock") or {}
    m = re.search(r"perception\s*([+-]\s*\d+)", str(sb.get("skills") or ""), re.I)
    if m:
        return int(m.group(1).replace(" ", ""))
    m = re.search(r"passive perception\s*(\d+)", str(sb.get("senses") or ""), re.I)
    return int(m.group(1)) - 10 if m else 0


def spot(ctx, me, enemy_id):
    """An enemy tries to pick out the real Yamato while Mirage is on: a flat Perception check."""
    if not _has(me, MIRAGE):
        raise F.ApiError(f"{me['name']} isn't hiding with Mirage")
    e = ctx.combatant(int(enemy_id))
    mine = _clones(ctx, me)
    dc = mirage_dc(len(mine))
    bonus = _perception_bonus(e)
    roll = random.SystemRandom().randint(1, 20)
    total = roll + bonus
    if total >= dc:
        line = f"{e['name']} spots the real {me['name']} (Perception {roll}{bonus:+d} = {total} vs DC {dc})"
    else:
        decoy = random.SystemRandom().choice(mine)["name"] if mine else "a clone"
        line = f"{e['name']} is fooled by the Mirage (Perception {roll}{bonus:+d} = {total} vs DC {dc}): it goes for {decoy} instead"
    ctx.log("roll", line)
    return line


# ---- endpoints ----------------------------------------------------------------------------------------

@bp.post("/api/encounters/<int:eid>/technique")
def api_dm_use(eid):
    """The DM uses one of a character's techniques. {caster_id, index, targets, clones, rider: {target id: push|slow|none|size}}"""
    from .auth import is_dm
    from .combat import Ctx, encounter_state
    if not is_dm():
        raise F.ApiError("Only the DM can do that here", status=403)
    data = request.get_json(silent=True) or {}
    out = None
    with tx() as conn:
        if claim_op(conn, data.get("op_id")):
            ctx = Ctx(conn, eid)
            out = use(ctx, ctx.combatant(int(data.get("caster_id") or 0)), data.get("index"), data, player=False)
    return jsonify(encounter_state(eid) | {"technique": out})


@bp.post("/api/encounters/<int:eid>/mirage-spot")
def api_dm_spot(eid):
    """{caster_id: Yamato, enemy_id}: the enemy tries to see through Mirage."""
    from .auth import is_dm
    from .combat import Ctx, encounter_state
    if not is_dm():
        raise F.ApiError("Only the DM can do that", status=403)
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        ctx = Ctx(conn, eid)
        line = spot(ctx, ctx.combatant(int(data.get("caster_id") or 0)), data.get("enemy_id"))
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
    return jsonify(encounter_state(eid) | {"spot": line})


@bp.post("/api/play/me/technique")
def api_me_use():
    """The player uses a technique. {index, targets, clones}. Clone Calling and ending Mirage work
    any time in the fight; the rest on their own turn."""
    from .combat import Ctx
    from .play import _own, _own_character
    from .rest import active_combatant
    ident, char_id = _own(None)
    data = request.get_json(silent=True) or {}
    data.pop("rider", None)  # knockback or slow is the DM's call (by size from the phone)
    with tx() as conn:
        if not claim_op(conn, data.get("op_id")):
            return jsonify({"character": _own_character(conn, char_id), "repeat": True})
        cb = active_combatant(conn, char_id)
        if cb is None:
            raise F.ApiError("Techniques are for fights, and there's no fight running")
        ctx = Ctx(conn, cb["encounter_id"], viewer=ident)
        out = use(ctx, ctx.combatant(cb["id"]), data.get("index"), data, player=True, viewer=ident)
    return jsonify({"character": _own_character(get_db(), char_id), "technique": out})
