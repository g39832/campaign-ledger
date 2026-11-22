"""Wild Shape: a druid turns into a beast (or, for a Circle of the Moon druid, an elemental).

Only characters given forms can do it (characters.wild_shape = {forms, uses, used, active}); a sheet
that just says "Druid" gets nothing (Moni's sheet says Druid but she's a monk).

Shifting swaps the beast's AC, speed, attacks and HP onto the sheet and keeps hers in `active.saved`,
so the combat screen, the battle map and "Let it act" all use the beast's attacks with no extra code.
While shifted she can't cast spells (druids can't until level 18). When the beast drops to 0 HP she
changes back and the damage left over carries on to her own HP (combat.apply_hp calls take_damage).

Shifting or changing back is a bonus action on her turn in a fight, any time outside one. Uses come
back on a short or long rest (2 each; an elemental costs 2).
"""
import json
import uuid

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import now_iso, tx

bp = Blueprint("wildshape", __name__, url_prefix="/api")

SWAPPED = ("attacks", "ac", "speed", "max_hp", "current_hp")


def _atk(name, damage, condition="", notes="", **extra):
    return dict({"name": name, "bonus": "+3", "damage": damage, "condition": condition, "notes": notes}, **extra)


# Circle of the Moon at level 15: beasts up to CR 5, and elementals for two uses.
MOON_FORMS = [
    {"name": "Dire Wolf", "cr": "1", "hp": 37, "ac": 14, "speed": "50 ft.",
     "look": "a huge grey wolf with pink antennas poking out of its fur",
     "attacks": [_atk("Bite", "2d6+3 piercing", "Prone", "A knock-down bite")]},
    {"name": "Brown Bear", "cr": "1", "hp": 34, "ac": 11, "speed": "40 ft., climb 30 ft.",
     "look": "a big brown bear with shiny bug eyes",
     "attacks": [_atk("Bite", "1d8+4 piercing"), _atk("Claws", "2d6+4 slashing")]},
    {"name": "Giant Eagle", "cr": "1", "hp": 26, "ac": 13, "speed": "80 ft. (flying)",
     "look": "a giant eagle; the antennas stay on as two pink feathers",
     "attacks": [_atk("Beak", "1d6+3 piercing"), _atk("Talons", "2d6+3 slashing")]},
    {"name": "Giant Constrictor Snake", "cr": "2", "hp": 60, "ac": 12, "speed": "30 ft., swim 30 ft.",
     "look": "a long pink-and-green snake with big bug eyes",
     "attacks": [_atk("Bite", "2d6+4 piercing", notes="reach 10 ft"),
                 _atk("Constrict", "2d8+4 bludgeoning", "Restrained", "Wraps up the target")]},
    {"name": "Giant Scorpion", "cr": "3", "hp": 52, "ac": 15, "speed": "40 ft.",
     "look": "a giant scorpion with pink feelers",
     "attacks": [_atk("Claw", "1d8+2 bludgeoning", "Grappled", "Grabs the target"),
                 _atk("Sting", "1d10+4d10+2 poison", notes="Piercing sting full of poison", cooldown=1)]},
    {"name": "Triceratops", "cr": "5", "hp": 95, "ac": 13, "speed": "50 ft.",
     "look": "a triceratops with two little pink antennas between its horns",
     "attacks": [_atk("Gore", "4d8+6 piercing"), _atk("Stomp", "3d10+6 bludgeoning", "Prone", "On a creature that's down or small")]},
    {"name": "Air Elemental", "cr": "5", "hp": 90, "ac": 15, "speed": "90 ft. (flying)", "cost": 2,
     "look": "a howling whirlwind with two pink sparks for antennas",
     "attacks": [_atk("Slam", "2d8+5 bludgeoning"),
                 _atk("Whirlwind", "3d8+2 bludgeoning", "Prone", "Everyone in the swirl", area="10 ft radius, range 0", cooldown=2)]},
    {"name": "Earth Elemental", "cr": "5", "hp": 126, "ac": 17, "speed": "30 ft., burrow 30 ft.",  "cost": 2,
     "look": "a walking hill of stone with two glowing bug eyes",
     "attacks": [_atk("Slam", "2d8+5 bludgeoning"), _atk("Rock Slam", "3d8+5 bludgeoning", "Prone", cooldown=1)]},
    {"name": "Fire Elemental", "cr": "5", "hp": 102, "ac": 13, "speed": "50 ft.", "cost": 2,
     "look": "a dancing pink-orange flame",
     "attacks": [_atk("Touch", "2d6+3 fire"), _atk("Fire Wave", "3d6+3 fire", notes="Everything around her catches", area="10 ft radius, range 0", cooldown=2)]},
    {"name": "Water Elemental", "cr": "5", "hp": 114, "ac": 14, "speed": "30 ft., swim 90 ft.", "cost": 2,
     "look": "a rolling wave with two bubbles for bug eyes",
     "attacks": [_atk("Slam", "2d8+4 bludgeoning"), _atk("Whelm", "2d8+4 bludgeoning", "Grappled", "Pulls the target inside the wave", cooldown=2)]},
    # her trump card: once per long rest, on top of her two normal uses; her token grows to 3x3 squares
    {"name": "Ancient Moon Behemoth", "cr": "trump card", "hp": 250, "ac": 18, "speed": "50 ft.", "trump": True, "size": 3,
     "look": "a gargantuan silver-furred behemoth the size of a house, crescent moons glowing along its back, "
             "two huge pink antennas sparking above its horns",
     "attacks": [_atk("Crushing Jaws", "6d10+8 piercing", "Grappled", "Clamps down and won't let go", look="bite"),
                 _atk("Tail Sweep", "4d10+8 bludgeoning", "Prone", "Everyone around her", area="15 ft radius, range 0", cooldown=1),
                 _atk("Moonquake Stomp", "5d10+8 bludgeoning", "Prone", "The ground cracks open", area="20 ft radius, range 0", cooldown=2)]},
]


def _a(name):
    return ("an " if name[:1].lower() in "aeiou" else "a ") + name


def state(conn, char_id):
    row = conn.execute("SELECT wild_shape FROM characters WHERE id = ?", (char_id,)).fetchone()
    try:
        ws = json.loads(row["wild_shape"] or "{}") if row else {}
    except ValueError:
        ws = {}
    return ws if isinstance(ws, dict) else {}


def _put(conn, char_id, ws):
    conn.execute("UPDATE characters SET wild_shape = ?, updated_at = ? WHERE id = ?", (json.dumps(ws), now_iso(), char_id))


def info(conn, char_id):
    """What the combat screen and map show, or None if this character has no wild shape."""
    ws = state(conn, char_id)
    if not ws.get("forms"):
        return None
    uses = int(ws.get("uses") or 2)
    left = max(0, uses - int(ws.get("used") or 0))
    act = ws.get("active")
    return {"uses": uses, "left": left, "active": ({"name": act["name"], "hp": act.get("hp"), "look": act.get("look", ""), "trump": bool(act.get("trump"))} if act else None),
            "trump_ready": not ws.get("trump_used"),
            "forms": [{"index": i, "name": f["name"], "cr": f.get("cr", ""), "hp": f["hp"], "ac": f["ac"], "speed": f["speed"],
                       "cost": 0 if f.get("trump") else int(f.get("cost") or 1), "trump": bool(f.get("trump")), "look": f.get("look", ""),
                       "attacks": [a["name"] for a in f.get("attacks") or []]} for i, f in enumerate(ws["forms"])]}


def is_shifted(conn, char_id):
    return bool(char_id and state(conn, char_id).get("active"))


def _bonus_action(conn, char_id):
    """In a running fight it's her bonus action, on her turn. Outside a fight: any time."""
    from .movement import _row, _save, _turn
    from .rest import active_combatant
    cb = active_combatant(conn, char_id)
    if cb is None:
        return
    fight = _row(conn, cb["id"])
    if fight is None or fight["status"] != "active":
        return
    if fight["current_id"] != fight["cb_id"]:
        raise F.ApiError("In a fight, Wild Shape is used on her own turn (a bonus action)")
    done = _turn(fight)
    if done.get("bonus"):
        raise F.ApiError("She has already used her bonus action this turn")
    _save(conn, fight, dict(done, bonus=True))


def _chip(conds, name=None, look=""):
    conds = [x for x in conds if not (isinstance(x, dict) and x.get("wild_shape"))]
    if name:
        conds.append({"id": uuid.uuid4().hex[:12], "name": "Wild Shape: " + name, "note": look or "In beast form",
                      "wild_shape": True, "expired": False})
    return conds


def _log(conn, char_id, message):
    """A line in the log of any running fight she's in, and those fights refresh."""
    from .rest import active_combatant
    cb = active_combatant(conn, char_id)
    if cb is not None:
        from .combat import Ctx
        Ctx(conn, cb["encounter_id"]).log("condition", message)
    conn.execute("UPDATE encounters SET rev = rev + 1 WHERE status != 'ended' AND id IN "
                 "(SELECT encounter_id FROM combatants WHERE character_id = ?)", (char_id,))


def _fx(conn, char_id, name, kind="buff"):
    from .rest import active_combatant
    cb = active_combatant(conn, char_id)
    if cb is not None:
        from .maps import attack_fx
        attack_fx(conn, cb["encounter_id"], cb["id"], [(cb["id"], "auto")], name, kind, "", None, "arcane")


def shift(conn, char_id, index, free=False):
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    ws = state(conn, char_id)
    forms = ws.get("forms") or []
    try:
        form = forms[int(index)]
    except (TypeError, ValueError, IndexError):
        raise F.ApiError("Pick one of her forms")
    if ws.get("active"):
        raise F.ApiError(f"{ch['name']} is already {_a(ws['active']['name'])} — change back first")
    if (ch["current_hp"] or 0) <= 0 or ch["status"] not in ("ok",):
        raise F.ApiError(f"{ch['name']} can't Wild Shape while she's down")
    trump = bool(form.get("trump"))
    cost = 0 if trump else int(form.get("cost") or 1)
    left = int(ws.get("uses") or 2) - int(ws.get("used") or 0)
    if trump and ws.get("trump_used"):
        raise F.ApiError(f"{form['name']} is her trump card — it's used, and back after a long rest")
    if left < cost:
        raise F.ApiError(f"Not enough Wild Shape uses left ({left}; {form['name']} needs {cost}) — they come back on a short or long rest")
    if not free:
        _bonus_action(conn, char_id)
    ws["used"] = int(ws.get("used") or 0) + cost
    if trump:
        ws["trump_used"] = True
    ws["active"] = {"name": form["name"], "look": form.get("look", ""), "hp": form["hp"], "trump": trump,
                    "saved": {k: ch[k] for k in SWAPPED}, "token_sizes": _grow(conn, char_id, form.get("size"))}
    _put(conn, char_id, ws)
    conn.execute("UPDATE characters SET attacks = ?, ac = ?, speed = ?, max_hp = ?, current_hp = ?, conditions = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(form["attacks"]), form["ac"], form["speed"], form["hp"], form["hp"],
                  json.dumps(_chip(ch["conditions"] or [], form["name"], form.get("look", ""))), now_iso(), char_id))
    if trump:
        _log(conn, char_id, f"{ch['name']} plays her trump card and becomes the {form['name']} ({form['hp']} HP, AC {form['ac']})!")
    else:
        _log(conn, char_id, f"{ch['name']} uses Wild Shape and becomes {_a(form['name'])} ({form['hp']} HP, AC {form['ac']})"
                            f" · {left - cost} use{'s' if left - cost != 1 else ''} left")
    _fx(conn, char_id, "Wild Shape")
    if trump:
        from .rest import active_combatant
        cb = active_combatant(conn, char_id)
        if cb is not None:
            from .maps import attack_fx
            attack_fx(conn, cb["encounter_id"], cb["id"], [(cb["id"], "auto")], "Moonquake", "buff", "", None, "quake")
    return form["name"]


def _grow(conn, char_id, size):
    """A huge form makes her map tokens bigger. Returns {token id: old size} to put back."""
    if not size:
        return {}
    old = {}
    for t in conn.execute("SELECT id, size, map_id FROM map_tokens WHERE character_id = ? OR combatant_id IN "
                          "(SELECT id FROM combatants WHERE character_id = ?)", (char_id, char_id)).fetchall():
        old[str(t["id"])] = t["size"]
        conn.execute("UPDATE map_tokens SET size = ? WHERE id = ?", (int(size), t["id"]))
        from .maps import _bump
        _bump(conn, t["map_id"])
    return old


def revert(conn, char_id, carry=0, why=""):
    """Back to her own form: her AC, speed, attacks and HP come back. `carry` is damage that went past
    the beast's 0 HP, taken from her own HP by the caller. Returns the form she was, or None."""
    ws = state(conn, char_id)
    act = ws.get("active")
    if not act:
        return None
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    saved = act.get("saved") or {}
    for tid, size in (act.get("token_sizes") or {}).items():  # her token shrinks back
        conn.execute("UPDATE map_tokens SET size = ? WHERE id = ?", (int(size), int(tid)))
        row = conn.execute("SELECT map_id FROM map_tokens WHERE id = ?", (int(tid),)).fetchone()
        if row:
            from .maps import _bump
            _bump(conn, row["map_id"])
    ws["active"] = None
    _put(conn, char_id, ws)
    hp = min(int(saved.get("current_hp") or 0), int(saved.get("max_hp") or 0))
    conn.execute("UPDATE characters SET attacks = ?, ac = ?, speed = ?, max_hp = ?, current_hp = ?, conditions = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(saved.get("attacks") or []), saved.get("ac", ch["ac"]), saved.get("speed", ch["speed"]),
                  saved.get("max_hp", ch["max_hp"]), hp, json.dumps(_chip(ch["conditions"] or [])), now_iso(), char_id))
    _log(conn, char_id, f"{ch['name']} changes back from {_a(act['name'])}" + (f" — {why}" if why else "") + f" ({hp} HP)")
    _fx(conn, char_id, "Wild Shape ends", "debuff" if carry else "buff")
    return act["name"]


def take_damage(ctx, c, amount):
    """Called by combat.apply_hp before damage lands on a shifted character. If the beast's HP (and
    temp HP) can't hold it, she changes back and returns the damage left over for her own HP;
    otherwise returns `amount` unchanged."""
    if not c.get("linked") or not is_shifted(ctx.conn, c["character_id"]):
        return amount
    room = (c["hp"] or 0) + (c["temp_hp"] or 0)
    if amount < room:
        return amount
    if c["temp_hp"]:
        ctx.conn.execute("UPDATE characters SET temp_hp = 0 WHERE id = ?", (c["character_id"],))
    name = state(ctx.conn, c["character_id"])["active"]["name"]
    carry = amount - room
    revert(ctx.conn, c["character_id"], carry, f"the {name} drops to 0 HP" + (f"; {carry} damage carries over" if carry else ""))
    return carry


def rest(conn, char_id):
    """A short or long rest: she changes back and gets her uses back."""
    ws = state(conn, char_id)
    if not ws.get("forms"):
        return
    revert(conn, char_id, why="rest")
    ws = state(conn, char_id)
    ws["used"] = 0
    ws["trump_used"] = False
    _put(conn, char_id, ws)


def give_forms(conn, char_id, forms=None, uses=2):
    ws = state(conn, char_id)
    ws.update(forms=forms or MOON_FORMS, uses=uses)
    ws.setdefault("used", 0)
    ws.setdefault("active", None)
    _put(conn, char_id, ws)


# ---- endpoints (DM) ------------------------------------------------------------

def _out(char_id):
    from .characters import get_character
    from .db import get_db
    return {"character": get_character(char_id), "wild_shape": info(get_db(), char_id)}


@bp.post("/characters/<int:char_id>/wild-shape")
def api_shift(char_id):
    """{form: index} turns her into that form; {back: true} changes her back (a bonus action in a fight)."""
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        if conn.execute("SELECT 1 FROM characters WHERE id = ?", (char_id,)).fetchone() is None:
            raise F.NotFound("Character not found")
        if data.get("back"):
            if not is_shifted(conn, char_id):
                raise F.ApiError("She's already in her own form")
            _bonus_action(conn, char_id)
            revert(conn, char_id, why="by choice")
        else:
            shift(conn, char_id, data.get("form"))
    return jsonify(_out(char_id))
