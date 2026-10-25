"""Reusable creature library.

Encounters copy a creature's stat block when an enemy is added, so editing or
deleting a library entry never changes enemies already placed in encounters.
"""
from flask import Blueprint, jsonify, request

from . import fields as F
from .db import get_db, new_uid, now_iso, tx
from .rules import ABILITIES

bp = Blueprint("creatures", __name__, url_prefix="/api")


def creature_dict(row):
    return F.decode_row(row, F.CREATURE) | {"campaign_id": row["campaign_id"], "id": row["id"]}


def list_creatures(campaign_id=None, q=""):
    sql = "SELECT * FROM creatures WHERE (campaign_id IS NULL OR campaign_id = ?)"
    params = [campaign_id]
    if q:
        sql += " AND (name LIKE ? OR creature_type LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name COLLATE NOCASE"
    return [creature_dict(r) for r in get_db().execute(sql, params).fetchall()]


@bp.get("/creatures")
def api_list():
    cid = request.args.get("campaign_id", type=int)
    return jsonify({"creatures": list_creatures(cid, request.args.get("q", "").strip())})


@bp.post("/creatures")
def api_create():
    data = dict(request.get_json(silent=True) or {})
    campaign_id = data.pop("campaign_id", None)
    values = F.validate_new(F.CREATURE, data)
    if not values.get("name", "").strip():
        raise F.ApiError("Name the creature")
    values.setdefault("abilities", {a: 10 for a in ABILITIES})
    ts = now_iso()
    with tx() as conn:
        new_id = F.insert(conn, "creatures", F.CREATURE, values,
                          {"uid": new_uid(), "campaign_id": campaign_id, "created_at": ts, "updated_at": ts})
    row = get_db().execute("SELECT * FROM creatures WHERE id = ?", (new_id,)).fetchone()
    return jsonify({"creature": creature_dict(row)}), 201


@bp.patch("/creatures/<int:cr_id>")
def api_patch(cr_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        if isinstance(changes, dict) and "name" in changes and not str(changes["name"].get("to", "")).strip():
            raise F.ApiError("Name can't be empty")
        F.cas_patch(conn, "creatures", F.CREATURE, cr_id, changes)
    row = get_db().execute("SELECT * FROM creatures WHERE id = ?", (cr_id,)).fetchone()
    return jsonify({"creature": creature_dict(row)})


@bp.delete("/creatures/<int:cr_id>")
def api_delete(cr_id):
    with tx() as conn:
        if conn.execute("SELECT 1 FROM creatures WHERE id = ?", (cr_id,)).fetchone() is None:
            raise F.NotFound("Creature not found")
        conn.execute("DELETE FROM creatures WHERE id = ?", (cr_id,))
    return jsonify({"deleted": cr_id})


# ---- Monster Book: ready-made stat blocks to copy into the library ---------------

def _library_names(conn, campaign_id):
    rows = conn.execute("SELECT name FROM creatures WHERE campaign_id IS NULL OR campaign_id = ?", (campaign_id,)).fetchall()
    return {r["name"].strip().lower() for r in rows}


@bp.get("/monster-book")
def api_monster_book():
    from .monster_book import ATTRIBUTION, MONSTERS, cr_value
    have = _library_names(get_db(), request.args.get("campaign_id", type=int))
    items = [{"name": m["name"], "creature_type": m["creature_type"], "cr": m["cr"], "max_hp": m["max_hp"], "ac": m["ac"],
              "in_library": m["name"].lower() in have} for m in MONSTERS]
    items.sort(key=lambda m: (cr_value(m["cr"]), m["name"]))
    return jsonify({"monsters": items, "attribution": ATTRIBUTION})


@bp.post("/monster-book/add")
def api_monster_book_add():
    """Copy chosen Monster Book entries into the shared creature library.
    Monsters already in the library (same name) are skipped, never duplicated."""
    from .monster_book import BY_NAME
    data = request.get_json(silent=True) or {}
    names = data.get("names")
    if not isinstance(names, list) or not names or len(names) > 200 or not all(isinstance(n, str) for n in names):
        raise F.ApiError("Choose at least one monster")
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        raise F.ApiError(f"Not in the Monster Book: {', '.join(map(str, unknown[:3]))}")
    added, skipped = [], []
    ts = now_iso()
    with tx() as conn:
        have = _library_names(conn, data.get("campaign_id"))
        for name in dict.fromkeys(names):  # keep order, drop repeats
            if name.lower() in have:
                skipped.append(name)
                continue
            values = F.validate_new(F.CREATURE, BY_NAME[name])
            F.insert(conn, "creatures", F.CREATURE, values,
                     {"uid": new_uid(), "campaign_id": None, "created_at": ts, "updated_at": ts})
            have.add(name.lower())
            added.append(name)
    return jsonify({"added": added, "skipped": skipped, "creatures": list_creatures(data.get("campaign_id"))})
