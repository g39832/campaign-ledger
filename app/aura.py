"""Auras you switch on and off: a magic item or feature that helps every ally near its
owner (Moni's item: double speed and +20 HP for allies within 60 ft) and lasts until it's
switched off, in fights and between them.

On a sheet it's a spell row with `aura` set; its area gives the radius, `speed_mult`
and `max_hp` what it gives. Switching it on puts an effect on each ally in range (the
owner too): more max HP and as much current HP, and the speed note. Switching it off
takes it off everyone and gives the max HP back. In a running fight on a battle map
where the owner has a token, only allies within the radius get it; otherwise the
whole party does.
"""
import json
import uuid

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import now_iso, tx
from .rules import spell_info

bp = Blueprint("aura", __name__, url_prefix="/api")


def aura_key(char_id, name):
    return f"{char_id}:{name}"


def _touch(conn, char_id):
    conn.execute("UPDATE encounters SET rev = rev + 1 WHERE status != 'ended' AND id IN "
                 "(SELECT encounter_id FROM combatants WHERE character_id = ?)", (char_id,))


def _allies(conn, owner, radius_ft):
    """The characters the aura reaches: within the radius on the owner's fight map, or else the party."""
    from .maps import tokens_for
    from .rest import active_combatant
    party = [r["id"] for r in conn.execute("SELECT id FROM characters WHERE campaign_id = ? AND archived = 0 AND kind = 'pc'",
                                           (owner["campaign_id"],))]
    cb = active_combatant(conn, owner["id"])
    if cb is None:
        return sorted(set(party) | {owner["id"]}), False
    for m in conn.execute("SELECT * FROM maps WHERE encounter_id = ?", (cb["encounter_id"],)).fetchall():
        toks = tokens_for(conn, m["id"])
        me = next((t for t in toks if t["character_id"] == owner["id"]), None)
        if me is None:
            continue
        per = m["scale_value"] or 5
        reach = radius_ft / per
        cx, cy = me["x"] + me["size"] / 2, me["y"] + me["size"] / 2
        near = {owner["id"]}
        for t in toks:
            if not t["character_id"] or t["character_id"] == owner["id"]:
                continue
            # distance from the owner's middle to the nearest edge of their token, in squares
            dx = max(t["x"] - cx, 0, cx - (t["x"] + t["size"]))
            dy = max(t["y"] - cy, 0, cy - (t["y"] + t["size"]))
            if max(dx, dy) <= reach + me["size"] / 2 - 0.01:
                near.add(t["character_id"])
        friends = {r["character_id"] for r in conn.execute(
            "SELECT character_id FROM combatants WHERE encounter_id = ? AND character_id IS NOT NULL AND kind != 'enemy'", (cb["encounter_id"],))}
        return sorted(near & (friends | {owner["id"]})), True
    return sorted(set(party) | {owner["id"]}), False


def toggle(conn, char_id, index, on):
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        raise F.NotFound("Character not found")
    owner = F.decode_row(row, F.CHARACTER)
    try:
        sp = spell_info((owner.get("spells") or [])[int(index)])
    except (TypeError, ValueError, IndexError):
        raise F.ApiError("That isn't on the sheet any more")
    if not sp["aura"]:
        raise F.ApiError(f"{sp['name']} isn't something you switch on and off")
    if on and sp["used"] and not is_on(owner, sp["name"]):
        raise F.ApiError(f"{sp['name'].strip()} has been used already — it can be switched on again after a long rest")
    key = aura_key(char_id, sp["name"])
    radius = (sp["area"] or {}).get("size") or 60
    changed = []
    # an item renamed while it was on leaves its effects under the old name: take those off first
    live = {aura_key(char_id, spell_info(x)["name"]) for x in owner.get("spells") or [] if isinstance(x, dict) and x.get("aura")}
    _take_off(conn, owner, lambda k: k.startswith(f"{char_id}:") and k not in live)
    if on:
        targets, by_map = _allies(conn, owner, radius)
        for cid in targets:
            ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (cid,)).fetchone(), F.CHARACTER)
            if any(x.get("aura") == key for x in ch["conditions"] or []):
                continue
            cond = {"id": uuid.uuid4().hex[:12], "name": sp["condition"] or sp["name"], "note": f"From {owner['name']}'s {sp['name']}",
                    "rounds_left": None, "expired": False, "aura": key}
            if sp["speed_mult"] > 1:
                cond["speed_mult"] = sp["speed_mult"]
            sets, vals = "conditions = ?", [json.dumps((ch["conditions"] or []) + [cond])]
            if sp["max_hp"]:
                cond["max_hp"] = sp["max_hp"]
                vals[0] = json.dumps((ch["conditions"] or []) + [cond])
                sets += ", max_hp = max_hp + ?, current_hp = current_hp + ?"
                vals += [sp["max_hp"], sp["max_hp"]]
            conn.execute(f"UPDATE characters SET {sets}, updated_at = ? WHERE id = ?", (*vals, now_iso(), cid))
            _touch(conn, cid)
            changed.append(ch["name"])
        where = f"within {radius} ft" if by_map else "in the party"
        # once a day: it's used now (a long rest brings it back)
        spells = list(owner.get("spells") or [])
        spells[int(index)] = dict(spells[int(index)], used=True)
        conn.execute("UPDATE characters SET spells = ?, updated_at = ? WHERE id = ?", (json.dumps(spells), now_iso(), char_id))
    else:
        changed = _take_off(conn, owner, lambda k: k == key)
        where = ""
    _log(conn, owner, f"{owner['name']} switches {'on' if on else 'off'} {sp['name']}"
         + (f": {', '.join(changed)} {where}" if on and changed else f" for {', '.join(changed)}" if changed else ""))
    return {"name": sp["name"], "on": on, "who": changed}


def _take_off(conn, owner, which):
    """Remove the aura effects whose key matches, everywhere in the campaign (their extra max HP
    goes too, and HP never ends above max). Returns who had them."""
    changed = []
    for r in conn.execute("SELECT * FROM characters WHERE campaign_id = ?", (owner["campaign_id"],)).fetchall():
        ch = F.decode_row(r, F.CHARACTER)
        gone = [x for x in ch["conditions"] or [] if isinstance(x, dict) and x.get("aura") and which(x["aura"])]
        if not gone:
            continue
        extra = sum(int(x.get("max_hp") or 0) for x in gone)
        new_max = max(0, ch["max_hp"] - extra)
        conn.execute("UPDATE characters SET conditions = ?, max_hp = ?, current_hp = ?, updated_at = ? WHERE id = ?",
                     (json.dumps([x for x in ch["conditions"] if x not in gone]), new_max,
                      min(ch["current_hp"], new_max) if new_max else ch["current_hp"], now_iso(), ch["id"]))
        _touch(conn, ch["id"])
        changed.append(ch["name"])
    return changed


def _log(conn, owner, message):
    from .combat import Ctx
    from .rest import active_combatant
    cb = active_combatant(conn, owner["id"])
    if cb:
        Ctx(conn, cb["encounter_id"]).log("condition", message)


def is_on(char, sp_name):
    key = aura_key(char["id"], sp_name)
    return any(isinstance(x, dict) and x.get("aura") == key for x in char.get("conditions") or [])


@bp.post("/characters/<int:char_id>/aura")
def api_toggle(char_id):
    """The DM switches an aura on or off. {index, on}"""
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        out = toggle(conn, char_id, data.get("index"), bool(data.get("on")))
    from .characters import get_character
    return jsonify({"aura": out, "character": get_character(char_id)})
