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
    return conn.execute("SELECT cb.id AS cb_id, cb.name, cb.moved, cb.conditions, cb.statblock, cb.character_id, e.id AS eid, e.status, e.current_id, e.round "
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


def monster_speed(row):
    """A monster's walking speed from its stat block ("30 ft., fly 60 ft." is 30), with speed boosts."""
    try:
        sb = json.loads(row["statblock"] or "{}")
    except ValueError:
        sb = {}
    m = re.search(r"\d+", str(sb.get("speed") or ""))
    base = int(m.group()) if m else DEFAULT_SPEED
    mult = max([float(x.get("speed_mult") or 1) for x in json.loads(row["conditions"] or "[]")
                if isinstance(x, dict) and not x.get("expired")] or [1])
    return int(base * max(mult, 1))


def turn_info(conn, cb_id):
    """{cb_id, name, my_turn, speed, used, dash, left} for someone in a running fight, or None."""
    row = _row(conn, cb_id)
    if row is None or row["status"] != "active":
        return None
    mine = row["current_id"] == row["cb_id"]
    done = _turn(row)
    speed = speed_ft(conn, row["character_id"]) if row["character_id"] else monster_speed(row)
    held = held_by(conn, row)
    if held:
        speed = 0  # Grappled, Restrained, down...: they can't move at all
    used = done.get("ft", 0)
    return {"cb_id": row["cb_id"], "name": row["name"], "my_turn": mine, "speed": speed, "used": used, "dash": bool(done.get("dash")),
            "left": max(0, speed * (2 if done.get("dash") else 1) - used) if mine else 0, "held": held}


def held_by(conn, row):
    """What keeps someone in place (speed 0), or None: a condition like Grappled, or being down."""
    from .play import SPEED_ZERO
    if row["character_id"]:
        ch = conn.execute("SELECT conditions, status FROM characters WHERE id = ?", (row["character_id"],)).fetchone()
        conds, status = ch["conditions"], ch["status"]
    else:
        st = conn.execute("SELECT status FROM combatants WHERE id = ?", (row["cb_id"],)).fetchone()
        conds, status = row["conditions"], st["status"]
    if status in ("unconscious", "dead", "defeated"):
        return status.capitalize()
    for x in json.loads(conds or "[]"):
        if isinstance(x, dict) and not x.get("expired") and str(x.get("name") or "").strip().capitalize() in SPEED_ZERO:
            return x["name"].strip()
    return None


def fight_turn(conn, md, char_id):
    """The hero's place in the fight on this map, or None when they aren't in a running one."""
    if not md.get("encounter_id") or not char_id:
        return None
    hit = conn.execute("SELECT cb.id FROM combatants cb JOIN encounters e ON e.id = cb.encounter_id "
                       "WHERE e.id = ? AND e.status = 'active' AND cb.character_id = ?", (md["encounter_id"], char_id)).fetchone()
    return turn_info(conn, hit["id"]) if hit else None


def token_fighter(conn, md, token):
    """The combatant a token stands for in this map's running fight, or None."""
    if not md.get("encounter_id"):
        return None
    if token["combatant_id"]:
        row = conn.execute("SELECT cb.id FROM combatants cb JOIN encounters e ON e.id = cb.encounter_id "
                           "WHERE cb.id = ? AND e.id = ? AND e.status = 'active'", (token["combatant_id"], md["encounter_id"])).fetchone()
        if row:
            return row["id"]
    if token["character_id"]:
        row = conn.execute("SELECT cb.id FROM combatants cb JOIN encounters e ON e.id = cb.encounter_id "
                           "WHERE cb.character_id = ? AND e.id = ? AND e.status = 'active'", (token["character_id"], md["encounter_id"])).fetchone()
        if row:
            return row["id"]
    return None


def check_move(conn, md, char_id, x0, y0, x1, y1):
    """Refuses a player's move that's out of turn or too far; records it otherwise."""
    turn = fight_turn(conn, md, char_id)
    return _check(conn, md, turn, x0, y0, x1, y1, None) if turn else None


def check_dm_move(conn, md, token, x1, y1):
    """The DM's map follows the same rules in a fight (unless they choose Free move)."""
    cb = token_fighter(conn, md, token)
    turn = turn_info(conn, cb) if cb else None
    return _check(conn, md, turn, token["x"], token["y"], x1, y1, turn["name"]) if turn else None


def _check(conn, md, turn, x0, y0, x1, y1, name):
    if not turn["my_turn"]:
        raise F.ApiError("Wait for your turn to move" if name is None else f"It's not {name}'s turn — they can move on their turn (or switch on Free move)", status=403)
    if turn["held"]:
        raise F.ApiError((f"You're {turn['held']}" if name is None else f"{name} is {turn['held']}") + " and can't move", status=403, stuck=turn["held"])
    cost = step_ft(md, x0, y0, x1, y1)
    if cost > turn["left"]:
        who = "you have" if name is None else f"{name} has"
        raise F.ApiError(f"That's {cost} ft, and {who} {turn['left']} ft of movement left this turn"
                         + ("" if turn["dash"] or turn["left"] else " (Dash for more)"), status=403, left=turn["left"])
    row = _row(conn, turn["cb_id"])
    _save(conn, row, dict(_turn(row), ft=turn["used"] + cost))
    return dict(turn, used=turn["used"] + cost, left=turn["left"] - cost)


# ---- reach: how far apart two fighters stand -------------------------------------------

def _token_of(conn, map_id, cb_id):
    row = conn.execute("SELECT character_id FROM combatants WHERE id = ?", (cb_id,)).fetchone()
    char = row["character_id"] if row else None
    return conn.execute("SELECT x, y, size FROM map_tokens WHERE map_id = ? AND (combatant_id = ? OR (? IS NOT NULL AND character_id = ?)) "
                        "ORDER BY combatant_id = ? DESC LIMIT 1", (map_id, cb_id, char, char, cb_id)).fetchone()


def distance_ft(conn, eid, a_cb, b_cb):
    """Feet between two fighters on this fight's battle map (5 ft when they're side by side),
    or None when there's no map with both on it."""
    for m in conn.execute("SELECT m.* FROM maps m LEFT JOIN campaigns c ON c.live_map_id = m.id "
                          "WHERE m.encounter_id = ? ORDER BY c.id IS NULL, m.id DESC", (eid,)).fetchall():
        a, b = _token_of(conn, m["id"], a_cb), _token_of(conn, m["id"], b_cb)
        if a and b:
            gx = max(0.0, b["x"] - (a["x"] + a["size"]), a["x"] - (b["x"] + b["size"]))
            gy = max(0.0, b["y"] - (a["y"] + a["size"]), a["y"] - (b["y"] + b["size"]))
            per = ft_per_square(dict(m))
            return (math.ceil(max(gx, gy) - 1e-6) + 1) * per
    return None


def check_reach(conn, eid, attacker, targets, reach, move):
    """A melee move only reaches enemies within its reach (5 ft: right next to you)."""
    if not reach:
        return
    for t in targets:
        d = distance_ft(conn, eid, attacker, t)
        if d is not None and d > reach:
            name = conn.execute("SELECT COALESCE(ch.name, c.name) AS n FROM combatants c LEFT JOIN characters ch ON ch.id = c.character_id "
                                "WHERE c.id = ?", (t,)).fetchone()["n"]
            raise F.ApiError(f"{name} is {d} ft away — {move} only reaches {reach} ft. Move next to them first.", status=403, far=d)


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
                and x.get("encounter_id") in (None, row["eid"]) and x.get("applied_round") in (None, row["round"]))
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


def check_hero_action(conn, cb_id, what="that"):
    """The same two actions for a hero when the DM rolls or casts for them (monsters are the DM's call)."""
    row = conn.execute("SELECT character_id FROM combatants WHERE id = ?", (cb_id,)).fetchone()
    return check_action(conn, cb_id, what) if row and row["character_id"] else None


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
