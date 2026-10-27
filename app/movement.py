"""A hero's turn in a fight, for players: they move only on their own turn and only as far
as their speed (twice that after Dash), and they get two actions (attacks, spells, Dash,
Disengage) plus Action Surge's extra ones. The DM can still move anyone and roll anything."""
import json
import math
import re

from . import fields as F

DEFAULT_SPEED = 30
ACTIONS_PER_TURN = 2


def speed_ft(conn, char_id):
    """The character's speed in feet, with speed boosts (Moni's magic item: ×2) on top."""
    row = conn.execute("SELECT speed, conditions FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        return DEFAULT_SPEED
    m = re.search(r"\d+", str(row["speed"] or ""))
    base = int(m.group()) if m else DEFAULT_SPEED
    mult = max([float(x.get("speed_mult") or 1) for x in json.loads(row["conditions"] or "[]")
                if isinstance(x, dict) and not x.get("expired")] or [1])
    return int(base * max(mult, 1))


def ft_per_square(md):
    return int(md.get("scale_value") or 5) if (md.get("scale_unit") or "ft") == "ft" else 5


def step_ft(md, x0, y0, x1, y1):
    """Feet from one spot to another: diagonals count as one square, like the measure tool."""
    squares = math.ceil(max(abs(x1 - x0), abs(y1 - y0)) - 1e-6)
    return max(0, squares) * ft_per_square(md)


def _row(conn, cb_id):
    return conn.execute("SELECT cb.id AS cb_id, cb.moved, cb.conditions, cb.character_id, e.id AS eid, e.status, e.current_id, e.round "
                        "FROM combatants cb JOIN encounters e ON e.id = cb.encounter_id WHERE cb.id = ?", (cb_id,)).fetchone()


def _turn(row):
    """What they've done this turn. It belongs to one round, so it starts over on their next turn."""
    try:
        done = json.loads(row["moved"] or "{}")
    except ValueError:
        done = {}
    return done if done.get("round") == row["round"] and row["current_id"] == row["cb_id"] else {}


def _save(conn, row, done):
    conn.execute("UPDATE combatants SET moved = ? WHERE id = ?", (json.dumps(dict(done, round=row["round"])), row["cb_id"]))


def fight_turn(conn, md, char_id):
    """The hero's place in the fight on this map, or None when they aren't in a running one.
    {cb_id, my_turn, speed, used, dash, left}"""
    if not md.get("encounter_id") or not char_id:
        return None
    hit = conn.execute("SELECT cb.id FROM combatants cb JOIN encounters e ON e.id = cb.encounter_id "
                       "WHERE e.id = ? AND e.status = 'active' AND cb.character_id = ?", (md["encounter_id"], char_id)).fetchone()
    if hit is None:
        return None
    row = _row(conn, hit["id"])
    mine = row["current_id"] == row["cb_id"]
    done = _turn(row)
    speed = speed_ft(conn, char_id)
    used = done.get("ft", 0)
    return {"cb_id": row["cb_id"], "my_turn": mine, "speed": speed, "used": used, "dash": bool(done.get("dash")),
            "left": max(0, speed * (2 if done.get("dash") else 1) - used) if mine else 0}


def check_move(conn, md, char_id, x0, y0, x1, y1):
    """Refuses a player's move that's out of turn or too far; records it otherwise."""
    turn = fight_turn(conn, md, char_id)
    if turn is None:
        return None
    if not turn["my_turn"]:
        raise F.ApiError("Wait for your turn to move", status=403)
    cost = step_ft(md, x0, y0, x1, y1)
    if cost > turn["left"]:
        raise F.ApiError(f"That's {cost} ft, and you have {turn['left']} ft of movement left this turn"
                         + ("" if turn["dash"] or turn["left"] else " (Dash for more)"), status=403, left=turn["left"])
    row = _row(conn, turn["cb_id"])
    _save(conn, row, dict(_turn(row), ft=turn["used"] + cost))
    return dict(turn, used=turn["used"] + cost, left=turn["left"] - cost)


# ---- actions ---------------------------------------------------------------------------

def actions(conn, cb_id):
    """{used, limit, left} for this turn, or None when it isn't their turn in a running fight."""
    row = _row(conn, cb_id)
    if row is None or row["status"] != "active" or row["current_id"] != row["cb_id"]:
        return None
    conds = conn.execute("SELECT conditions FROM characters WHERE id = ?", (row["character_id"],)).fetchone()["conditions"] \
        if row["character_id"] else row["conditions"]
    extra = sum(int(x.get("extra_total") or 0) for x in json.loads(conds or "[]")
                if isinstance(x, dict) and x.get("extra_moves") is not None and not x.get("expired")
                and x.get("encounter_id") in (None, row["eid"]))
    used = _turn(row).get("acts", 0)
    limit = ACTIONS_PER_TURN + extra
    return {"used": used, "limit": limit, "left": max(0, limit - used), "extra": extra}


def check_action(conn, cb_id, what="that"):
    """A player is about to use an action on their turn: refused when they're out of them."""
    a = actions(conn, cb_id)
    if a is not None and a["left"] <= 0:
        raise F.ApiError(f"You've used your {a['limit']} actions this turn — no more for {what} until your next turn"
                         + ("" if a["extra"] else " (Action Surge gives two more)"), status=403)
    return a


def spend_action(conn, cb_id):
    """An action was used on their own turn. Returns how many they've used now (None: not their turn)."""
    row = _row(conn, cb_id)
    if row is None or row["status"] != "active" or row["current_id"] != row["cb_id"]:
        return None
    done = _turn(row)
    done["acts"] = done.get("acts", 0) + 1
    _save(conn, row, done)
    return done["acts"]


def dash(conn, cb_id):
    """The Dash action: this turn's movement doubles. It uses one of their actions."""
    row = _row(conn, cb_id)
    if row["current_id"] != row["cb_id"]:
        raise F.ApiError("Dash is for your own turn", status=403)
    if _turn(row).get("dash"):
        raise F.ApiError("You've already dashed this turn")
    check_action(conn, cb_id, "Dash")
    spend_action(conn, cb_id)
    row = _row(conn, cb_id)
    _save(conn, row, dict(_turn(row), dash=True))
