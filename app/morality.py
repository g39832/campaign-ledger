from flask import Blueprint, jsonify, request

from . import fields as F
from .campaigns import get_campaign
from .db import claim_op, get_db, new_uid, now_iso, tx
from .rules import SAINTS_SINNERS_MAX, SAINTS_SINNERS_MIN, alignment_for, morality_timeline, saints_sinners_level

bp = Blueprint("morality", __name__, url_prefix="/api")


def _events(conn, char_id):
    rows = conn.execute(
        "SELECT * FROM morality_events WHERE character_id = ? ORDER BY seq, id", (char_id,)
    ).fetchall()
    return [F.decode_row(r, F.MORALITY) for r in rows]


def morality_state(char_id, conn=None):
    conn = conn or get_db()
    ch = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if ch is None:
        raise F.NotFound("Character not found")
    cfg = get_campaign(ch["campaign_id"])["settings"]["morality"]
    events = _events(conn, char_id)
    timeline = morality_timeline(ch["law_start"], ch["good_start"], events, cfg)
    last = timeline[-1]
    return {
        "character": {
            "id": ch["id"], "name": ch["name"], "alignment": ch["alignment"],
            "auto_alignment": bool(ch["auto_alignment"]), "law_start": ch["law_start"],
            "good_start": ch["good_start"], "campaign_id": ch["campaign_id"], "portrait": ch["portrait"],
            "class_name": ch["class_name"], "level": ch["level"], "kind": ch["kind"],
        },
        "config": cfg,
        "events": events,
        "timeline": timeline,
        "law": last["law"],
        "good": last["good"],
        "computed_alignment": last["alignment"],
        "saints_sinners": saints_sinners_level(ch["morality_score"]),
    }


def _sync_alignment(conn, char_id):
    """With automatic alignment on, store the computed alignment. Returns a
    notice describing any change so the UI can tell the DM explicitly."""
    state = morality_state(char_id, conn)
    ch = state["character"]
    if ch["auto_alignment"] and ch["alignment"] != state["computed_alignment"]:
        conn.execute("UPDATE characters SET alignment = ?, updated_at = ? WHERE id = ?",
                     (state["computed_alignment"], now_iso(), char_id))
        return {"from": ch["alignment"], "to": state["computed_alignment"]}
    return None


def _respond(char_id, notice):
    state = morality_state(char_id)
    state["alignment_change"] = notice
    return jsonify(state)


@bp.get("/characters/<int:char_id>/morality")
def api_state(char_id):
    return jsonify(morality_state(char_id))


@bp.post("/characters/<int:char_id>/morality")
def api_create(char_id):
    data = dict(request.get_json(silent=True) or {})
    op_id = data.pop("op_id", None)
    values = F.validate_new(F.MORALITY, data)
    if not values.get("title", "").strip():
        raise F.ApiError("Give the event a title")
    values["tags"] = _clean_tags(values.get("tags", []))
    with tx() as conn:
        ch = conn.execute("SELECT campaign_id FROM characters WHERE id = ?", (char_id,)).fetchone()
        if ch is None:
            raise F.NotFound("Character not found")
        if not claim_op(conn, op_id):
            return _respond(char_id, None)
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM morality_events WHERE character_id = ?",
                           (char_id,)).fetchone()[0]
        ts = now_iso()
        F.insert(conn, "morality_events", F.MORALITY, values,
                 {"uid": new_uid(), "campaign_id": ch["campaign_id"], "character_id": char_id,
                  "seq": seq, "created_at": ts, "updated_at": ts})
        notice = _sync_alignment(conn, char_id)
    return _respond(char_id, notice), 201


def _clean_tags(tags):
    out = []
    for t in tags:
        t = str(t).strip().lower()[:40]
        if t and t not in out:
            out.append(t)
    return out[:20]


def _event_char(conn, event_id):
    row = conn.execute("SELECT character_id FROM morality_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise F.NotFound("Event not found")
    return row["character_id"]


@bp.patch("/morality/<int:event_id>")
def api_patch(event_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        char_id = _event_char(conn, event_id)
        if isinstance(changes, dict) and "tags" in changes and isinstance(changes["tags"], dict):
            changes["tags"]["to"] = _clean_tags(changes["tags"].get("to") or [])
        if isinstance(changes, dict) and "title" in changes and not str(changes["title"].get("to", "")).strip():
            raise F.ApiError("Title can't be empty")
        F.cas_patch(conn, "morality_events", F.MORALITY, event_id, changes)
        notice = _sync_alignment(conn, char_id)
    return _respond(char_id, notice)


@bp.delete("/morality/<int:event_id>")
def api_delete(event_id):
    with tx() as conn:
        char_id = _event_char(conn, event_id)
        conn.execute("DELETE FROM journal_links WHERE target_type = 'morality' AND target_id = ?", (event_id,))
        conn.execute("DELETE FROM morality_events WHERE id = ?", (event_id,))
        notice = _sync_alignment(conn, char_id)
    return _respond(char_id, notice)


@bp.post("/morality/<int:event_id>/reverse")
def api_reverse(event_id):
    """Add an offsetting event instead of erasing history."""
    with tx() as conn:
        ev = conn.execute("SELECT * FROM morality_events WHERE id = ?", (event_id,)).fetchone()
        if ev is None:
            raise F.NotFound("Event not found")
        if conn.execute("SELECT 1 FROM morality_events WHERE reverses_id = ?", (event_id,)).fetchone():
            raise F.ApiError("This event has already been reversed")
        if ev["reverses_id"]:
            raise F.ApiError("This is already a reversal; delete it instead to restore the original")
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM morality_events WHERE character_id = ?",
                           (ev["character_id"],)).fetchone()[0]
        ts = now_iso()
        conn.execute(
            """INSERT INTO morality_events (uid, campaign_id, character_id, seq, title, description,
               session_label, occurred_on, law_delta, good_delta, dm_notes, tags, reverses_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)""",
            (new_uid(), ev["campaign_id"], ev["character_id"], seq, f"Reversed: {ev['title']}",
             "Offsets an earlier event that was recorded in error or later retconned.",
             ev["session_label"], "", -ev["law_delta"], -ev["good_delta"], "", event_id, ts, ts),
        )
        notice = _sync_alignment(conn, ev["character_id"])
    return _respond(ev["character_id"], notice)


@bp.post("/characters/<int:char_id>/morality/settings")
def api_char_settings(char_id):
    """Starting scores, automatic alignment toggle and manual alignment."""
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        changes = {}
        for key in ("law_start", "good_start", "auto_alignment", "alignment"):
            if key in data:
                changes[key] = {"to": data[key]}
        if not changes:
            raise F.ApiError("Nothing to change")
        F.cas_patch(conn, "characters", F.CHARACTER, char_id, changes)
        notice = None
        if "alignment" not in data:
            notice = _sync_alignment(conn, char_id)
    return _respond(char_id, notice)


@bp.get("/campaigns/<int:cid>/morality")
def api_overview(cid):
    conn = get_db()
    cfg = get_campaign(cid)["settings"]["morality"]
    out = []
    for ch in conn.execute(
        "SELECT * FROM characters WHERE campaign_id = ? AND archived = 0 ORDER BY kind, name COLLATE NOCASE", (cid,)
    ).fetchall():
        totals = conn.execute(
            "SELECT COALESCE(SUM(law_delta),0), COALESCE(SUM(good_delta),0), COUNT(*) FROM morality_events WHERE character_id = ?",
            (ch["id"],),
        ).fetchone()
        law, good = ch["law_start"] + totals[0], ch["good_start"] + totals[1]
        out.append({
            "id": ch["id"], "name": ch["name"], "kind": ch["kind"], "alignment": ch["alignment"],
            "auto_alignment": bool(ch["auto_alignment"]), "law": law, "good": good,
            "computed_alignment": alignment_for(law, good, cfg), "event_count": totals[2],
        })
    return jsonify({"config": cfg, "characters": out})


@bp.post("/characters/<int:char_id>/saints-sinners")
def api_saints_sinners(char_id):
    """Move the Saints & Sinners score by exactly one point (+1 or -1),
    never past -100 or +100. A retried request (same op_id) counts once."""
    data = request.get_json(silent=True) or {}
    step = data.get("step")
    if step not in (1, -1) or isinstance(step, bool):
        raise F.ApiError("step must be 1 or -1")
    with tx() as conn:
        row = conn.execute("SELECT morality_score FROM characters WHERE id = ?", (char_id,)).fetchone()
        if row is None:
            raise F.NotFound("Character not found")
        if claim_op(conn, data.get("op_id")):
            new = max(SAINTS_SINNERS_MIN, min(SAINTS_SINNERS_MAX, row["morality_score"] + step))
            if new != row["morality_score"]:
                conn.execute("UPDATE characters SET morality_score = ?, updated_at = ? WHERE id = ?", (new, now_iso(), char_id))
        score = conn.execute("SELECT morality_score FROM characters WHERE id = ?", (char_id,)).fetchone()["morality_score"]
    return jsonify({"saints_sinners": saints_sinners_level(score)})
