import json
import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from . import fields as F
from .auth import current_identity
from .db import get_db, new_uid, now_iso, tx
from .rules import ABILITIES, derived

bp = Blueprint("characters", __name__, url_prefix="/api")

PORTRAIT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def default_character_values():
    return {
        "abilities": {a: 10 for a in ABILITIES},
        "currency": {"cp": 0, "sp": 0, "ep": 0, "gp": 0, "pp": 0},
        "spell_slots": {str(i): {"max": 0, "used": 0} for i in range(1, 10)},
    }


def character_dict(row):
    d = F.decode_row(row, F.CHARACTER)
    d["derived"] = derived(d)
    return d


def get_character(char_id, conn=None):
    row = (conn or get_db()).execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        raise F.NotFound("Character not found")
    return character_dict(row)


def list_characters(campaign_id, include_archived=False):
    sql = "SELECT * FROM characters WHERE campaign_id = ?"
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY kind, name COLLATE NOCASE"
    return [character_dict(r) for r in get_db().execute(sql, (campaign_id,)).fetchall()]


@bp.get("/campaigns/<int:cid>/characters")
def api_list(cid):
    return jsonify({"characters": list_characters(cid, request.args.get("archived") == "1")})


@bp.post("/campaigns/<int:cid>/characters")
def api_create(cid):
    data = request.get_json(silent=True) or {}
    if get_db().execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    values = default_character_values()
    values.update(F.validate_new(F.CHARACTER, data))
    if not str(values.get("name", "")).strip():
        raise F.ApiError("Give the character a name")
    if "current_hp" not in values and "max_hp" in values:
        values["current_hp"] = values["max_hp"]
    ts = now_iso()
    with tx() as conn:
        char_id = F.insert(conn, "characters", F.CHARACTER, values,
                           {"uid": new_uid(), "campaign_id": cid, "created_at": ts, "updated_at": ts})
        conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (ts, cid))
    return jsonify({"character": get_character(char_id)}), 201


@bp.get("/characters/<int:char_id>")
def api_get(char_id):
    return jsonify({"character": get_character(char_id)})


@bp.patch("/characters/<int:char_id>")
def api_patch(char_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        if isinstance(changes, dict) and "name" in changes and not str(changes["name"].get("to", "")).strip():
            raise F.ApiError("Name can't be empty")
        before = conn.execute("SELECT conditions FROM characters WHERE id = ?", (char_id,)).fetchone()
        row, updates = F.cas_patch(conn, "characters", F.CHARACTER, char_id, changes)
        if "conditions" in updates and before is not None and "max_hp" not in updates:
            # an effect that raised max HP (Aid) was taken off on the sheet: the extra HP goes too
            now = {x.get("id") for x in row["conditions"] or [] if isinstance(x, dict)}
            gone = sum(int(x.get("max_hp") or 0) for x in json.loads(before["conditions"] or "[]")
                       if isinstance(x, dict) and x.get("id") not in now)
            if gone:
                conn.execute("UPDATE characters SET max_hp = MAX(0, max_hp - ?) WHERE id = ?", (gone, char_id))
                row = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
                updates["max_hp"] = row["max_hp"]
        if "max_hp" in updates and row["current_hp"] > row["max_hp"]:
            conn.execute("UPDATE characters SET current_hp = max_hp WHERE id = ?", (char_id,))
        _touch_encounters(conn, char_id)
    return jsonify({"character": get_character(char_id)})


def _touch_encounters(conn, char_id):
    """Bump the revision of open encounters this character is in, so an open
    combat screen refreshes and shows the same HP as the sheet."""
    conn.execute(
        """UPDATE encounters SET rev = rev + 1 WHERE status != 'ended' AND id IN
           (SELECT encounter_id FROM combatants WHERE character_id = ?)""",
        (char_id,),
    )


@bp.post("/characters/<int:char_id>/portrait")
def api_portrait(char_id):
    get_character(char_id)
    f = request.files.get("file")
    if f is None or not f.filename:
        raise F.ApiError("Choose an image file")
    ext = PORTRAIT_TYPES.get(f.mimetype)
    if ext is None:
        raise F.ApiError("Portraits must be PNG, JPEG, WebP or GIF")
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config["UPLOAD_DIR"], name)
    f.save(path)
    with tx() as conn:
        old = conn.execute("SELECT portrait FROM characters WHERE id = ?", (char_id,)).fetchone()["portrait"]
        conn.execute("UPDATE characters SET portrait = ?, updated_at = ? WHERE id = ?", (name, now_iso(), char_id))
    # Old files are kept: backups taken earlier may still reference them.
    return jsonify({"character": get_character(char_id), "previous": old})


@bp.delete("/characters/<int:char_id>/portrait")
def api_portrait_clear(char_id):
    with tx() as conn:
        conn.execute("UPDATE characters SET portrait = NULL, updated_at = ? WHERE id = ?", (now_iso(), char_id))
    return jsonify({"character": get_character(char_id)})


@bp.get("/uploads/<path:name>")
def uploads(name):
    ident = current_identity()
    if ident and ident["role"] == "player":
        # Players may load portraits from their own campaign, nothing else
        # (raw map images could reveal areas still under fog of war).
        ok = get_db().execute("SELECT 1 FROM characters WHERE campaign_id = ? AND portrait = ?",
                              (ident["campaign_id"], name)).fetchone() or get_db().execute(
            "SELECT 1 FROM creatures WHERE portrait = ? AND (campaign_id IS NULL OR campaign_id = ?)", (name, ident["campaign_id"])).fetchone()
        if not ok:
            from .handouts import player_may_see_image
            ok = player_may_see_image(get_db(), ident["campaign_id"], ident["character_id"], name)
        if not ok:
            raise F.NotFound("Not found")
    return send_from_directory(current_app.config["UPLOAD_DIR"], name, max_age=86400)


@bp.delete("/characters/<int:char_id>")
def api_delete(char_id):
    char = get_character(char_id)
    if not char["archived"]:
        raise F.ApiError("Archive the character first. Only archived characters can be deleted.")
    if (request.get_json(silent=True) or {}).get("confirm_name") != char["name"]:
        raise F.ApiError("Type the character's name to confirm deletion")
    with tx() as conn:
        # Encounters keep a frozen copy of the character's last known vitals.
        conn.execute(
            """UPDATE combatants SET current_hp = ?, max_hp = ?, temp_hp = ?, ac = ?, conditions = ?
               WHERE character_id = ?""",
            (char["current_hp"], char["max_hp"], char["temp_hp"], char["ac"],
             F.to_db(F.CHARACTER["conditions"], char["conditions"]), char_id),
        )
        conn.execute("DELETE FROM journal_links WHERE target_type = 'character' AND target_id = ?", (char_id,))
        conn.execute(
            "DELETE FROM journal_links WHERE target_type = 'morality' AND target_id IN "
            "(SELECT id FROM morality_events WHERE character_id = ?)", (char_id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (char_id,))
    return jsonify({"deleted": char_id})
