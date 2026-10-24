from flask import Blueprint, jsonify, request

from . import fields as F
from .db import get_db, get_setting, new_uid, now_iso, set_setting, tx
from .rules import merged_settings

bp = Blueprint("campaigns", __name__, url_prefix="/api")


def campaign_dict(row):
    d = F.decode_row(row, F.CAMPAIGN)
    d["settings"] = merged_settings(d["settings"])
    return d


def get_campaign(campaign_id):
    row = get_db().execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise F.NotFound("Campaign not found")
    return campaign_dict(row)


def active_campaign():
    """The campaign the UI is working in. Falls back to the most recently
    touched open campaign if the stored one is gone or archived."""
    conn = get_db()
    cid = get_setting("active_campaign_id")
    row = None
    if cid:
        row = conn.execute("SELECT * FROM campaigns WHERE id = ? AND archived = 0", (cid,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE archived = 0 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return campaign_dict(row) if row else None


def list_campaigns():
    conn = get_db()
    rows = conn.execute(
        """SELECT c.*,
             (SELECT COUNT(*) FROM characters WHERE campaign_id = c.id AND archived = 0) AS character_count,
             (SELECT COUNT(*) FROM journal_entries WHERE campaign_id = c.id AND kind = 'session') AS session_count,
             (SELECT COUNT(*) FROM encounters WHERE campaign_id = c.id) AS encounter_count
           FROM campaigns c ORDER BY c.archived, c.updated_at DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = campaign_dict(r)
        d["character_count"] = r["character_count"]
        d["session_count"] = r["session_count"]
        d["encounter_count"] = r["encounter_count"]
        out.append(d)
    return out


@bp.get("/campaigns")
def api_list():
    active = active_campaign()
    return jsonify({"campaigns": list_campaigns(), "active_id": active["id"] if active else None})


@bp.post("/campaigns")
def api_create():
    data = request.get_json(silent=True) or {}
    values = F.validate_new(F.CAMPAIGN, {k: data[k] for k in ("name", "description") if k in data}, required=["name"])
    values["name"] = values["name"].strip()
    if not values["name"]:
        raise F.ApiError("name is required")
    ts = now_iso()
    with tx() as conn:
        cid = F.insert(conn, "campaigns", F.CAMPAIGN, values,
                       {"uid": new_uid(), "created_at": ts, "updated_at": ts})
        if data.get("activate", True):
            set_setting(conn, "active_campaign_id", cid)
    return jsonify({"campaign": get_campaign(cid)}), 201


@bp.patch("/campaigns/<int:cid>")
def api_patch(cid):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        if isinstance(changes, dict) and "settings" in changes:
            # Settings arrive as a full merged object; store only known sections.
            to = changes["settings"].get("to") if isinstance(changes["settings"], dict) else None
            if not isinstance(to, dict):
                raise F.ApiError("settings must be an object")
            _validate_settings(to)
        if isinstance(changes, dict) and "name" in changes:
            if not str(changes["name"].get("to", "")).strip():
                raise F.ApiError("Campaign name can't be empty")
        row, _ = F.cas_patch(conn, "campaigns", F.CAMPAIGN, cid, changes)
        if "archived" in (changes or {}):
            conn.execute("UPDATE campaigns SET archived_at = ? WHERE id = ?",
                         (now_iso() if row["archived"] else None, cid))
    return jsonify({"campaign": get_campaign(cid)})


def _validate_settings(s):
    m = s.get("morality", {})
    scale = m.get("scale", 100)
    for key in ("scale", "law_threshold", "good_threshold"):
        v = m.get(key, 1)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 1000:
            raise F.ApiError(f"morality.{key} must be a whole number from 1 to 1000")
    if m.get("law_threshold", 1) > scale or m.get("good_threshold", 1) > scale:
        raise F.ApiError("Alignment thresholds must be within the scale")
    c = s.get("combat", {})
    if c.get("tie_break", "modifier") not in ("modifier", "pc_first", "enemy_first", "manual"):
        raise F.ApiError("Unknown tie-break rule")
    if not isinstance(c.get("skip_statuses", []), list):
        raise F.ApiError("skip_statuses must be a list")


@bp.post("/campaigns/<int:cid>/activate")
def api_activate(cid):
    camp = get_campaign(cid)
    if camp["archived"]:
        raise F.ApiError("Unarchive this campaign before switching to it")
    with tx() as conn:
        set_setting(conn, "active_campaign_id", cid)
    return jsonify({"campaign": camp})


@bp.get("/settings")
def api_get_settings():
    return jsonify({"theme": get_setting("theme", "dark")})


@bp.patch("/settings")
def api_set_settings():
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        if "theme" in data:
            if data["theme"] not in ("dark", "light"):
                raise F.ApiError("theme must be dark or light")
            set_setting(conn, "theme", data["theme"])
    return jsonify({"theme": get_setting("theme", "dark")})
