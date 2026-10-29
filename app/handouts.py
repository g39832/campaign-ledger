"""Player handouts: the DM sends a picture and/or a note (a letter, a map scrap, a monster
reveal) to everyone or to chosen characters. It pops up on those players' screens (instant
updates) and stays in their Handouts list. Players only ever see the ones meant for them."""
import json
import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from . import fields as F
from .auth import is_dm
from .db import get_db, new_uid, now_iso, tx

bp = Blueprint("handouts", __name__, url_prefix="/api")


def _dm():
    if not is_dm():
        raise F.ApiError("Only the DM can do that.", status=403)


def handout_dict(r):
    to = json.loads(r["to_characters"]) if r["to_characters"] else None
    return {"id": r["id"], "uid": r["uid"], "title": r["title"], "body": r["body"], "image": r["image"], "to": to, "created_at": r["created_at"]}


def for_character(conn, campaign_id, char_id, limit=30):
    """The handouts a player sees: those for everyone, and those sent to their character."""
    out = []
    for r in conn.execute("SELECT * FROM handouts WHERE campaign_id = ? ORDER BY id DESC", (campaign_id,)):
        h = handout_dict(r)
        if h["to"] is None or (char_id and char_id in h["to"]):
            h.pop("to")
            out.append(h)
            if len(out) >= limit:
                break
    return out


def player_may_see_image(conn, campaign_id, char_id, name):
    return any(h["image"] == name for h in for_character(conn, campaign_id, char_id, limit=1000))


@bp.get("/campaigns/<int:cid>/handouts")
def api_list(cid):
    _dm()
    rows = get_db().execute("SELECT * FROM handouts WHERE campaign_id = ? ORDER BY id DESC", (cid,)).fetchall()
    return jsonify({"handouts": [handout_dict(r) for r in rows]})


@bp.post("/campaigns/<int:cid>/handouts")
def api_send(cid):
    """Send a handout: a form with title, body, to (character ids, comma separated; empty =
    everyone) and an optional picture (file)."""
    from .characters import PORTRAIT_TYPES
    _dm()
    conn = get_db()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    form = request.form if request.form else (request.get_json(silent=True) or {})
    title = str(form.get("title") or "").strip()[:200]
    body = str(form.get("body") or "").strip()[:20000]
    raw_to = form.get("to")
    to = None
    if raw_to not in (None, "", []):
        try:
            to = sorted({int(x) for x in (raw_to if isinstance(raw_to, list) else str(raw_to).split(",")) if str(x).strip()})
        except ValueError:
            raise F.ApiError("Pick who it's for")
        known = {r["id"] for r in conn.execute("SELECT id FROM characters WHERE campaign_id = ?", (cid,))}
        if not to or not set(to) <= known:
            raise F.ApiError("Pick characters from this campaign")
    image = None
    f = request.files.get("file")
    if f is not None and f.filename:
        ext = PORTRAIT_TYPES.get(f.mimetype)
        if ext is None:
            raise F.ApiError("Pictures must be PNG, JPEG, WebP or GIF")
        image = f"{uuid.uuid4().hex}{ext}"
        f.save(os.path.join(current_app.config["UPLOAD_DIR"], image))
    if not (title or body or image):
        raise F.ApiError("Write something or add a picture")
    with tx() as conn:
        cur = conn.execute("INSERT INTO handouts (uid, campaign_id, title, body, image, to_characters, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                           (new_uid(), cid, title, body, image, json.dumps(to) if to is not None else None, now_iso(), now_iso()))
        hid = cur.lastrowid
    return jsonify({"handout": handout_dict(get_db().execute("SELECT * FROM handouts WHERE id = ?", (hid,)).fetchone())}), 201


@bp.delete("/handouts/<int:hid>")
def api_delete(hid):
    _dm()
    with tx() as conn:
        if conn.execute("SELECT 1 FROM handouts WHERE id = ?", (hid,)).fetchone() is None:
            raise F.NotFound("Handout not found")
        conn.execute("DELETE FROM handouts WHERE id = ?", (hid,))
    return jsonify({"deleted": hid})
