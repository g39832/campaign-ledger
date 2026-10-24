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
