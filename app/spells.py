"""Casting a spell in a fight, start to finish, on the server.

One request does what the table would do: spend the slot (upcasting adds the
spell's extra dice), drop the caster's old concentration, roll the spell's dice,
then for each target roll to hit against AC or have them roll their save against
the caster's DC, deal the damage (half on a save, changed by resistances and
vulnerabilities), heal, hand out temp HP, and leave the spell's lasting effect:
a condition, AC, a bonus or penalty to rolls (Bless, Bane), advantage, extra
damage, more max HP, damage or healing every turn, and a save each turn to end it.

Every roll is saved to the dice history so the tray animates it, every change is
in the combat log, and HP changes go through apply_hp so Undo HP works.

Effects live on the combatant's conditions list with these extra keys:
    ac, roll_mod, dmg_mod, adv, max_hp     what it changes while it lasts
    ongoing {dice, kind, type, save, dc}   rolled at the start of the bearer's turn
    save {ability, dc}                     rolled at the end of the bearer's turn; success ends it
    source {cast, caster, spell, conc}     which casting put it there
and a caster who concentrates carries a "Concentrating" effect with concentration = cast id.
"""
import json
import re
import uuid

from flask import Blueprint, jsonify, request

from . import dice
from . import fields as F
from . import spell_book
from .auth import current_identity
from .db import claim_op, get_db, now_iso, tx
from .rules import (ABILITIES, ABILITY_NAMES, ability_mod, active_effects, attack_mode, damage_multiplier, derived,
                    roll_mods, save_mode, spell_expression, spell_helps, spell_info, spell_lasts, with_mods)

bp = Blueprint("spells", __name__, url_prefix="/api")

DM = {"role": "dm", "name": "DM"}
SHORT = {a: ABILITY_NAMES[a] for a in ABILITIES}
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def ordinal(n):
    return ORDINAL.get(n, f"{n}th")


def _char(conn, char_id):
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        raise F.NotFound("Character not found")
    return F.decode_row(row, F.CHARACTER)


# ---- dice ------------------------------------------------------------------------

TERM = re.compile(r"([+-]?)\s*(\d*)d(\d+)|([+-]?)\s*(\d+)", re.I)


def scale_dice(text, times):
    """'1d6' x 2 -> '2d6', '1d4+1' x 3 -> '3d4+3' (upcasting: extra dice per slot level)."""
    out = []
    for m in TERM.finditer(text or ""):
        if m.group(3):
            out.append(f"{m.group(1) or '+'}{int(m.group(2) or 1) * times}d{m.group(3)}")
        else:
            out.append(f"{m.group(4) or '+'}{int(m.group(5)) * times}")
    s = "".join(out)
    return s[1:] if s.startswith("+") else s


def resolve(text, mod, name):
    """'1d8+mod' -> '1d8+3'. Raises a readable error when mod is used without a spellcasting ability."""
    expr = spell_expression(text, mod)
    if expr is None:
        raise F.ApiError(f"{name} uses mod — set a spellcasting ability on the Spells tab first")
    return expr.lstrip("+")


def spell_dice(sp, text, mod, slot):
    """The dice to roll for a spell cast with a slot: its dice, plus the upcast dice for
    every level above its own ('8d6' at 5th level with '1d6' upcast -> '8d6+2d6')."""
    expr = resolve(text, mod, sp["name"])
    if sp["upcast"] and slot and slot > sp["level"] > 0:
        expr += "+" + scale_dice(resolve(sp["upcast"], mod, sp["name"]), slot - sp["level"])
    return expr.replace("+-", "-")


class Roller:
    """Rolls for one cast (or one turn's effects) and keeps each roll for the dice history."""

    def __init__(self, ctx, viewer=None):
        self.ctx, self.viewer, self.ids = ctx, viewer or getattr(ctx, "viewer", None) or DM, []

    def roll(self, expr, label, *, mode="normal", crit=False):
        if re.fullmatch(r"-?\d+", expr):  # a flat amount: Heal's 70, Heroism's modifier
            n = int(expr)
            return {"terms": [{"type": "mod", "value": n}], "modifier": n, "total": n, "natural": None,
                    "expression": str(n), "mode": "normal"}
        try:
            return dice.roll(expr, mode=mode, crit=crit)
        except dice.DiceError as e:
            raise F.ApiError(f"{label}: {e}")

    def keep(self, result, label, kind, who, outcome=""):
        from .rolls import save_roll
        if kind in ("damage", "heal"):
            result = dict(result, applied=True)  # the spell already dealt it: the dice history mustn't offer to apply it again
        ids = {"encounter_id": self.ctx.enc["id"], "combatant_id": who["id"],
               "character_id": who["character_id"] if who.get("linked") else None}
        self.ids.append(save_roll(self.ctx.conn, self.viewer, self.ctx.enc["campaign_id"], result, label=label[:120], kind=kind,
                                  subject=who["name"], ids=ids, visibility="dm" if who.get("hidden") else "public",
                                  outcome=outcome[:200]))


# ---- who is casting, and against what --------------------------------------------------

def _prof_for_cr(cr):
    try:
        n = float(eval_cr(cr))
    except (TypeError, ValueError):
        return 2
    return 2 + max(0, int(n) - 1) // 4


def eval_cr(cr):
    s = str(cr or "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a) / int(b)
    return float(s) if s else 1


def caster_numbers(ctx, c):
    """{dc, attack, mod} for whoever casts. Characters: from the sheet (None when no
    spellcasting ability is set). Monsters: 'spell save DC 13, +5 to hit' in their stat
    block, otherwise worked out from their best mental ability and CR."""
    if c["linked"]:
        d = derived(_char(ctx.conn, c["character_id"]))
        if not d["spell"]:
            return {"dc": None, "attack": None, "mod": None}
        return {"dc": d["spell"]["dc"], "attack": d["spell"]["attack"], "mod": d["mods"][d["spell"]["ability"]]}
    sb = c["statblock"] or {}
    text = " ".join(str(sb.get(k) or "") for k in ("traits", "spells", "notes", "attacks"))
    mod = max(ability_mod((sb.get("abilities") or {}).get(a, 10)) for a in ("int", "wis", "cha"))
    prof = _prof_for_cr(sb.get("cr"))
    dc = re.search(r"spell save DC\s*(\d+)", text, re.I)
    atk = re.search(r"([+-]\s*\d+)\s*to hit with spell", text, re.I) or re.search(r"spell save DC\s*\d+\s*,\s*([+-]\s*\d+)\s*to hit", text, re.I)
    return {"dc": int(dc.group(1)) if dc else 8 + prof + mod,
            "attack": int(atk.group(1).replace(" ", "")) if atk else prof + mod, "mod": mod}


def save_bonus(ctx, t, ability):
    if t["linked"]:
        return derived(_char(ctx.conn, t["character_id"]))["saves"][ability]
    sb = t["statblock"] or {}
    text = " ".join(str(sb.get(k) or "") for k in ("traits", "notes"))
    m = re.search(r"saving throws?[^\n]*?\b" + ABILITY_NAMES[ability][:3] + r"[a-z]*\.?\s*([+-]\s*\d+)", text, re.I)
    if m:
        return int(m.group(1).replace(" ", ""))
    return ability_mod((sb.get("abilities") or {}).get(ability, 10))


def roll_save(roller, t, ability, dc, why):
    """The target rolls a saving throw. Returns (made it, total, text)."""
    mode, reason = save_mode(t["conditions"], ability)
    if mode == "auto_fail":
        return False, None, f"auto-fail, {reason}"
    mods = roll_mods(t["conditions"])
    expr = with_mods("1d20" + _signed(save_bonus(roller.ctx, t, ability)), mods)
    r = roller.roll(expr, why, mode=mode)
    made = r["total"] >= dc
    extra = "".join(f", {n}" for _m, n in mods) + (f", disadvantage: {reason}" if r["mode"] == "disadvantage" else "")
    text = f"{r['total']} vs DC {dc}{extra}"
    roller.keep(r, f"{SHORT[ability]} save — {why}", "save", t, ("Saved" if made else "Failed") + f" (DC {dc})")
    return made, r["total"], text


def _signed(n):
    return "" if not n else (f"+{n}" if n > 0 else str(n))


# ---- which spell -----------------------------------------------------------------------

def spell_from(ctx, caster, data):
    """The spell being cast, normalised: a row on the caster's sheet (spell: index), a
    monster's spell line as the browser read it (spell: {name, dice, ...}), or a spell
    from the book (book: name). A monster line that names a book spell ("Fireball",
    "Hold person DC 13") gets the book's details for anything the line doesn't say."""
    raw, extra = data.get("spell"), {}
    if isinstance(raw, int) and not isinstance(raw, bool) or (isinstance(raw, str) and raw.isdigit()):
        if not caster["linked"]:
            raise F.ApiError("That spell isn't on a character sheet")
        spells = _char(ctx.conn, caster["character_id"]).get("spells") or []
        try:
            row = spells[int(raw)]
        except IndexError:
            raise F.ApiError("That spell isn't on the sheet any more — the sheet may have changed")
        return spell_info(row), extra
    if isinstance(raw, dict):
        spec = {k: v for k, v in raw.items() if v not in (None, "")}
        base = dict(spell_book.find(spec.get("name")) or {})
        base.update(spec)
        if "attack_bonus" in spec:
            try:
                extra["attack"] = max(-20, min(30, int(spec["attack_bonus"])))
            except (TypeError, ValueError):
                pass
        if "dc" in spec:
            try:
                extra["dc"] = max(1, min(40, int(spec["dc"])))
            except (TypeError, ValueError):
                pass
        return spell_info(base), extra
    if data.get("book"):
        row = spell_book.find(data["book"])
        if row is None:
            raise F.ApiError("That spell isn't in the spell list")
        return spell_info(row), extra
    raise F.ApiError("Pick a spell to cast")


def spend_slot(ctx, caster, sp, slot, free):
    """Spend the spell slot (characters who track slots on their sheet). Returns the
    level it's cast at. Cantrips and free casts don't use a slot."""
    level = sp["level"]
    if slot not in (None, ""):
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            raise F.ApiError("Slot level must be a number")
        if not level <= slot <= 9:
            raise F.ApiError(f"{sp['name']} is a level {level} spell — cast it with a slot of level {level} or higher")
    else:
        slot = level
    if level == 0:
        return 0, False
    if free or not caster["linked"]:
        return slot, False
    row = ctx.conn.execute("SELECT spell_slots FROM characters WHERE id = ?", (caster["character_id"],)).fetchone()
    slots = json.loads(row["spell_slots"] or "{}")
    if not any(isinstance(v, dict) and (v.get("max") or 0) > 0 for v in slots.values()):
        return slot, False  # this sheet doesn't track slots
    cur = slots.get(str(slot)) or {}
    if (cur.get("max") or 0) - (cur.get("used") or 0) <= 0:
        have = [int(k) for k, v in slots.items() if isinstance(v, dict) and int(k) >= level and (v.get("max") or 0) > (v.get("used") or 0)]
        hint = f" Level {', '.join(map(str, sorted(have)))} slots are left." if have else " No slots that can cast it are left."
        raise F.ApiError(f"{caster['name']} has no level {slot} slots left.{hint}", needs_free=True)
    cur["used"] = (cur.get("used") or 0) + 1
    slots[str(slot)] = cur
    ctx.conn.execute("UPDATE characters SET spell_slots = ?, updated_at = ? WHERE id = ?", (json.dumps(slots), now_iso(), caster["character_id"]))
    return slot, True


# ---- effects ------------------------------------------------------------------------

def effect_for(ctx, sp, caster, cast_id, nums, slot):
    """The lasting effect this spell leaves on whoever it lands on."""
    name = sp["condition"] or sp["name"]
    cond = {"id": uuid.uuid4().hex[:12], "name": name, "note": sp["name"] if name != sp["name"] else "",
            "rounds_left": sp["rounds"], "tick": "start", "tick_on": caster["id"], "encounter_id": ctx.enc["id"],
            "auto_expire": True, "expired": False, "applied_round": ctx.enc["round"],
            "source": {"cast": cast_id, "caster": caster["id"], "spell": sp["name"], "conc": sp["concentration"]}}
    for k in ("ac", "max_hp"):
        if sp[k]:
            cond[k] = sp[k]
    for k in ("roll_mod", "dmg_mod"):
        if sp[k]:
            cond[k] = resolve(sp[k], nums["mod"], sp["name"])
    if sp["adv"]:
        cond["adv"] = sp["adv"]
    if sp["ongoing"]:
        on = {"dice": resolve(sp["ongoing"], nums["mod"], sp["name"]), "kind": sp["ongoing_kind"],
              "type": sp["ongoing_type"] or sp["damage_type"]}
        if sp["ongoing_save"] and sp["hit"] in ABILITIES and nums["dc"]:
            on.update(save=sp["hit"], dc=nums["dc"], half=True)
        cond["ongoing"] = on
    if sp["repeat_save"] and sp["hit"] in ABILITIES and nums["dc"]:
        cond["save"] = {"ability": sp["hit"], "dc": nums["dc"]}
    if sp["escape"] and nums["dc"]:
        cond["save"] = {"ability": sp["escape"], "dc": nums["dc"]}
        cond["note"] = (cond["note"] + " · " if cond["note"] else "") + f"can't move; {SHORT[sp['escape']]} save DC {nums['dc']} at the end of its turn to break free"
    return cond


def put_effect(ctx, target, cond):
    """Put an effect on someone. Casting the same spell again refreshes it; a different
    source of the same condition (already Prone) is left alone. Returns 'added',
    'refreshed' or 'already'."""
    from .combat import drop_conditions
    t = ctx.combatant(target["id"])
    same = [x for x in t["conditions"] if str(x.get("name", "")).lower() == cond["name"].lower() and not x.get("expired")]
    if same and not any((x.get("source") or {}).get("spell") == cond["source"]["spell"] for x in same):
        return "already"
    how = "added"
    if same:
        drop_conditions(ctx, t, {x["id"] for x in same}, quiet=True)
        t = ctx.combatant(target["id"])
        how = "refreshed"
    v = {"conditions": t["conditions"] + [cond]}
    if cond.get("max_hp"):
        v.update(max_hp=t["max_hp"] + cond["max_hp"], hp=t["hp"] + cond["max_hp"])
    ctx.set_vitals(t, **v)
    return how


def start_concentration(ctx, caster, sp, cast_id):
    from .combat import end_concentration
    end_concentration(ctx, caster["id"], f"now concentrating on {sp['name']}")
    c = ctx.combatant(caster["id"])
    cond = {"id": uuid.uuid4().hex[:12], "name": "Concentrating", "note": sp["name"], "rounds_left": sp["rounds"],
            "tick": "start", "tick_on": caster["id"], "encounter_id": ctx.enc["id"], "auto_expire": True, "expired": False,
            "applied_round": ctx.enc["round"], "concentration": cast_id, "spell": sp["name"]}
    ctx.set_vitals(c, conditions=c["conditions"] + [cond])


def spell_over(ctx, cast_id):
    """Once nobody has any effect from a concentration spell left (they all saved, or
    the effects were removed), the caster isn't concentrating on it any more."""
    if not cast_id:
        return
    everyone = ctx.combatants()
    if any((x.get("source") or {}).get("cast") == cast_id for o in everyone for x in o["conditions"]):
        return
    for o in everyone:
        mark = next((x for x in o["conditions"] if x.get("concentration") == cast_id), None)
        if mark:
            ctx.set_vitals(o, conditions=[x for x in o["conditions"] if x.get("id") != mark["id"]])
            ctx.log("spell", f"{mark.get('spell') or 'The spell'} has ended — {o['name']} is no longer concentrating")


def change_ground(ctx, sp, data):
    """Mend Earth and the like: raise solid rock over the squares it covers (not under
    anyone standing there), or mend broken ground back to plain earth. Returns a line for the log."""
    from .maps import MENDABLE, _bump, _cells, map_dict
    row = ctx.conn.execute("SELECT * FROM maps WHERE id = ?", (int(data["map_id"]),)).fetchone()
    if row is None or row["campaign_id"] != ctx.enc["campaign_id"]:
        raise F.ApiError("That map isn't in this campaign")
    m = map_dict(row)
    cells = _cells(data, m)
    terrain, changed = m["terrain"], 0
    if sp["terrain"] == "rock":
        taken = set()
        for t in ctx.conn.execute("SELECT x, y, size FROM map_tokens WHERE map_id = ? AND kind NOT IN ('marker', 'trap')", (m["id"],)):
            for dx in range(t["size"]):
                for dy in range(t["size"]):
                    taken.add(f"{int(round(t['x'])) + dx},{int(round(t['y'])) + dy}")
        for x, y in cells:
            k = f"{x},{y}"
            if k not in taken and terrain.get(k) != "rock":
                terrain[k] = "rock"
                changed += 1
        what = f"raises solid rock over {changed} square{'s' if changed != 1 else ''}"
    else:
        for x, y in cells:
            k = f"{x},{y}"
            if terrain.get(k) in MENDABLE:
                terrain.pop(k)
                changed += 1
        what = f"mends {changed} square{'s' if changed != 1 else ''} of ground"
    ctx.conn.execute("UPDATE maps SET terrain = ? WHERE id = ?", (json.dumps(terrain), m["id"]))
    _bump(ctx.conn, m["id"])
    return what


def concentration_check(ctx, c, damage):
    """A concentrating caster took damage: Constitution save, DC 10 or half the damage.
    Dropping to 0 HP ends it outright."""
    from .combat import end_concentration
    mark = next((x for x in active_effects(c["conditions"]) if x.get("concentration")), None)
    if not mark or damage <= 0:
        return
    if c["hp"] == 0:
        end_concentration(ctx, c["id"], "dropped to 0 HP")
        return
    if not ctx.settings.get("auto_concentration", True):
        ctx.log("spell", f"{c['name']} took {damage} damage while concentrating on {mark['spell']} — Constitution save, DC {max(10, damage // 2)}")
        return
    dc = max(10, damage // 2)
    made, total, text = roll_save(Roller(ctx), c, "con", dc, f"concentration on {mark['spell']}")
    if made:
        ctx.log("spell", f"{c['name']} keeps concentrating on {mark['spell']} (Constitution save {text})")
    else:
        end_concentration(ctx, c["id"], f"failed the Constitution save, {text}")


def on_turn(ctx, cid, phase):
    """Effects that happen on the bearer's own turn: damage or healing at the start
    (Moonbeam, Heroism, Regenerate), a save at the end to shake it off (Hold Person)."""
    from .combat import apply_hp, drop_conditions
    try:
        c = ctx.combatant(cid)
    except F.NotFound:
        return
    if c["status"] in ("dead",):
        return
    roller = Roller(ctx)
    for cond in active_effects(c["conditions"]):
        src = (cond.get("source") or {}).get("spell") or cond["name"]
        if phase == "start" and isinstance(cond.get("ongoing"), dict):
            on = cond["ongoing"]
            c = ctx.combatant(cid)
            r = roller.roll(on["dice"], f"{src} on {c['name']}")
            amount, why = max(0, r["total"]), ""
            if on["kind"] == "damage":
                if on.get("save"):
                    made, _t, text = roll_save(roller, c, on["save"], on["dc"], src)
                    if made:
                        amount //= 2
                        why = f" (saved, {text}: half)"
                    else:
                        why = f" (failed the save, {text})"
                if not c["linked"]:
                    mult, word = damage_multiplier(c["statblock"], on.get("type"))
                    if mult != 1:
                        amount = int(amount * mult)
                        why += f" — {word} {on['type']}"
            roller.keep(r, f"{src} — start of {c['name']}'s turn", "heal" if on["kind"] != "damage" else "damage", c,
                        f"{amount} {'healing' if on['kind'] == 'heal' else 'temp HP' if on['kind'] == 'temp' else (on.get('type') or '') + ' damage'}".replace("  ", " "))
            ctx.log("spell", f"{src}: {c['name']} " + {"damage": f"takes {amount}{' ' + on['type'] if on.get('type') else ''} damage",
                                                         "heal": f"regains {amount} HP", "temp": f"gets {amount} temp HP"}[on["kind"]]
                    + why + " at the start of their turn")
            apply_hp(ctx, cid, {"op": on["kind"] if on["kind"] != "damage" else "damage", "amount": amount}, src)
        if phase == "end" and isinstance(cond.get("save"), dict):
            c = ctx.combatant(cid)
            if not any(x.get("id") == cond["id"] for x in c["conditions"]):
                continue
            made, _t, text = roll_save(roller, c, cond["save"]["ability"], cond["save"]["dc"], f"end {cond['name']}")
            if made:
                drop_conditions(ctx, c, {cond["id"]}, quiet=True)
                ctx.log("spell", f"{c['name']} shakes off {cond['name']} ({SHORT[cond['save']['ability']]} save {text})")
                spell_over(ctx, (cond.get("source") or {}).get("cast"))
            else:
                ctx.log("spell", f"{c['name']} is still {cond['name']} ({SHORT[cond['save']['ability']]} save {text})")
    return roller.ids


# ---- casting -----------------------------------------------------------------------------

def cast(ctx, caster_id, data, viewer=None):
    """Cast one spell on the chosen targets. Returns what happened, for the screen."""
    from .combat import apply_hp, start_cooldown
    caster = ctx.combatant(int(caster_id))
    sp, extra = spell_from(ctx, caster, data)
    targets = data.get("targets")
    if not isinstance(targets, list) or len(targets) > 50 or not all(isinstance(t, int) and not isinstance(t, bool) for t in targets):
        raise F.ApiError("Choose who the spell is cast on")
    targets = list(dict.fromkeys(targets))
    if not sp["kind"]:
        raise F.ApiError(f"{sp['name']} is only notes — set what it does (damage, healing, buff or debuff) on the Spells tab")
    if sp["terrain"]:
        if not data.get("map_id") or not isinstance(data.get("cells"), list):
            raise F.ApiError(f"Aim {sp['name']} on the battle map to choose where it goes")
        if not (sp["dice"] or spell_lasts(sp) or sp["temp_hp"]):
            targets = []  # it only changes the ground
    elif not targets and not sp["concentration"]:
        raise F.ApiError(f"Pick who {sp['name']} is cast on")
    if sp["targets"] and len(targets) > sp["targets"]:
        raise F.ApiError(f"{sp['name']} reaches at most {sp['targets']} {'creature' if sp['targets'] == 1 else 'creatures'}")
    people = [ctx.combatant(t) for t in targets]
    nums = caster_numbers(ctx, caster)
    nums.update(extra)
    helps = spell_helps(sp)
    rule = ctx.settings.get("roll_to_hit", True)
    lands = "auto" if helps else "attack" if sp["hit"] == "attack" or (rule and sp["hit"] in ABILITIES) else "save" if sp["hit"] else "auto"
    if lands == "save" and not nums["dc"]:
        raise F.ApiError(f"Set {caster['name']}'s spellcasting ability on the Spells tab so the save DC is known")
    attack_bonus = nums["attack"] if nums["attack"] is not None else 0
    if sp["dice"]:
        resolve(sp["dice"], nums["mod"], sp["name"])  # fail early on 'mod' without an ability
    slot, spent = spend_slot(ctx, caster, sp, data.get("slot"), bool(data.get("free")))
    cast_id = uuid.uuid4().hex[:12]
    roller = Roller(ctx, viewer)
    if sp["concentration"]:
        start_concentration(ctx, caster, sp, cast_id)

    def amount_expr(text):
        return spell_dice(sp, text, nums["mod"], slot)

    at = f" at {ordinal(slot)} level" if slot and slot > sp["level"] else ""
    by = f"{sp['name']}, {caster['name']}"
    shared = None  # one roll for everyone (area spells, heals); attack spells roll per target
    if sp["dice"] and lands != "attack":
        expr = amount_expr(sp["dice"])
        if sp["kind"] == "damage":
            expr = with_mods(expr, roll_mods(caster["conditions"], "dmg_mod"))
        shared = roller.roll(expr, sp["name"])
        word = "healing" if sp["kind"] == "heal" else ((sp["damage_type"] + " ") if sp["damage_type"] else "") + "damage"
        roller.keep(shared, f"{sp['name']}{at} — {word}", "heal" if sp["kind"] == "heal" else "damage", caster, f"{max(0, shared['total'])} {word}")
    temp = None
    if sp["temp_hp"]:
        temp = roller.roll(amount_expr(sp["temp_hp"]), sp["name"])
        roller.keep(temp, f"{sp['name']}{at} — temp HP", "heal", caster, f"{max(0, temp['total'])} temp HP")

    lines, results = [], []
    melee = bool(re.search(r"\btouch\b|\bmelee\b", sp["notes"], re.I))
    for t in people:
        t = ctx.combatant(t["id"])
        res = {"id": t["id"], "name": t["name"], "how": "auto", "amount": None, "effect": None, "text": ""}
        landed, crit, how, half = True, False, "", False
        if lands == "attack":
            mode, why = attack_mode(caster["conditions"], t["conditions"], melee)
            mods = roll_mods(caster["conditions"])
            r = roller.roll(with_mods("1d20" + _signed(attack_bonus), mods), sp["name"], mode=mode)
            nat = r["natural"]
            crit = nat == 20
            landed = crit or (nat != 1 and r["total"] >= t["ac"])
            how = f"{r['total']} vs AC {t['ac']}" + (", natural 20" if crit else ", natural 1" if nat == 1 else "") \
                + "".join(f", {n}" for _m, n in mods) + (f", {r['mode']}: {', '.join(why)}" if r["mode"] != "normal" else "")
            roller.keep(r, f"{sp['name']} attack on {t['name']}", "attack", caster,
                        "Critical hit!" if crit else ("Hit" if landed else "Miss") + f" (AC {t['ac']})")
            res.update(how="crit" if crit else "hit" if landed else "miss", roll=r["total"], vs=t["ac"])
        elif lands == "save":
            made, total, how = roll_save(roller, t, sp["hit"], nums["dc"], sp["name"])
            res.update(how="saved" if made else "failed", roll=total, vs=nums["dc"])
            if made:
                landed, half = False, sp["kind"] == "damage" and sp["save_half"]
        parts = []
        if sp["kind"] == "damage" and sp["dice"] and (landed or half):
            if lands == "attack":
                expr = with_mods(amount_expr(sp["dice"]), roll_mods(caster["conditions"], "dmg_mod"))
                d = roller.roll(expr, sp["name"], crit=crit)
                amount = max(0, d["total"])
                word = ((sp["damage_type"] + " ") if sp["damage_type"] else "") + "damage"
                roller.keep(d, f"{sp['name']}{at} — {word}" + (" — critical" if crit else ""), "damage", caster, f"{amount} {word} to {t['name']}")
            else:
                amount = max(0, shared["total"])
            if half:
                amount //= 2
            note = ""
            if not t["linked"]:
                mult, word = damage_multiplier(t["statblock"], sp["damage_type"])
                if mult != 1:
                    amount, note = int(amount * mult), f", {word} {sp['damage_type']}"
            apply_hp(ctx, t["id"], {"op": "damage", "amount": amount}, by)
            res["amount"] = amount
            parts.append(f"{amount}{' ' + sp['damage_type'] if sp['damage_type'] else ''} damage" + (" (half)" if half else "") + note)
        if sp["kind"] == "heal" and shared is not None:
            amount = max(0, shared["total"])
            apply_hp(ctx, t["id"], {"op": "heal", "amount": amount}, by)
            res["amount"] = amount
            parts.append(f"heals {amount}")
        if temp is not None and landed:
            apply_hp(ctx, t["id"], {"op": "temp", "amount": max(0, temp["total"])}, by)
            parts.append(f"{max(0, temp['total'])} temp HP")
        if spell_lasts(sp) and landed:
            cond = effect_for(ctx, sp, caster, cast_id, nums, slot)
            got = put_effect(ctx, t, cond)
            res["effect"], res["effect_how"] = cond["name"], got
            parts.append({"added": cond["name"], "refreshed": cond["name"] + " (renewed)", "already": f"already {cond['name']}"}[got]
                         + (f" {cond['ac']:+d} AC" if cond.get("ac") and got != "already" else ""))
        verdict = {"attack": "hit" if landed else "missed", "save": "failed the save" if res["how"] == "failed" else "saved"}.get(lands, "")
        if crit:
            verdict = "CRIT"
        res["text"] = f"{t['name']}" + (f" {verdict}" if verdict else "") + (f" ({how})" if how else "") + (" — " + ", ".join(parts) if parts else "")
        lines.append(res["text"])
        results.append(res)
    if sp["terrain"]:
        lines.insert(0, change_ground(ctx, sp, data))
    from .combat import used_a_move
    used_a_move(ctx, caster["id"], sp["name"])
    if sp["cooldown"]:
        start_cooldown(ctx, caster["id"], sp["name"], sp["cooldown"])
    slot_word = f" with a level {slot} slot" if spent else at
    move = isinstance(data.get("spell"), dict) and bool(data["spell"].get("move"))  # Grapple: a move, not a spell
    head = f"{caster['name']} {'uses' if move else 'casts'} {sp['name']}{slot_word}" + (" (concentration)" if sp["concentration"] else "")
    ctx.log("spell", head + (": " + "; ".join(lines) if lines else ""))
    return {"spell": sp["name"], "kind": sp["kind"], "caster": caster["name"], "slot": slot if sp["level"] else 0,
            "spent": spent, "lands": lands, "targets": results, "summary": head + (": " + "; ".join(lines) if lines else ""),
            "rolls": roller.ids, "concentration": sp["concentration"], "move": move}


def _rolls_for(ids, viewer):
    from .rolls import roll_dict
    if not ids:
        return []
    conn = get_db()
    rows = conn.execute(f"SELECT * FROM rolls WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    return [roll_dict(r, viewer) for r in rows]


@bp.post("/encounters/<int:eid>/cast")
def api_cast(eid):
    """The DM casts a spell for a combatant. {caster_id, spell: sheet index | spell line,
    book: name, targets: [combatant ids], slot, free}"""
    from .combat import Ctx, encounter_state
    viewer = current_identity()
    data = request.get_json(silent=True) or {}
    if data.get("caster_id") is None:
        raise F.ApiError("Who is casting?")
    out = {}
    with tx() as conn:
        ctx = Ctx(conn, eid)
        if claim_op(conn, data.get("op_id")):
            out = cast(ctx, data["caster_id"], data, viewer)
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
            conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["campaign_id"]))
    if out:
        out["rolls"] = _rolls_for(out["rolls"], viewer)
    return jsonify(encounter_state(eid) | {"cast": out or None})


@bp.get("/spell-book")
def api_book():
    return jsonify(spell_book.book())
