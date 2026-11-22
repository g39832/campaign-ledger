"""Healing items in a hero's inventory (Stim injector, Med-gel patch, Trauma kit...), used from the
player's screen. What an item does comes from its notes, the way chest loot writes them:
"Bonus action: regain 2d4 + 2 hit points." / "Action: press it on a wound to regain 1d4 + 1 hit points."

- Healing: the dice in "regain <dice> hit points" (not ones that heal "at the start of each" turn).
- When: "Action:" uses one of their actions on their turn in a fight; "Bonus action:" is one bonus
  action a turn. Outside a fight they can use it any time.
- Used up: one off the quantity (the row goes at 0). "Three uses" items count down their uses
  first; "three charges ... back at dawn" items keep the row and get their charges back on a long rest.
"""

import json
import re

from . import dice
from . import fields as F
from .db import now_iso

_REGAIN = re.compile(r"regains?\s+(\d+\s*d\s*\d+(?:\s*[+-]\s*\d+)?|\d+)\s+hit points", re.I)
_COUNT = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(uses|charges)\b", re.I)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def heal_info(row):
    """{dice, when: action|bonus|any, uses, charges} for an item that heals, else None."""
    if not isinstance(row, dict):
        return None
    notes = str(row.get("notes") or "")
    m = _REGAIN.search(notes)
    if not m or re.search(r"at the start of each", notes, re.I):
        return None
    expr = re.sub(r"\s+", "", m.group(1))
    try:
        dice.parse(expr)
    except Exception:  # noqa: BLE001  (not dice we can roll)
        return None
    when = "bonus" if re.search(r"\bbonus action\b", notes, re.I) else "action" if re.search(r"\baction\b", notes, re.I) else "any"
    n = _COUNT.search(notes)
    count = (int(n.group(1)) if n.group(1).isdigit() else _WORDS[n.group(1).lower()]) if n else None
    charges = bool(n and n.group(2).lower() == "charges")
    out = {"dice": expr, "when": when, "uses": None, "charges": None}
    if count and count > 1:
        used = int(row.get("charges_used" if charges else "uses_used") or 0)
        out["charges" if charges else "uses"] = {"total": count, "left": max(0, count - used)}
    return out


def _qty(row):
    try:
        return int(float(row.get("qty") if row.get("qty") not in (None, "") else 1))
    except (TypeError, ValueError):
        return 1


def use_item(conn, viewer, char_id, index, op_id=None):
    """The hero uses a healing item on themselves. Returns the roll id."""
    from .movement import _row, _save, _turn, check_action, spend_action
    from .rest import active_combatant, change_character_hp
    from .rolls import save_roll
    if op_id:
        old = conn.execute("SELECT * FROM rolls WHERE op_id = ?", (op_id,)).fetchone()
        if old:
            return old["id"]
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    rows = list(ch.get("equipment") or [])
    try:
        index = int(index)
        row = rows[index]
    except (TypeError, ValueError, IndexError):
        raise F.ApiError("That item isn't in your inventory any more")
    info = heal_info(row)
    name = str(row.get("name") or "Item").strip()
    if info is None:
        raise F.ApiError(f"{name} doesn't heal")
    if _qty(row) <= 0:
        raise F.ApiError(f"You're out of {name}")
    if info["charges"] and not info["charges"]["left"]:
        raise F.ApiError(f"{name} has no charges left — they come back after a long rest")
    if (ch["current_hp"] or 0) <= 0:
        raise F.ApiError("You're down — someone else has to help you")
    if (ch["current_hp"] or 0) >= (ch["max_hp"] or 0):
        raise F.ApiError("You're already at full health")
    cb = active_combatant(conn, char_id)
    fight = _row(conn, cb["id"]) if cb else None
    if fight is not None and info["when"] in ("action", "bonus"):
        if fight["current_id"] != fight["cb_id"]:
            raise F.ApiError(f"In a fight, {name} is used on your turn ({'a bonus action' if info['when'] == 'bonus' else 'an action'})", status=403)
        if info["when"] == "action":
            check_action(conn, cb["id"], name)
            spend_action(conn, cb["id"])
        else:
            done = _turn(fight)
            if done.get("bonus"):
                raise F.ApiError("You've already used your bonus action this turn", status=403)
            _save(conn, fight, dict(done, bonus=True))
    result = dice.roll(info["dice"])
    heal = max(0, result["total"])
    # used up
    left_txt = ""
    if info["charges"]:
        rows[index] = dict(row, charges_used=int(row.get("charges_used") or 0) + 1)
        left_txt = f" · {info['charges']['left'] - 1} of {info['charges']['total']} charges left"
    elif info["uses"] and info["uses"]["left"] > 1:
        rows[index] = dict(row, uses_used=int(row.get("uses_used") or 0) + 1)
        left_txt = f" · {info['uses']['left'] - 1} of {info['uses']['total']} uses left"
    else:
        q = _qty(row) - 1
        if q > 0:
            rows[index] = dict(row, qty=q, uses_used=0) if info["uses"] else dict(row, qty=q)
            left_txt = f" · {q} left"
        else:
            rows.pop(index)
            left_txt = " · that was the last one"
    conn.execute("UPDATE characters SET equipment = ?, updated_at = ? WHERE id = ?", (json.dumps(rows), now_iso(), char_id))
    roll_id = save_roll(conn, viewer, ch["campaign_id"], result, label=name, kind="heal", subject=ch["name"],
                        ids={"character_id": char_id}, op_id=op_id, outcome=f"Heals {heal}{left_txt}")
    if heal:
        change_character_hp(conn, char_id, {"op": "heal", "amount": heal},
                            by=f"{name}{', ' + viewer['name'] if viewer.get('role') == 'player' else ''}")
    return roll_id


def recharge(equipment):
    """A long rest: items with charges get them all back. None when nothing changes."""
    rows = equipment or []
    if not any(isinstance(r, dict) and r.get("charges_used") for r in rows):
        return None
    return [dict(r, charges_used=0) if isinstance(r, dict) and r.get("charges_used") else r for r in rows]
