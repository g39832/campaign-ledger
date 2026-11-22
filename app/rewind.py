"""Time Reversal (Lux's Worldheart Fate Ring): right after a creature within 60 ft finishes its
turn, the ring's owner makes it take that turn again from where it started: its position, hit
points and everything it spent go back to how they were when its turn began.

The fight remembers how things stood at the start of each turn (in memory, like Undo last
action: a server restart forgets it). A sheet spell row with `rewind: true` is the ring; with
`per_rest` it's used once, then back after a long rest (Grayson's rule for limited magic items).
Players may use it only before the next creature has done anything; the DM any time during
that next creature's turn."""

import json

from flask import Blueprint, current_app, jsonify, request

from . import fields as F
from .db import claim_op, get_db, now_iso, tx

bp = Blueprint("rewind", __name__)

RANGE_FT = 60


def _store(eid):
    try:
        return current_app.extensions.setdefault("turn_rewind", {}).setdefault(eid, {})
    except RuntimeError:  # no app (a script): nothing to remember
        return {}


def turn_started(ctx, cid):
    """Called once a turn has started (after start-of-turn effects): remember how it all is,
    and the turn that just ended becomes the one the ring can take back."""
    from .spells import snapshot
    s = _store(ctx.enc["id"])
    prev = s.get("current")
    s["last"] = None
    if prev and prev["cid"] != cid:
        s["last"] = {"cid": prev["cid"], "snap": prev["snap"], "next_cid": cid,
                     "mark": ctx.conn.execute("SELECT MAX(id) FROM combat_log WHERE encounter_id = ?", (ctx.enc["id"],)).fetchone()[0] or 0}
    s["current"] = {"cid": cid, "snap": snapshot(ctx)}


def forget(eid):
    s = _store(eid)
    s.clear()


def ring_rows(ch):
    """The sheet's Time Reversal rows: [(index, spell_info)]."""
    from .rules import spell_info
    return [(i, spell_info(r)) for i, r in enumerate(ch.get("spells") or []) if isinstance(r, dict) and r.get("rewind")]


def _char(conn, char_id):
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    return F.decode_row(row, F.CHARACTER) if row else None


def offer(ctx, me, dm=False):
    """What the ring could do right now for this fighter: {index, name, target_id, target, ok, why}
    or None when they have no such item."""
    if not me.get("character_id"):
        return None
    ch = _char(ctx.conn, me["character_id"])
    rows = ring_rows(ch) if ch else []
    if not rows:
        return None
    index, sp = next(((i, s) for i, s in rows if not (s["per_rest"] and s["used"])), rows[0])
    out = {"index": index, "name": sp["name"], "target_id": None, "target": None, "ok": False, "why": ""}
    if sp["per_rest"] and sp["used"]:
        out["why"] = "used · back after a long rest"
        return out
    if ctx.enc["status"] != "active":
        out["why"] = "only in a running fight"
        return out
    last = _store(ctx.enc["id"]).get("last")
    if not last or ctx.enc["current_id"] != last["next_cid"]:
        out["why"] = "right after a creature ends its turn"
        return out
    who = next((c for c in ctx.combatants() if c["id"] == last["cid"]), None)
    if who is None:
        out["why"] = "that creature has left the fight"
        return out
    out.update(target_id=who["id"], target=who["name"])
    if me["status"] in ("dead", "unconscious") or (me["hp"] or 0) <= 0:
        out["why"] = f"{me['name']} is down"
        return out
    from .movement import distance_ft
    ft = distance_ft(ctx.conn, ctx.enc["id"], me["id"], who["id"]) if who["id"] != me["id"] else 0
    if ft is not None and ft > RANGE_FT:
        out["why"] = f"{who['name']} is {ft} ft away (it reaches {RANGE_FT} ft)"
        return out
    if not dm:
        acted = ctx.conn.execute("SELECT 1 FROM combat_log WHERE encounter_id = ? AND id > ? LIMIT 1",
                                 (ctx.enc["id"], last["mark"])).fetchone()
        if acted:
            out["why"] = "too late: the next turn has already started (ask the DM)"
            return out
    out["ok"] = True
    return out


def use(ctx, cb_id, dm=False):
    """Rewind the turn that just ended. Returns {target, name, summary}."""
    from .spells import restore
    me = ctx.combatant(int(cb_id))
    o = offer(ctx, me, dm)
    if o is None:
        raise F.ApiError(f"{me['name']} has no Time Reversal item")
    if not o["ok"]:
        raise F.ApiError(f"{o['name']}: {o['why']}")
    s = _store(ctx.enc["id"])
    last = s["last"]
    restore(ctx, last["snap"], keep_log=True)
    ctx.enc.update(dict(ctx.conn.execute("SELECT * FROM encounters WHERE id = ?", (ctx.enc["id"],)).fetchone()))
    # the ring is spent (after the restore, which puts sheets back as they were)
    ch = _char(ctx.conn, me["character_id"])
    rows = list(ch.get("spells") or [])
    sp = rows[o["index"]]
    if sp.get("per_rest"):
        rows[o["index"]] = dict(sp, used=True)
        ctx.conn.execute("UPDATE characters SET spells = ?, updated_at = ? WHERE id = ?", (json.dumps(rows), now_iso(), ch["id"]))
    s["current"] = {"cid": last["cid"], "snap": last["snap"]}
    s["last"] = None
    summary = (f"{me['name']} uses {o['name']}: time runs backwards — {o['target']} is back where its turn began, "
               f"with its hit points and everything it spent restored, and takes that turn again")
    ctx.log("spell", summary)
    from .maps import _bump
    for m in ctx.conn.execute("SELECT id FROM maps WHERE encounter_id = ?", (ctx.enc["id"],)).fetchall():
        _bump(ctx.conn, m["id"])
    return {"name": o["name"], "target": o["target"], "summary": summary}


def _run(eid, cb_id, op_id, dm):
    from .combat import Ctx
    from .spells import record, snapshot
    out = {}
    with tx() as conn:
        if claim_op(conn, op_id):
            ctx = Ctx(conn, eid)
            snap = snapshot(ctx)
            out = use(ctx, cb_id, dm)
            record(ctx, snap)  # the DM's Undo last action can take it back
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
            conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["campaign_id"]))
    return out


@bp.post("/api/encounters/<int:eid>/rewind")
def api_dm_rewind(eid):
    """The DM uses a hero's Time Reversal for them. {caster_id}"""
    from .combat import encounter_state
    data = request.get_json(silent=True) or {}
    try:
        cb_id = int(data.get("caster_id"))
    except (TypeError, ValueError):
        raise F.ApiError("Whose item is it?")
    out = _run(eid, cb_id, data.get("op_id"), dm=True)
    return jsonify(encounter_state(eid) | {"rewind": out or None})


@bp.post("/api/play/me/rewind")
def api_me_rewind():
    """The player uses their Time Reversal on the creature whose turn just ended."""
    from .play import _own, _own_character
    from .rest import active_combatant
    ident, char_id = _own(None)
    data = request.get_json(silent=True) or {}
    conn = get_db()
    cb = active_combatant(conn, char_id)
    if cb is None:
        raise F.ApiError("Time Reversal is for fights, and there's no fight running")
    out = _run(cb["encounter_id"], cb["id"], data.get("op_id"), dm=False)
    return jsonify({"character": _own_character(get_db(), char_id), "rewind": out or None})
