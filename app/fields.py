"""Field specs, validation and the compare-and-swap patch used by autosave.

Autosave sends only the fields that changed, each as {"from": old, "to": new}.
A field is written only if its stored value still equals "from" (or already
equals "to", which makes retries idempotent). Anything else is a conflict:
someone else changed that field since this page loaded, so we refuse rather
than silently overwrite newer data.
"""
import json

from .db import now_iso


class ApiError(Exception):
    status = 400

    def __init__(self, message, status=None, **extra):
        super().__init__(message)
        self.message = message
        if status:
            self.status = status
        self.extra = extra


class Conflict(ApiError):
    status = 409


class NotFound(ApiError):
    status = 404


def Text(max_len=20000):
    return ("text", {"max": max_len})


def Int(lo=-1_000_000, hi=1_000_000, nullable=False):
    return ("int", {"lo": lo, "hi": hi, "nullable": nullable})


def Num(lo=-1e6, hi=1e6):
    return ("num", {"lo": lo, "hi": hi})


def Bool():
    return ("bool", {})


def Json(kind):
    return ("json", {"kind": kind})


def Choice(*options):
    return ("choice", {"options": options})


def coerce(spec, value, field):
    typ, opts = spec
    if typ == "text":
        if value is None:
            value = ""
        if not isinstance(value, (str, int, float)):
            raise ApiError(f"{field} must be text")
        value = str(value)
        if len(value) > opts["max"]:
            raise ApiError(f"{field} is too long (max {opts['max']} characters)")
        return value
    if typ == "int":
        if value is None or value == "":
            if opts["nullable"]:
                return None
            raise ApiError(f"{field} needs a number")
        if isinstance(value, bool):
            raise ApiError(f"{field} must be a whole number")
        try:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            value = int(str(value).strip().replace("+", "")) if isinstance(value, str) else int(value)
        except (TypeError, ValueError):
            raise ApiError(f"{field} must be a whole number")
        if value < opts["lo"] or value > opts["hi"]:
            raise ApiError(f"{field} must be between {opts['lo']} and {opts['hi']}")
        return value
    if typ == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(f"{field} must be a number")
        if value != value or value < opts["lo"] or value > opts["hi"]:
            raise ApiError(f"{field} is out of range")
        return round(float(value), 3)
    if typ == "bool":
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ApiError(f"{field} must be true or false")
    if typ == "choice":
        if value not in opts["options"]:
            raise ApiError(f"{field} must be one of: {', '.join(map(str, opts['options']))}")
        return value
    if typ == "json":
        kind = opts["kind"]
        if kind == "list" and not isinstance(value, list):
            raise ApiError(f"{field} must be a list")
        if kind == "dict" and not isinstance(value, dict):
            raise ApiError(f"{field} must be an object")
        if len(json.dumps(value)) > 500_000:
            raise ApiError(f"{field} is too large")
        return value
    raise ApiError(f"unknown field type for {field}")


def to_db(spec, value):
    typ = spec[0]
    if typ == "json":
        return json.dumps(value)
    if typ == "bool":
        return 1 if value else 0
    return value


def from_db(spec, value):
    typ = spec[0]
    if typ == "json":
        return json.loads(value) if isinstance(value, str) else value
    if typ == "bool":
        return bool(value)
    return value


def decode_row(row, specs):
    if row is None:
        return None
    d = dict(row)
    for k, spec in specs.items():
        if k in d:
            d[k] = from_db(spec, d[k])
    return d


def validate_new(specs, data, required=()):
    """Validate a dict of fields for an INSERT. Unknown keys are rejected."""
    out = {}
    for k, v in (data or {}).items():
        if k not in specs:
            raise ApiError(f"Unknown field: {k}")
        out[k] = coerce(specs[k], v, k)
    for r in required:
        if r not in out or out[r] in ("", None):
            raise ApiError(f"{r} is required")
    return out


def insert(conn, table, specs, values, extra):
    cols = list(values.keys()) + list(extra.keys())
    params = [to_db(specs[k], v) for k, v in values.items()] + list(extra.values())
    cur = conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        params,
    )
    return cur.lastrowid


def cas_patch(conn, table, specs, row_id, changes, touch=True):
    """Apply {"field": {"from": x, "to": y}} changes atomically.
    Must be called inside a write transaction. Returns the decoded row."""
    if not isinstance(changes, dict) or not changes:
        raise ApiError("No changes supplied")
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise NotFound("Not found")
    current = decode_row(row, specs)
    updates = {}
    conflicts = {}
    for field, change in changes.items():
        if field not in specs:
            raise ApiError(f"Unknown field: {field}")
        if not isinstance(change, dict) or "to" not in change:
            raise ApiError(f"Change for {field} must include 'to'")
        new = coerce(specs[field], change["to"], field)
        cur = current[field]
        if "from" in change:
            try:
                old = coerce(specs[field], change["from"], field)
            except ApiError:
                old = object()
            if cur != old and cur != new:
                conflicts[field] = cur
                continue
        if cur != new:
            updates[field] = new
    if conflicts:
        raise Conflict(
            "This was changed somewhere else since you opened it.",
            conflicts=conflicts,
            current=current,
        )
    if updates:
        sets = [f"{k} = ?" for k in updates]
        params = [to_db(specs[k], v) for k, v in updates.items()]
        if touch and "updated_at" in current:
            sets.append("updated_at = ?")
            params.append(now_iso())
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", params + [row_id])
        current.update(updates)
    return current, updates


# ---- Specs per table --------------------------------------------------------

CAMPAIGN = {
    "name": Text(200),
    "description": Text(5000),
    "settings": Json("dict"),
    "archived": Bool(),
}

CHARACTER = {
    "kind": Choice("pc", "npc"),
    "archived": Bool(),
    "name": Text(200),
    "player_name": Text(200),
    "race": Text(200),
    "class_name": Text(200),
    "subclass": Text(200),
    "level": Int(1, 30),
    "background": Text(200),
    "alignment": Text(60),
    "xp": Int(0, 10_000_000),
    "max_hp": Int(0, 99999),
    "current_hp": Int(0, 99999),
    "temp_hp": Int(0, 99999),
    "ac": Int(0, 99),
    "initiative_bonus": Int(-50, 50),
    "initiative_override": Int(-50, 50, nullable=True),
    "initiative_roll": Int(-50, 99, nullable=True),
    "speed": Text(200),
    "prof_override": Int(-10, 20, nullable=True),
    "hit_dice": Text(100),
    "hit_dice_used": Int(0, 99),
    "death_successes": Int(0, 3),
    "death_failures": Int(0, 3),
    "exhaustion": Int(0, 10),
    "inspiration": Bool(),
    "status": Choice("ok", "unconscious", "stable", "defeated", "dead", "fled", "incapacitated"),
    "conditions": Json("list"),
    "abilities": Json("dict"),
    "save_profs": Json("list"),
    "save_bonus": Json("dict"),
    "skill_profs": Json("dict"),
    "skill_bonus": Json("dict"),
    "attacks": Json("list"),
    "spellcasting_ability": Choice("", "str", "dex", "con", "int", "wis", "cha"),
    "spell_slots": Json("dict"),
    "spells": Json("list"),
    "features": Text(),
    "proficiencies": Text(),
    "equipment": Json("list"),
    "currency": Json("dict"),
    "appearance": Text(),
    "personality": Text(),
    "ideals": Text(),
    "bonds": Text(),
    "flaws": Text(),
    "backstory": Text(50000),
    "goals": Text(),
    "relationships": Text(),
    "notes": Text(50000),
    "law_start": Int(-1000, 1000),
    "good_start": Int(-1000, 1000),
    "auto_alignment": Bool(),
}
CHARACTER_JSON = [k for k, s in CHARACTER.items() if s[0] == "json"]

MORALITY = {
    "title": Text(300),
    "description": Text(10000),
    "session_label": Text(100),
    "occurred_on": Text(40),
    "law_delta": Int(-1000, 1000),
    "good_delta": Int(-1000, 1000),
    "dm_notes": Text(10000),
    "tags": Json("list"),
}

CREATURE = {
    "name": Text(200),
    "creature_type": Text(200),
    "cr": Text(20),
    "max_hp": Int(1, 99999),
    "ac": Int(0, 99),
    "initiative_mod": Int(-50, 50),
    "speed": Text(200),
    "abilities": Json("dict"),
    "attacks": Text(),
    "traits": Text(),
    "resistances": Text(1000),
    "immunities": Text(1000),
    "vulnerabilities": Text(1000),
    "condition_immunities": Text(1000),
    "senses": Text(1000),
    "languages": Text(1000),
    "notes": Text(),
}

ENCOUNTER = {
    "name": Text(200),
    "location": Text(200),
    "notes": Text(20000),
}

COMBATANT = {
    "name": Text(200),
    "init_roll": Int(-50, 99, nullable=True),
    "init_mod": Int(-50, 50),
    "ac": Int(0, 99),
    "notes": Text(5000),
    "status": Choice("ok", "unconscious", "stable", "defeated", "dead", "fled", "incapacitated"),
    "death_successes": Int(0, 3),
    "death_failures": Int(0, 3),
    "hidden": Bool(),
}

MAP = {
    "name": Text(200),
    "cols": Int(1, 200),
    "rows": Int(1, 200),
    "cell_px": Int(8, 400),
    "offset_x": Int(-4000, 4000),
    "offset_y": Int(-4000, 4000),
    "scale_value": Int(1, 1000),
    "scale_unit": Text(12),
    "show_grid": Bool(),
    "grid_color": Text(20),
    "grid_opacity": Int(0, 100),
    "snap": Bool(),
    "bg_color": Text(20),
    "fog_enabled": Bool(),
    "players_can_move": Bool(),
    "notes": Text(20000),
    "encounter_id": Int(1, 10**12, nullable=True),
}

TOKEN_KINDS = ("pc", "npc", "enemy", "trap", "marker", "object")
TOKEN = {
    "kind": Choice(*TOKEN_KINDS),
    "label": Text(60),
    "x": Num(-50, 250),
    "y": Num(-50, 250),
    "size": Int(1, 6),
    "color": Text(20),
    "hidden": Bool(),
    "notes": Text(2000),
}

JOURNAL_KINDS = ("session", "npc", "location", "quest", "faction", "discovery",
                 "decision", "mystery", "hook", "loot", "note")

JOURNAL = {
    "kind": Choice(*JOURNAL_KINDS),
    "title": Text(300),
    "session_number": Int(0, 100000, nullable=True),
    "session_date": Text(40),
    "body": Text(200000),
    "status": Text(40),
    "tags": Json("list"),
    "pinned": Bool(),
}
