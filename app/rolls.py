"""Dice rolls: authoritative results, persistent history, visibility.

The server rolls; the browser only animates the saved result. A request
carries an op_id, so a double-click or a retry after a dropped connection
returns the roll that was already made instead of rolling again.

Visibility: public (everyone at the table), dm (the roller and the DM),
private (only the roller).
"""
import json
import re

from flask import Blueprint, jsonify, request

from . import dice
from . import fields as F
from .auth import current_identity
from .campaigns import active_campaign
from .db import get_db, new_uid, now_iso, tx
from .rules import ABILITIES, ABILITY_NAMES, SKILLS, ability_mod, derived, is_healing, spell_expression, spell_info

bp = Blueprint("rolls", __name__, url_prefix="/api")

SKILL_LABEL = {k: label for k, label, _ in SKILLS}
VISIBILITY = ("public", "dm", "private")
MODES = ("normal", "advantage", "disadvantage")


AC_NOTE = re.compile(r"\s*\(AC \d+\)|\s*vs AC \d+")


def roll_dict(row, viewer=None):
    d = dict(row)
    d["result"] = json.loads(d["result"])
    d.pop("op_id", None)
    if viewer and viewer.get("role") == "player":  # players never see a target's AC (older rolls still say "Hit (AC 12)")
        d["outcome"] = AC_NOTE.sub("", d.get("outcome") or "")
        d["label"] = AC_NOTE.sub("", d.get("label") or "")
    if viewer:
        d["mine"] = (viewer["role"] == "dm" and d["roller_kind"] == "dm") or (
            viewer["role"] == "player" and d["player_id"] == viewer.get("id"))
    return d


def _signed(n):
    """Modifier suffix for an expression: '+3', '-1', or '' for zero."""
    return "" if n == 0 else (f"+{n}" if n > 0 else str(n))


def _character(conn, char_id):
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        raise F.NotFound("Character not found")
    return F.decode_row(row, F.CHARACTER)


def build_check(conn, check):
    """Turn a named check into (expression, label, kind, subject, ids).
    Modifiers come from the saved character/stat block, never from the client."""
    t = check.get("type")
    key = check.get("key")
    if check.get("combatant_id"):
        cb = conn.execute("SELECT * FROM combatants WHERE id = ?", (int(check["combatant_id"]),)).fetchone()
        if cb is None:
            raise F.NotFound("Combatant not found")
        if cb["character_id"]:
            check = dict(check, character_id=cb["character_id"], combatant_id=None)
            expr, label, kind, subject, ids = build_check(conn, check)
            ids.update(combatant_id=cb["id"], encounter_id=cb["encounter_id"])
            return expr, label, kind, subject, ids
        block = json.loads(cb["statblock"] or "{}")
        ids = {"combatant_id": cb["id"], "encounter_id": cb["encounter_id"], "character_id": None}
        if t == "initiative":
            return f"1d20{_signed(cb['init_mod'])}", "Initiative", "initiative", cb["name"], ids
        if t in ("save", "ability") and key in ABILITIES:
            mod = ability_mod((block.get("abilities") or {}).get(key, 10))
            noun = "save" if t == "save" else "check"
            return f"1d20{_signed(mod)}", f"{ABILITY_NAMES[key]} {noun}", t, cb["name"], ids
        raise F.ApiError("That roll isn't available for this enemy")

    if not check.get("character_id"):
        raise F.ApiError("Choose a character for this roll")
    ch = _character(conn, int(check["character_id"]))
    d = derived(ch)
    ids = {"character_id": ch["id"]}
    name = ch["name"]
    if t == "ability" and key in ABILITIES:
        return f"1d20{_signed(d['mods'][key])}", f"{ABILITY_NAMES[key]} check", "ability", name, ids
    if t == "save" and key in ABILITIES:
        return f"1d20{_signed(d['saves'][key])}", f"{ABILITY_NAMES[key]} save", "save", name, ids
    if t == "skill" and key in SKILL_LABEL:
        return f"1d20{_signed(d['skills'][key])}", f"{SKILL_LABEL[key]} check", "skill", name, ids
    if t == "initiative":
        return f"1d20{_signed(d['initiative'])}", "Initiative", "initiative", name, ids
    if t == "death":
        return "1d20", "Death save", "death", name, ids
    if t == "spell_attack":
        if not d["spell"]:
            raise F.ApiError("Set a spellcasting ability on the Spells tab first")
        return f"1d20{_signed(d['spell']['attack'])}", "Spell attack", "attack", name, ids
    if t == "spell":
        try:
            sp = spell_info((ch.get("spells") or [])[int(key)])
        except (TypeError, ValueError, IndexError):
            raise F.ApiError("That spell no longer exists — the sheet may have changed")
        if sp["effect"] not in ("damage", "heal") or not sp["dice"]:
            raise F.ApiError(f"{sp['name']} has no dice to roll — set what it does and its dice on the Spells tab")
        expr = spell_expression(sp["dice"], d["mods"][d["spell"]["ability"]] if d["spell"] else None)
        if expr is None:
            raise F.ApiError(f"{sp['name']} uses mod — set a spellcasting ability on the Spells tab first")
        if sp["effect"] == "heal":
            return expr, f"{sp['name']} healing", "heal", name, ids
        return expr, f"{sp['name']} damage", "damage", name, ids
    if t in ("attack", "damage"):
        attacks = ch.get("attacks") or []
        try:
            atk = attacks[int(key)]
        except (TypeError, ValueError, IndexError):
            raise F.ApiError("That attack no longer exists — the sheet may have changed")
        atk_name = (atk.get("name") or "Attack").strip() or "Attack"
        if t == "attack":
            bonus = dice.attack_bonus(str(atk.get("bonus", "")))
            if bonus is None:
                raise F.ApiError(f"{atk_name} has no attack bonus (like +5) in its Atk / DC column")
            return f"1d20{_signed(bonus)}", f"{atk_name} attack", "attack", name, ids
        expr = dice.damage_expression(str(atk.get("damage", "")))
        if not expr:
            raise F.ApiError(f"{atk_name} has no damage dice (like 1d8+3) in its damage column")
        dtype = str(atk.get("damage", "")).replace(expr, "").strip()
        if is_healing(atk):
            return expr, f"{atk_name} healing", "heal", name, ids
        return expr, f"{atk_name} damage" + (f" ({dtype})" if dtype else ""), "damage", name, ids
    raise F.ApiError("Unknown roll type")


def with_effects(conn, ids, check_type, expr, label, mode):
    """What the roller's effects add: Bless +1d4 / Bane -1d4 on attacks and saves,
    Divine Favor on damage, and disadvantage on attacks while poisoned, frightened..."""
    from .rules import attack_mode, roll_mods, save_mode, with_mods
    if check_type not in ("attack", "spell_attack", "save", "damage", "spell"):
        return expr, label, mode
    if ids.get("character_id"):
        row = conn.execute("SELECT conditions FROM characters WHERE id = ?", (ids["character_id"],)).fetchone()
    elif ids.get("combatant_id"):
        row = conn.execute("SELECT conditions FROM combatants WHERE id = ?", (ids["combatant_id"],)).fetchone()
    else:
        return expr, label, mode
    conds = json.loads(row["conditions"] or "[]") if row else []
    if check_type in ("damage", "spell"):
        mods = roll_mods(conds, "dmg_mod") if check_type == "damage" else []
    else:
        mods = roll_mods(conds)
    if mods and len(with_mods(expr, mods)) <= dice.MAX_LENGTH:
        expr = with_mods(expr, mods)
        label = f"{label} ({', '.join(f'{n} {m}' for m, n in mods)})"
    if check_type in ("attack", "spell_attack"):
        auto, why = attack_mode(conds)
        if auto != "normal":
            mode = auto if mode == "normal" else ("normal" if mode != auto else mode)
            label = f"{label} — {auto} ({', '.join(why)})"
    return expr, label, mode


def _row_mult(conn, check):
    """The damage multiplier for this roll: the sheet row's Damage × (an attack that
    doubles itself), times any stance on the roller (Reckless)."""
    from .combat import dmg_mult, stance_mult
    from .rules import effect_mult
    if check.get("type") not in ("damage", "spell"):
        return 1
    char_id = check.get("character_id")
    if not char_id and check.get("combatant_id"):
        row = conn.execute("SELECT character_id FROM combatants WHERE id = ?", (int(check["combatant_id"]),)).fetchone()
        char_id = row["character_id"] if row else None
    if not char_id:
        return 1
    row = conn.execute("SELECT attacks, conditions FROM characters WHERE id = ?", (int(char_id),)).fetchone()
    if row is None:
        return 1
    mult = effect_mult(json.loads(row["conditions"] or "[]"))
    if check.get("type") == "damage":
        try:
            r = json.loads(row["attacks"] or "[]")[int(check.get("key"))]
            mult *= dmg_mult(r) if stance_mult(r) == 1 else 1
        except (TypeError, ValueError, IndexError):
            pass
    return mult


def _is_a_move(conn, check, ids):
    """Rolling to hit is making a move (and so is the damage of a move with no to-hit roll).
    Only counts in a running fight, on the roller's own turn."""
    from .rest import active_combatant
    t = check.get("type")
    if t not in ("attack", "spell_attack", "damage"):
        return False
    if not ids.get("combatant_id") and ids.get("character_id"):
        cb = active_combatant(conn, ids["character_id"])
        if cb is None:
            return False
        ids["combatant_id"], ids["encounter_id"] = cb["id"], cb["encounter_id"]
    if not ids.get("combatant_id"):
        return False
    enc = conn.execute("SELECT e.status, e.current_id, e.id FROM encounters e JOIN combatants c ON c.encounter_id = e.id WHERE c.id = ?",
                       (ids["combatant_id"],)).fetchone()
    if enc is None or enc["status"] != "active" or enc["current_id"] != ids["combatant_id"]:
        return False
    ids["encounter_id"] = enc["id"]
    if t == "damage" and ids.get("character_id"):
        row = conn.execute("SELECT attacks FROM characters WHERE id = ?", (ids["character_id"],)).fetchone()
        try:
            atk = json.loads(row["attacks"] or "[]")[int(check.get("key"))]
        except (TypeError, ValueError, IndexError):
            return False
        return not str(atk.get("bonus") or "").strip()
    return t != "damage"


OFF_TURN_ROLLS = ("initiative", "save", "death")  # what a player may roll while it's someone else's turn


def player_off_turn(conn, char_id, t=None):
    """In a running fight a player rolls only on their own turn (initiative, saves and death
    saves excepted). Raises when this roll has to wait."""
    from .rest import active_combatant
    cb = active_combatant(conn, char_id) if char_id else None
    if cb is None or t in OFF_TURN_ROLLS:
        return None
    enc = conn.execute("SELECT status, current_id FROM encounters WHERE id = ?", (cb["encounter_id"],)).fetchone()
    if enc["status"] == "active" and enc["current_id"] != cb["id"]:
        raise F.ApiError("It's not your turn yet — you can " + ("attack" if t in ("attack", "damage", "spell_attack", "spell") else "roll")
                         + " when your turn comes round", status=403)
    return cb


def _player_turn_rules(conn, viewer, check):
    """In a running fight a player rolls (and attacks) only on their own turn, and a move
    that's recharging can't be used. Returns (combatant id, move, turns) when this roll uses
    a move with a cooldown, so it starts recharging."""
    from .rules import cooldown_left, parse_cooldown
    t = check.get("type")
    char_id = int(check["character_id"])
    cb = player_off_turn(conn, char_id, t)
    if cb is None:
        return None
    if t not in ("attack", "damage"):
        return None
    ch = _character(conn, char_id)
    try:
        row = (ch.get("attacks") or [])[int(check.get("key"))]
    except (TypeError, ValueError, IndexError):
        return None
    turns = parse_cooldown(row)
    uses = t == "attack" or not str(row.get("bonus") or "").strip()  # the to-hit roll, or the damage of a move with no to-hit
    if not turns or not uses:
        return None
    name = (row.get("name") or "Attack").strip() or "Attack"
    left = cooldown_left(ch.get("conditions"), name, cb["encounter_id"])
    if left:
        raise F.ApiError(f"{name} is recharging — ready after {max(1, left - 1)} more of your turns", status=400)
    return cb["id"], name, turns


def outcome_for(kind, result):
    nat = result.get("natural")
    if kind == "death":
        if nat == 20:
            return "Natural 20 — regain 1 HP"
        if nat == 1:
            return "Natural 1 — counts as two failures"
        return "Success" if result["total"] >= 10 else "Failure"
    if nat == 20:
        return "Critical hit!" if kind == "attack" else "Natural 20"
    if nat == 1:
        return "Natural 1"
    return ""


def save_roll(conn, viewer, campaign_id, result, *, label, kind, subject="", ids=None, visibility="public",
              op_id=None, outcome=""):
    """Insert a roll inside the caller's transaction and return its id."""
    ids = ids or {}
    cur = conn.execute(
        """INSERT INTO rolls (uid, op_id, campaign_id, roller_kind, player_id, roller_name, character_id, combatant_id,
           encounter_id, subject, label, kind, expression, mode, visibility, result, total, outcome, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (new_uid(), op_id, campaign_id, viewer["role"], viewer.get("id") if viewer["role"] == "player" else None,
         viewer["name"], ids.get("character_id"), ids.get("combatant_id"), ids.get("encounter_id"), subject, label,
         kind, result["expression"], result["mode"], visibility, json.dumps(result), result["total"], outcome, now_iso()))
    return cur.lastrowid


def visible_clause(viewer):
    if viewer["role"] == "dm":
        return "(r.visibility IN ('public', 'dm') OR r.roller_kind = 'dm')", []
    return "(r.campaign_id = ? AND (r.visibility = 'public' OR r.player_id = ?))", [viewer["campaign_id"], viewer["id"]]


@bp.post("/rolls")
def api_roll():
    viewer = current_identity()
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "normal")
    if mode not in MODES:
        raise F.ApiError("mode must be normal, advantage or disadvantage")
    visibility = data.get("visibility", "public")
    if visibility not in VISIBILITY:
        raise F.ApiError("visibility must be public, dm or private")
    op_id = str(data.get("op_id") or "")[:80] or None
    conn = get_db()
    if op_id:
        existing = conn.execute("SELECT * FROM rolls WHERE op_id = ?", (op_id,)).fetchone()
        if existing:
            return jsonify({"roll": roll_dict(existing, viewer), "repeat": True})

    if viewer["role"] == "player":
        campaign_id = viewer["campaign_id"]
    else:
        campaign_id = data.get("campaign_id")
        if campaign_id is None:
            camp = active_campaign()
            campaign_id = camp["id"] if camp else None

    check = data.get("check")
    ids = {"character_id": None, "combatant_id": None, "encounter_id": None}
    subject = ""
    if check:
        if not isinstance(check, dict):
            raise F.ApiError("check must be an object")
        if viewer["role"] == "player":
            if check.get("combatant_id") or not check.get("character_id") or int(check["character_id"]) != viewer.get("character_id"):
                raise F.ApiError("Players can only roll for their own character", status=403)
        expr, label, kind, subject, got = build_check(conn, check)
        ids.update(got)
        expr, label, mode = with_effects(conn, got, check.get("type"), expr, label, mode)
        used = _player_turn_rules(conn, viewer, check) if viewer["role"] == "player" else None
        if data.get("label"):
            label = str(data["label"])[:120]
    else:
        expr = data.get("expression")
        label = str(data.get("label") or "")[:120]
        kind = data.get("kind") if data.get("kind") in ("damage", "heal", "attack", "save", "custom") else "custom"
        subject = str(data.get("subject") or "")[:120]
        if viewer["role"] == "player":
            player_off_turn(conn, viewer.get("character_id"), "save" if kind == "save" else None)
    if viewer["role"] == "dm" and data.get("encounter_id"):
        ids["encounter_id"] = int(data["encounter_id"])
    if ids.get("character_id") and campaign_id is not None:
        row = conn.execute("SELECT campaign_id FROM characters WHERE id = ?", (ids["character_id"],)).fetchone()
        if row and row["campaign_id"] != campaign_id:
            campaign_id = row["campaign_id"]
    try:
        result = dice.roll(expr, mode=mode, crit=bool(data.get("crit")) and kind == "damage")
    except dice.DiceError as e:
        raise F.ApiError(str(e))
    mult = _row_mult(conn, check) if check and kind == "damage" else 1
    if mult > 1:  # Reckless: the rolled damage is doubled
        result["multiplier"], result["total"] = mult, result["total"] * mult
        label = f"{label} — {'doubled' if mult == 2 else '×' + str(mult)}"
    if data.get("crit") and kind == "damage":
        label = (label + " — critical").strip(" —")
    outcome = outcome_for(kind, result)
    apply_init = bool(data.get("apply_initiative")) and kind == "initiative"
    if apply_init and viewer["role"] != "dm":
        raise F.ApiError("Only the DM can set initiative", status=403)

    with tx() as conn:
        probe = dict(ids)
        is_move = bool(check) and _is_a_move(conn, check, probe)
        if is_move:  # two actions a turn, whether the player or the DM rolls it
            from .movement import check_hero_action
            check_hero_action(conn, probe["combatant_id"], label or "that")
        if op_id and conn.execute("SELECT 1 FROM rolls WHERE op_id = ?", (op_id,)).fetchone():
            row = conn.execute("SELECT * FROM rolls WHERE op_id = ?", (op_id,)).fetchone()
            return jsonify({"roll": roll_dict(row, viewer), "repeat": True})
        roll_id = save_roll(conn, viewer, campaign_id, result, label=label, kind=kind, subject=subject, ids=ids,
                            visibility=visibility, op_id=op_id, outcome=outcome)
        if check and viewer["role"] == "player" and used:
            from .combat import Ctx, start_cooldown
            cb_id, move, turns = used
            ctx = Ctx(conn, conn.execute("SELECT encounter_id FROM combatants WHERE id = ?", (cb_id,)).fetchone()["encounter_id"])
            start_cooldown(ctx, cb_id, move, turns)
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["id"]))
        if apply_init:
            _apply_initiative(conn, ids, result["total"], result)
        if is_move:
            from .combat import Ctx, used_a_move
            ctx = Ctx(conn, probe["encounter_id"])
            used_a_move(ctx, probe["combatant_id"], label)
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["id"]))
    row = get_db().execute("SELECT * FROM rolls WHERE id = ?", (roll_id,)).fetchone()
    return jsonify({"roll": roll_dict(row, viewer)}), 201


def _apply_initiative(conn, ids, total, result):
    """Explicit 'roll and set initiative' from the combat screen."""
    from .combat import Ctx, _resort
    cid = ids.get("combatant_id")
    if not cid:
        raise F.ApiError("Pick a combatant to set initiative for")
    enc_id = conn.execute("SELECT encounter_id FROM combatants WHERE id = ?", (cid,)).fetchone()["encounter_id"]
    ctx = Ctx(conn, enc_id)
    c = ctx.combatant(cid)
    d20 = next(r["value"] for t in result["terms"] if t["type"] == "dice" for r in t["rolls"] if r["kept"])
    conn.execute("UPDATE combatants SET init_roll = ? WHERE id = ?", (total, cid))
    ctx.log("initiative", f"{c['name']} rolled initiative: {total} (d20 {d20}{' ' + _signed(c['init_mod']) if c['init_mod'] else ''})")
    if ctx.settings["auto_sort"]:
        _resort(ctx)
    conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), enc_id))


@bp.get("/rolls")
def api_history():
    viewer = current_identity()
    clause, params = visible_clause(viewer)
    sql = f"SELECT r.* FROM rolls r WHERE {clause}"
    if viewer["role"] == "dm":
        cid = request.args.get("campaign_id", type=int)
        if cid is None:
            camp = active_campaign()
            cid = camp["id"] if camp else None
        sql += " AND (r.campaign_id = ? OR r.campaign_id IS NULL)"
        params.append(cid)
    after = request.args.get("after_id", type=int)
    if after:
        sql += " AND r.id > ?"
        params.append(after)
    for key in ("character_id", "encounter_id"):
        v = request.args.get(key, type=int)
        if v:
            sql += f" AND r.{key} = ?"
            params.append(v)
    limit = max(1, min(200, request.args.get("limit", 40, type=int)))
    sql += " ORDER BY r.id DESC LIMIT ?"
    params.append(limit)
    rows = get_db().execute(sql, params).fetchall()
    return jsonify({"rolls": [roll_dict(r, viewer) for r in rows]})


@bp.get("/rolls/<int:roll_id>")
def api_one(roll_id):
    viewer = current_identity()
    clause, params = visible_clause(viewer)
    row = get_db().execute(f"SELECT r.* FROM rolls r WHERE r.id = ? AND {clause}", [roll_id] + params).fetchone()
    if row is None:
        raise F.NotFound("Roll not found")
    return jsonify({"roll": roll_dict(row, viewer)})
