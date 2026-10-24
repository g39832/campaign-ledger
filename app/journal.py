from flask import Blueprint, jsonify, request

from . import fields as F
from .db import get_db, new_uid, now_iso, tx

bp = Blueprint("journal", __name__, url_prefix="/api")

LINK_TABLES = {"character": "characters", "encounter": "encounters", "morality": "morality_events"}
LINK_LABEL = {"character": "name", "encounter": "name", "morality": "title"}


def _links(conn, entry_id):
    out = []
    for r in conn.execute("SELECT target_type, target_id FROM journal_links WHERE entry_id = ?", (entry_id,)):
        table = LINK_TABLES.get(r["target_type"])
        if not table:
            continue
        row = conn.execute(f"SELECT {LINK_LABEL[r['target_type']]} AS label FROM {table} WHERE id = ?",
                           (r["target_id"],)).fetchone()
        if row:
            out.append({"type": r["target_type"], "id": r["target_id"], "label": row["label"]})
    return out


def entry_dict(row, conn=None):
    d = F.decode_row(row, F.JOURNAL)
    d["links"] = _links(conn or get_db(), row["id"])
    return d


def search_entries(campaign_id, q="", kind="", limit=500):
    sql = "SELECT * FROM journal_entries WHERE campaign_id = ?"
    params = [campaign_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if q:
        for word in q.split()[:8]:
            sql += " AND (title LIKE ? OR body LIKE ? OR tags LIKE ? OR status LIKE ?)"
            params += [f"%{word}%"] * 4
    sql += (" ORDER BY pinned DESC, CASE WHEN kind = 'session' THEN COALESCE(session_number, 0) ELSE 0 END DESC,"
            " updated_at DESC LIMIT ?")
    params.append(limit)
    conn = get_db()
    return [entry_dict(r, conn) for r in conn.execute(sql, params).fetchall()]


@bp.get("/campaigns/<int:cid>/journal")
def api_list(cid):
    return jsonify({"entries": search_entries(cid, request.args.get("q", "").strip(), request.args.get("kind", ""))})


@bp.post("/campaigns/<int:cid>/journal")
def api_create(cid):
    data = dict(request.get_json(silent=True) or {})
    links = data.pop("links", [])
    values = F.validate_new(F.JOURNAL, data)
    values.setdefault("kind", "note")
    conn = get_db()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    if values["kind"] == "session" and values.get("session_number") is None:
        values["session_number"] = conn.execute(
            "SELECT COALESCE(MAX(session_number), 0) + 1 FROM journal_entries WHERE campaign_id = ? AND kind = 'session'",
            (cid,)).fetchone()[0]
    if not values.get("title"):
        values["title"] = f"Session {values['session_number']}" if values["kind"] == "session" else "Untitled"
    ts = now_iso()
    with tx() as conn:
        eid = F.insert(conn, "journal_entries", F.JOURNAL, values,
                       {"uid": new_uid(), "campaign_id": cid, "created_at": ts, "updated_at": ts})
        _set_links(conn, eid, cid, links)
        conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (ts, cid))
    return jsonify({"entry": entry_dict(get_db().execute("SELECT * FROM journal_entries WHERE id = ?", (eid,)).fetchone())}), 201


def _get_row(conn, eid):
    row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (eid,)).fetchone()
    if row is None:
        raise F.NotFound("Journal entry not found")
    return row


@bp.get("/journal/<int:eid>")
def api_get(eid):
    return jsonify({"entry": entry_dict(_get_row(get_db(), eid))})


@bp.patch("/journal/<int:eid>")
def api_patch(eid):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        F.cas_patch(conn, "journal_entries", F.JOURNAL, eid, changes)
    return jsonify({"entry": entry_dict(_get_row(get_db(), eid))})


def _set_links(conn, eid, campaign_id, links):
    if not isinstance(links, list):
        raise F.ApiError("links must be a list")
    conn.execute("DELETE FROM journal_links WHERE entry_id = ?", (eid,))
    for link in links:
        t, tid = link.get("type"), link.get("id")
        table = LINK_TABLES.get(t)
        if not table:
            raise F.ApiError(f"Can't link to {t}")
        row = conn.execute(f"SELECT campaign_id FROM {table} WHERE id = ?", (tid,)).fetchone()
        if row is None or row["campaign_id"] != campaign_id:
            raise F.ApiError("Linked item isn't in this campaign")
        conn.execute("INSERT OR IGNORE INTO journal_links (entry_id, target_type, target_id) VALUES (?,?,?)",
                     (eid, t, int(tid)))


@bp.put("/journal/<int:eid>/links")
def api_links(eid):
    links = (request.get_json(silent=True) or {}).get("links", [])
    with tx() as conn:
        row = _get_row(conn, eid)
        _set_links(conn, eid, row["campaign_id"], links)
        conn.execute("UPDATE journal_entries SET updated_at = ? WHERE id = ?", (now_iso(), eid))
    return jsonify({"entry": entry_dict(_get_row(get_db(), eid))})


@bp.delete("/journal/<int:eid>")
def api_delete(eid):
    with tx() as conn:
        _get_row(conn, eid)
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (eid,))
    return jsonify({"deleted": eid})


@bp.get("/links/<target_type>/<int:target_id>")
def api_backlinks(target_type, target_id):
    """Journal entries that mention a character, encounter or morality event."""
    rows = get_db().execute(
        """SELECT j.id, j.kind, j.title, j.session_number FROM journal_entries j
           JOIN journal_links l ON l.entry_id = j.id WHERE l.target_type = ? AND l.target_id = ?
           ORDER BY j.updated_at DESC""",
        (target_type, target_id)).fetchall()
    return jsonify({"entries": [dict(r) for r in rows]})
