"""Yamato's Echo Teleport: on his turn he picks one of his clones and teleports to where it stands.
The two swap places (the clone ends up where he was), like the Echo Knight's swap.

A sheet spell row with `clone_swap: true` is the ability. It uses no action; it costs 15 ft of his
movement this turn (the Echo Knight's price), and his movement afterwards is measured from the new
spot. A row cooldown (turns) still applies if the sheet gives it one.
"""
import json

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import claim_op, get_db, now_iso, tx

bp = Blueprint("echo", __name__)

COST_FT = 15


def _token(conn, map_id, cb_id, char_id=None):
    return conn.execute("SELECT * FROM map_tokens WHERE map_id = ? AND (combatant_id = ? OR (? IS NOT NULL AND character_id = ?)) "
                        "ORDER BY combatant_id = ? DESC LIMIT 1", (map_id, cb_id, char_id, char_id, cb_id)).fetchone()


def swap(ctx, me, clone, row_name):
    """Swap the caster's token with the clone's on the fight's battle map. Returns the log line."""
    from . import movement as MV
    from .maps import _bump, add_fx
    conn = ctx.conn
    m = MV._live_map(conn, ctx.enc["id"])
    if m is None:
        raise F.ApiError("There's no battle map for this fight, so there's nowhere to teleport to")
    a = _token(conn, m["id"], me["id"], me.get("character_id"))
    b = _token(conn, m["id"], clone["id"])
    if a is None or b is None:
        raise F.ApiError(f"{'You are' if a is None else clone['name'] + ' is'} not on the battle map")
    turn = MV.turn_info(conn, me["id"])
    if not turn or not turn["my_turn"]:
        raise F.ApiError("Teleport on your own turn", status=403)
    if turn["held"]:
        raise F.ApiError(f"You're {turn['held']} and can't teleport", status=403)
    if turn["left"] < COST_FT:
        raise F.ApiError(f"Teleporting costs {COST_FT} ft of movement and you only have {turn['left']} ft left this turn", status=403)
    ts = now_iso()
    conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (b["x"], b["y"], ts, a["id"]))
    conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (a["x"], a["y"], ts, b["id"]))
    # the walk so far is spent, plus the teleport's 15 ft; more walking is measured from the new spot
    row = MV._row(conn, me["id"])
    done = MV._turn(row)
    done["spent"] = done.get("spent", 0) + done.get("ft", 0) + COST_FT
    done["ft"] = 0
    done["from"] = [b["x"], b["y"]]
    MV._save(conn, row, done)
    md = dict(m)
    try:
        md["dungeon"] = json.loads(md.get("dungeon") or "null")
    except ValueError:
        md["dungeon"] = None
    if md.get("dungeon"):  # a made-up map: he sees around his new spot
        from .dungeon_maps import look_around
        look_around(conn, m["id"])
    s = a["size"] or 1
    add_fx(m["id"], {"name": row_name, "kind": "buff", "type": "force", "from": [round(a["x"] + s / 2, 2), round(a["y"] + s / 2, 2)],
                     "to": [[round(b["x"] + s / 2, 2), round(b["y"] + s / 2, 2)]], "how": ["auto"], "area": None, "style": "arcane"})
    _bump(conn, m["id"])
    return f"{me['name']} uses {row_name}: teleports to {clone['name']}'s spot and they swap places ({COST_FT} ft of movement)"


@bp.post("/api/play/me/teleport")
def api_me_teleport():
    """The player teleports to one of their clones. {spell: index of the clone_swap row, clone: clone's combatant id}"""
    from .combat import Ctx, start_cooldown
    from .play import _own, _own_character
    from .rest import active_combatant
    from .rules import cooldown_left, spell_info
    from .spells import my_clones, record, snapshot
    ident, char_id = _own(None)
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        me_row = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
        try:
            row = (me_row.get("spells") or [])[int(data.get("spell"))]
        except (TypeError, ValueError, IndexError):
            raise F.ApiError("That ability isn't on your sheet any more")
        sp = spell_info(row)
        if not row.get("clone_swap"):
            raise F.ApiError(f"{sp['name']} doesn't teleport you")
        cb = active_combatant(conn, char_id)
        if cb is None:
            raise F.ApiError("Teleporting to a clone is for fights, and there's no fight running")
        clones, _fight = my_clones(conn, char_id)
        k = next((k for k in clones if k["id"] == data.get("clone")), None)
        if k is None:
            raise F.ApiError("That clone isn't in the fight any more", status=403)
        if not claim_op(conn, data.get("op_id")):
            return jsonify({"character": _own_character(conn, char_id), "repeat": True})
        ctx = Ctx(conn, cb["encounter_id"])
        me = ctx.combatant(cb["id"])
        if sp["cooldown"] and cooldown_left(me_row["conditions"], sp["name"], ctx.enc["id"]):
            raise F.ApiError(f"{sp['name']} is still recharging")
        snap = snapshot(ctx)
        line = swap(ctx, me, k, sp["name"])
        if sp["cooldown"]:
            start_cooldown(ctx, me["id"], sp["name"], sp["cooldown"])
        ctx.log("move", line)
        record(ctx, snap)
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["id"]))
    return jsonify({"character": _own_character(get_db(), char_id), "teleport": {"name": sp["name"], "clone": k["name"]}})
