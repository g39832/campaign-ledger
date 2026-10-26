"""Rests, hit dice, and HP changes made outside the combat screen.

Every HP change here goes through combat.compute_hp, so the rules (temp HP
first, falling unconscious at 0, waking up when healed) are the same as in
combat. When the character is in a running encounter, the change goes through
that encounter instead, so it is logged there and the DM's Undo HP covers it.
"""
import uuid

from flask import Blueprint, jsonify, request

from . import dice
from . import fields as F
from .auth import current_identity
from .campaigns import get_campaign
from .characters import _touch_encounters, get_character
from .combat import Ctx, apply_hp, compute_hp
from .db import get_db, now_iso, tx
from .rolls import roll_dict, save_roll
from .rules import ability_mod, knocked_prone, long_rest_changes, parse_hit_dice

bp = Blueprint("rest", __name__, url_prefix="/api")

VITALS = {"hp": "current_hp", "max_hp": "max_hp", "temp_hp": "temp_hp", "status": "status",
          "death_successes": "death_successes", "death_failures": "death_failures"}


def active_combatant(conn, char_id):
    row = conn.execute(
        "SELECT c.id, c.encounter_id FROM combatants c JOIN encounters e ON e.id = c.encounter_id "
        "WHERE c.character_id = ? AND e.status = 'active' ORDER BY e.updated_at DESC LIMIT 1", (char_id,)).fetchone()
    return row


def change_character_hp(conn, char_id, data, by=None):
    """Apply damage / heal / temp / set to a character. Inside a running
    encounter it is logged and undoable there. Returns a short log line."""
    cb = active_combatant(conn, char_id)
    if cb:
        ctx = Ctx(conn, cb["encounter_id"])
        apply_hp(ctx, cb["id"], data, by=by)
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), cb["encounter_id"]))
        return
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        raise F.NotFound("Character not found")
    camp = get_campaign(row["campaign_id"])
    before = {k: row[col] for k, col in VITALS.items()}
    v, _label, _note = compute_hp(before, data.get("op"), data, name=row["name"], linked=True,
                                  max_hp=row["max_hp"], temp_stacking=camp["settings"]["combat"]["temp_hp_stacking"])
    if v != before:
        sets = ", ".join(f"{col} = ?" for col in VITALS.values())
        conn.execute(f"UPDATE characters SET {sets}, updated_at = ? WHERE id = ?",
                     [v[k] for k in VITALS] + [now_iso(), char_id])
        if before["hp"] > 0 and v["hp"] == 0:
            prone = knocked_prone(F.from_db(F.CHARACTER["conditions"], row["conditions"]))
            if prone is not None:
                conn.execute("UPDATE characters SET conditions = ? WHERE id = ?", (F.to_db(F.CHARACTER["conditions"], prone), char_id))
        _touch_encounters(conn, char_id)


def put_effect(conn, char_id, name, rounds=None, ac=0, note="", caster_char_id=None):
    """Put an effect (Bless, Shield of Faith +2 AC...) on a character. Inside a
    running encounter it goes through that encounter, so it is logged there and
    counts down on the caster's turn. Returns False if they already have it."""
    from .combat import add_conditions
    cb = active_combatant(conn, char_id)
    if cb:
        ctx = Ctx(conn, cb["encounter_id"])
        caster = conn.execute("SELECT id FROM combatants WHERE encounter_id = ? AND character_id = ?",
                              (cb["encounter_id"], caster_char_id)).fetchone() if caster_char_id else None
        added, _ = add_conditions(ctx, [cb["id"]], name, rounds, ac, ctx.combatant(caster["id"]) if caster else None, note)
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), cb["encounter_id"]))
        return bool(added)
    row = conn.execute("SELECT conditions FROM characters WHERE id = ?", (char_id,)).fetchone()
    conds = F.from_db(F.CHARACTER["conditions"], row["conditions"]) or []
    if any(x.get("name", "").lower() == name.lower() and not x.get("expired") for x in conds):
        return False
    cond = {"id": uuid.uuid4().hex[:12], "name": name, "note": note, "rounds_left": rounds, "expired": False}
    if ac:
        cond["ac"] = ac
    conn.execute("UPDATE characters SET conditions = ?, updated_at = ? WHERE id = ?",
                 (F.to_db(F.CHARACTER["conditions"], conds + [cond]), now_iso(), char_id))
    _touch_encounters(conn, char_id)
    return True


# ---- death saves -----------------------------------------------------------------

def ally_bonus(conn, char_id):
    """House rule: a downed hero gets a bonus on death saves while a hero who's
    still standing is right next to them (touching, diagonals count) on the
    fight's battle map. Returns (bonus, names of the allies beside them)."""
    from .maps import tokens_for
    cb = active_combatant(conn, char_id)
    if cb is None:
        return 0, []
    camp = conn.execute("SELECT campaign_id FROM encounters WHERE id = ?", (cb["encounter_id"],)).fetchone()
    bonus = get_campaign(camp["campaign_id"])["settings"]["combat"].get("ally_death_save_bonus", 2) or 0
    if not bonus:
        return 0, []
    for m in conn.execute("SELECT id FROM maps WHERE encounter_id = ?", (cb["encounter_id"],)):
        toks = tokens_for(conn, m["id"])
        me = next((t for t in toks if t["character_id"] == char_id), None)
        if me is None:
            continue
        def gap(a, b):
            ax, ay, bx, by = round(a["x"]), round(a["y"]), round(b["x"]), round(b["y"])
            dx = max(bx - (ax + a["size"] - 1), ax - (bx + b["size"] - 1), 0)
            dy = max(by - (ay + a["size"] - 1), ay - (by + b["size"] - 1), 0)
            return max(dx, dy)
        allies = [t["display"] for t in toks if t is not me and t["kind"] in ("pc", "npc") and t["character_id"]
                  and (t["hp"] or 0) > 0 and t["status"] not in ("dead", "unconscious", "stable") and not t["hidden"]
                  and gap(me, t) <= 1]
        if allies:
            return bonus, allies
    return 0, []


def death_save(conn, viewer, char_id, op_id=None):
    """Roll a death saving throw and mark it: 10 or more is a success, a natural 1
    is two failures, a natural 20 brings them back with 1 HP. Three successes:
    stable. Three failures: dead. An ally beside them adds the campaign's bonus."""
    if op_id:
        old = conn.execute("SELECT * FROM rolls WHERE op_id = ?", (op_id,)).fetchone()
        if old:
            return old["id"]
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    if ch["current_hp"] > 0:
        raise F.ApiError(f"{ch['name']} isn't at 0 HP, so there's no death save to make")
    if ch["status"] == "dead":
        raise F.ApiError(f"{ch['name']} has died")
    if ch["status"] == "stable":
        raise F.ApiError(f"{ch['name']} is stable and doesn't need death saves")
    bonus, allies = ally_bonus(conn, char_id)
    result = dice.roll("1d20" + (f"+{bonus}" if bonus else ""))
    nat, total = result["natural"], result["total"]
    s, f = ch["death_successes"], ch["death_failures"]
    if nat == 20:
        outcome = "Natural 20 — back on their feet with 1 HP!"
    elif nat == 1:
        f, outcome = min(3, f + 2), "Natural 1 — two failures"
    elif total >= 10:
        s, outcome = min(3, s + 1), "Success"
    else:
        f, outcome = min(3, f + 1), "Failure"
    status = "dead" if f >= 3 else "stable" if s >= 3 else ch["status"]
    if nat != 20:
        outcome += f" ({s} success{'es' if s != 1 else ''}, {f} failure{'s' if f != 1 else ''})"
        outcome += " — dead" if status == "dead" else " — stable" if status == "stable" else ""
    label = "Death save" + (f" +{bonus} ({', '.join(allies)} beside them)" if bonus else "")
    roll_id = save_roll(conn, viewer, ch["campaign_id"], result, label=label, kind="death", subject=ch["name"],
                        ids={"character_id": char_id}, op_id=op_id, outcome=outcome)
    if nat == 20:
        change_character_hp(conn, char_id, {"op": "heal", "amount": 1}, by="natural 20 on a death save")
        return roll_id
    cb = active_combatant(conn, char_id)
    if cb:
        ctx = Ctx(conn, cb["encounter_id"])
        ctx.set_vitals(ctx.combatant(cb["id"]), death_successes=s, death_failures=f, status=status)
        ctx.log("death", f"{ch['name']}: {label.lower()} — {total}. {outcome}")
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), cb["encounter_id"]))
    else:
        conn.execute("UPDATE characters SET death_successes = ?, death_failures = ?, status = ?, updated_at = ? WHERE id = ?",
                     (s, f, status, now_iso(), char_id))
        _touch_encounters(conn, char_id)
    return roll_id


@bp.post("/characters/<int:char_id>/death-save")
def api_death_save(char_id):
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        roll_id = death_save(conn, current_identity(), char_id, data.get("op_id"))
    row = get_db().execute("SELECT * FROM rolls WHERE id = ?", (roll_id,)).fetchone()
    return jsonify({"roll": roll_dict(row, current_identity()), "character": get_character(char_id)})


@bp.post("/combatants/<int:cid>/death-save")
def api_combatant_death_save(cid):
    from .combat import encounter_state
    data = request.get_json(silent=True) or {}
    cb = get_db().execute("SELECT encounter_id, character_id FROM combatants WHERE id = ?", (cid,)).fetchone()
    if cb is None:
        raise F.NotFound("Combatant not found")
    if not cb["character_id"]:
        raise F.ApiError("Monsters don't make death saves — at 0 HP they're defeated")
    with tx() as conn:
        roll_id = death_save(conn, current_identity(), cb["character_id"], data.get("op_id"))
    row = get_db().execute("SELECT * FROM rolls WHERE id = ?", (roll_id,)).fetchone()
    return jsonify(encounter_state(cb["encounter_id"]) | {"roll": roll_dict(row, current_identity())})


def spend_hit_die(conn, viewer, char_id, sides=None, op_id=None):
    """Roll one hit die + Constitution modifier and heal by the result."""
    if op_id:
        old = conn.execute("SELECT * FROM rolls WHERE op_id = ?", (op_id,)).fetchone()
        if old:
            return old["id"]
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    pools = parse_hit_dice(ch["hit_dice"])
    if not pools:
        raise F.ApiError("Set this character's hit dice first (for example 5d10) on the sheet.")
    total = sum(n for n, _ in pools)
    if ch["hit_dice_used"] >= total:
        raise F.ApiError("No hit dice left. A long rest gets half of them back.")
    sizes = [s for _, s in pools]
    sides = int(sides) if sides else max(sizes)
    if sides not in sizes:
        raise F.ApiError(f"{ch['name']} doesn't have d{sides} hit dice")
    con = ability_mod((ch["abilities"] or {}).get("con", 10))
    result = dice.roll(f"1d{sides}" + (f"{con:+d}" if con else ""))
    heal = max(0, result["total"])
    left = total - ch["hit_dice_used"] - 1
    roll_id = save_roll(conn, viewer, ch["campaign_id"], result, label="Hit die (short rest)", kind="heal",
                        subject=ch["name"], ids={"character_id": char_id}, op_id=op_id,
                        outcome=f"Heals {heal} · {left} hit {'die' if left == 1 else 'dice'} left")
    conn.execute("UPDATE characters SET hit_dice_used = hit_dice_used + 1 WHERE id = ?", (char_id,))
    if heal:
        change_character_hp(conn, char_id, {"op": "heal", "amount": heal},
                            by=f"hit die{', ' + viewer['name'] if viewer['role'] == 'player' else ''}")
    return roll_id


def long_rest(conn, char_id):
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    changes = long_rest_changes(ch)
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(f"UPDATE characters SET {sets}, updated_at = ? WHERE id = ?",
                 [F.to_db(F.CHARACTER[k], v) for k, v in changes.items()] + [now_iso(), char_id])
    _touch_encounters(conn, char_id)
    return ch["name"]


# ---- DM endpoints -------------------------------------------------------------

@bp.post("/characters/<int:char_id>/hp")
def api_hp(char_id):
    """Damage / heal / temp / set from the character sheet (DM)."""
    data = request.get_json(silent=True) or {}
    get_character(char_id)
    with tx() as conn:
        change_character_hp(conn, char_id, data, by="sheet")
    return jsonify({"character": get_character(char_id)})


@bp.post("/characters/<int:char_id>/hit-die")
def api_hit_die(char_id):
    data = request.get_json(silent=True) or {}
    get_character(char_id)
    viewer = current_identity()
    with tx() as conn:
        roll_id = spend_hit_die(conn, viewer, char_id, data.get("sides"), data.get("op_id"))
    row = get_db().execute("SELECT * FROM rolls WHERE id = ?", (roll_id,)).fetchone()
    return jsonify({"roll": roll_dict(row, viewer), "character": get_character(char_id)})


@bp.post("/characters/<int:char_id>/long-rest")
def api_long_rest(char_id):
    get_character(char_id)
    with tx() as conn:
        long_rest(conn, char_id)
    return jsonify({"character": get_character(char_id)})


@bp.post("/campaigns/<int:cid>/long-rest")
def api_party_rest(cid):
    data = request.get_json(silent=True) or {}
    get_campaign(cid)
    with tx() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM characters WHERE campaign_id = ? AND archived = 0 AND kind = 'pc'", (cid,))]
        if data.get("character_ids"):
            wanted = {int(i) for i in data["character_ids"]}
            ids = [i for i in ids if i in wanted]
        names = [long_rest(conn, i) for i in ids]
    if not names:
        raise F.ApiError("No player characters to rest")
    return jsonify({"rested": names})
