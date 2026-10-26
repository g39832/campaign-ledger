"""Backup export and import.

A backup is a JSON file holding one or more campaigns with everything that
belongs to them (characters, morality history, encounters with combatants and
logs, journal entries and links, campaign creatures, portrait images), plus
the shared creature library. A SHA-256 checksum over the data detects files
that were truncated or corrupted.

Import is two steps: upload -> validate and show a report -> apply with an
explicit choice per campaign. The live database is snapshotted before any
import is applied, and campaigns not in the backup are never touched.
"""
import base64
import hashlib
import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file

from . import fields as F
from .db import SCHEMA_VERSION, get_db, new_uid, now_iso, snapshot, tx

bp = Blueprint("backup", __name__, url_prefix="/api")

FORMAT = "dnd-tracker-backup"
FORMAT_VERSION = 1

JSON_COLUMNS = {
    "campaigns": ["settings"],
    "characters": [k for k, s in F.CHARACTER.items() if s[0] == "json"],
    "morality_events": ["tags"],
    "creatures": ["abilities"],
    "combatants": ["conditions", "statblock"],
    "journal_entries": ["tags"],
    "maps": ["terrain", "shapes"],
    "rolls": ["result"],
}
CHILD_KEYS = ("characters", "morality_events", "creatures", "encounters", "journal", "combatants", "hp_changes",
              "log", "links", "maps", "tokens", "rolls")


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _columns(conn, table):
    return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def build_export(campaign_ids=None):
    conn = get_db()
    if campaign_ids is None:
        campaigns = _rows(conn, "SELECT * FROM campaigns ORDER BY id")
        scope = "full"
    else:
        marks = ",".join("?" * len(campaign_ids))
        campaigns = _rows(conn, f"SELECT * FROM campaigns WHERE id IN ({marks}) ORDER BY id", campaign_ids)
        scope = "campaign"
    out = []
    portraits = set()
    for c in campaigns:
        cid = c["id"]
        c["characters"] = _rows(conn, "SELECT * FROM characters WHERE campaign_id = ? ORDER BY id", (cid,))
        portraits.update(ch["portrait"] for ch in c["characters"] if ch["portrait"])
        c["morality_events"] = _rows(conn, "SELECT * FROM morality_events WHERE campaign_id = ? ORDER BY id", (cid,))
        c["creatures"] = _rows(conn, "SELECT * FROM creatures WHERE campaign_id = ? ORDER BY id", (cid,))
        encounters = _rows(conn, "SELECT * FROM encounters WHERE campaign_id = ? ORDER BY id", (cid,))
        for e in encounters:
            e["combatants"] = _rows(conn, "SELECT * FROM combatants WHERE encounter_id = ? ORDER BY id", (e["id"],))
            e["hp_changes"] = _rows(conn, "SELECT * FROM hp_changes WHERE encounter_id = ? ORDER BY id", (e["id"],))
            e["log"] = _rows(conn, "SELECT * FROM combat_log WHERE encounter_id = ? ORDER BY id", (e["id"],))
        c["encounters"] = encounters
        journal = _rows(conn, "SELECT * FROM journal_entries WHERE campaign_id = ? ORDER BY id", (cid,))
        for j in journal:
            j["links"] = _rows(conn, "SELECT target_type, target_id FROM journal_links WHERE entry_id = ?", (j["id"],))
        c["journal"] = journal
        maps_ = _rows(conn, "SELECT * FROM maps WHERE campaign_id = ? ORDER BY id", (cid,))
        for m in maps_:
            m["tokens"] = _rows(conn, "SELECT * FROM map_tokens WHERE map_id = ? ORDER BY id", (m["id"],))
            if m["image"]:
                portraits.add(m["image"])
        c["maps"] = maps_
        c["rolls"] = _rows(conn, "SELECT * FROM rolls WHERE campaign_id = ? ORDER BY id", (cid,))
        out.append(c)
    data = {
        "campaigns": out,
        "library": _rows(conn, "SELECT * FROM creatures WHERE campaign_id IS NULL ORDER BY id"),
        "files": _portrait_files(portraits),
    }
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "scope": scope,
        "exported_at": now_iso(),
        "checksum": checksum(data),
        "data": data,
    }


def _portrait_files(names):
    files = {}
    up = current_app.config["UPLOAD_DIR"]
    for n in sorted(names):
        p = os.path.join(up, os.path.basename(n))
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                files[n] = base64.b64encode(fh.read()).decode("ascii")
    return files


def checksum(data):
    canon = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _slug(name):
    keep = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    return "-".join(p for p in keep.split("-") if p)[:40] or "campaign"


@bp.get("/backup/export")
def api_export():
    cid = request.args.get("campaign_id", type=int)
    if cid:
        row = get_db().execute("SELECT name FROM campaigns WHERE id = ?", (cid,)).fetchone()
        if row is None:
            raise F.NotFound("Campaign not found")
        payload = build_export([cid])
        name = f"dnd-tracker-{_slug(row['name'])}-{datetime.now():%Y%m%d-%H%M}.json"
    else:
        payload = build_export()
        name = f"dnd-tracker-full-backup-{datetime.now():%Y%m%d-%H%M}.json"
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    resp = current_app.response_class(body, mimetype="application/json")
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


@bp.get("/backup/database")
def api_database():
    """A consistent copy of the whole SQLite file."""
    path = snapshot(current_app.config["DATABASE"], current_app.config["BACKUP_DIR"], "manual")
    return send_file(path, as_attachment=True, download_name=os.path.basename(path).replace("manual", "dnd-tracker-db"))


@bp.get("/backup/snapshots")
def api_snapshots():
    d = current_app.config["BACKUP_DIR"]
    items = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.endswith(".sqlite3"):
            st = os.stat(os.path.join(d, f))
            items.append({"name": f, "size": st.st_size,
                          "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return jsonify({"folder": os.path.abspath(d), "snapshots": items})


# ---- validation -------------------------------------------------------------

class Invalid(Exception):
    pass


def _check_rows(conn, table, rows, errors, where, required_fk=()):
    cols = _columns(conn, table)
    if not isinstance(rows, list):
        errors.append(f"{where}: {table} must be a list")
        return
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            errors.append(f"{where}: {table}[{i}] is not an object")
            continue
        for k, v in r.items():
            if k in CHILD_KEYS:
                continue
            if k not in cols:
                errors.append(f"{where}: {table} has unknown column '{k}' (backup from a different version?)")
                return
        for name, col in cols.items():
            if col["notnull"] and col["dflt_value"] is None and name not in r and name not in required_fk:
                errors.append(f"{where}: {table}[{i}] is missing '{name}'")
                return
            if name in r and r[name] is not None:
                t = (col["type"] or "").upper()
                if t == "INTEGER" and (not isinstance(r[name], int) or isinstance(r[name], bool)):
                    errors.append(f"{where}: {table}[{i}].{name} should be a whole number")
                    return
                if t == "TEXT" and not isinstance(r[name], str):
                    errors.append(f"{where}: {table}[{i}].{name} should be text")
                    return
        for jc in JSON_COLUMNS.get(table, []):
            if jc in r:
                try:
                    json.loads(r[jc])
                except (TypeError, ValueError):
                    errors.append(f"{where}: {table}[{i}].{jc} is not valid JSON")
                    return


def validate_backup(payload):
    """Returns (report, errors). Never writes anything."""
    errors, warnings = [], []
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise Invalid("This isn't a D&D Tracker backup file.")
    if payload.get("version") != FORMAT_VERSION:
        raise Invalid(f"Backup format version {payload.get('version')} isn't supported by this app (needs {FORMAT_VERSION}).")
    if not isinstance(payload.get("schema_version"), int) or payload["schema_version"] > SCHEMA_VERSION:
        raise Invalid("This backup was made by a newer version of the app. Update the app first.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise Invalid("The backup has no data section.")
    if payload.get("checksum") != checksum(data):
        raise Invalid("The checksum doesn't match — the file is damaged or was edited. Nothing was imported.")

    conn = get_db()
    report = []
    for ci, c in enumerate(data.get("campaigns") or []):
        where = f"campaign {ci + 1}"
        _check_rows(conn, "campaigns", [c], errors, where)
        if errors:
            break
        where = f"campaign “{c.get('name')}”"
        for key, table in (("characters", "characters"), ("morality_events", "morality_events"),
                           ("creatures", "creatures"), ("encounters", "encounters"), ("journal", "journal_entries")):
            _check_rows(conn, table, c.get(key, []), errors, where)
        _check_rows(conn, "maps", c.get("maps", []), errors, where)
        for m in c.get("maps", []) or []:
            _check_rows(conn, "map_tokens", m.get("tokens", []), errors, where, required_fk=("map_id",))
        _check_rows(conn, "rolls", c.get("rolls", []), errors, where)
        for e in c.get("encounters", []) or []:
            _check_rows(conn, "combatants", e.get("combatants", []), errors, where)
            _check_rows(conn, "hp_changes", e.get("hp_changes", []), errors, where, required_fk=("encounter_id",))
            _check_rows(conn, "combat_log", e.get("log", []), errors, where)
        if errors:
            break
        char_ids = {ch["id"] for ch in c.get("characters", [])}
        missing = [m for m in c.get("morality_events", []) if m["character_id"] not in char_ids]
        if missing:
            errors.append(f"{where}: {len(missing)} morality events point at characters that aren't in the backup")
        dangling = sum(1 for j in c.get("journal", []) for l in j.get("links", [])
                       if l.get("target_type") not in ("character", "encounter", "morality"))
        if dangling:
            warnings.append(f"{where}: {dangling} journal links of unknown type will be dropped")
        local = conn.execute("SELECT id, name, archived FROM campaigns WHERE uid = ?", (c.get("uid"),)).fetchone()
        report.append({
            "uid": c.get("uid"),
            "name": c.get("name"),
            "archived": bool(c.get("archived")),
            "counts": {
                "characters": len(c.get("characters", [])),
                "morality_events": len(c.get("morality_events", [])),
                "encounters": len(c.get("encounters", [])),
                "journal": len(c.get("journal", [])),
                "creatures": len(c.get("creatures", [])),
                "maps": len(c.get("maps", [])),
                "rolls": len(c.get("rolls", [])),
            },
            "exists": bool(local),
            "local_name": local["name"] if local else None,
        })
    lib = data.get("library") or []
    _check_rows(conn, "creatures", lib, errors, "creature library")
    new_lib = [cr for cr in lib if isinstance(cr, dict) and
               conn.execute("SELECT 1 FROM creatures WHERE uid = ?", (cr.get("uid"),)).fetchone() is None]
    if not isinstance(data.get("files", {}), dict):
        errors.append("files section is malformed")
    return {
        "scope": payload.get("scope"),
        "exported_at": payload.get("exported_at"),
        "campaigns": report,
        "library_total": len(lib),
        "library_new": len(new_lib),
        "warnings": warnings,
    }, errors


@bp.post("/backup/inspect")
def api_inspect():
    f = request.files.get("file")
    if f is None:
        raise F.ApiError("Choose a backup file")
    raw = f.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise F.ApiError("That file isn't valid JSON, so it can't be a backup from this app.")
    try:
        report, errors = validate_backup(payload)
    except Invalid as e:
        raise F.ApiError(str(e))
    if errors:
        raise F.ApiError("The backup failed validation. Nothing was imported.", details=errors[:20])
    token = uuid.uuid4().hex
    with open(os.path.join(current_app.config["IMPORT_DIR"], f"{token}.json"), "wb") as fh:
        fh.write(raw)
    report["token"] = token
    return jsonify(report)


# ---- applying ---------------------------------------------------------------

def _insert_row(conn, table, row, overrides, fresh_uid=False):
    cols = _columns(conn, table)
    vals = {k: v for k, v in row.items() if k in cols and k != "id"}
    vals.update(overrides)
    if "uid" in cols and (fresh_uid or conn.execute(
            f"SELECT 1 FROM {table} WHERE uid = ?", (vals.get("uid"),)).fetchone()):
        vals["uid"] = new_uid()
    keys = list(vals)
    cur = conn.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                       [vals[k] for k in keys])
    return cur.lastrowid


def delete_campaign_data(conn, cid):
    conn.execute("DELETE FROM rolls WHERE campaign_id = ?", (cid,))
    conn.execute("DELETE FROM players WHERE campaign_id = ?", (cid,))
    conn.execute("DELETE FROM maps WHERE campaign_id = ?", (cid,))  # cascades tokens
    conn.execute("DELETE FROM journal_links WHERE entry_id IN (SELECT id FROM journal_entries WHERE campaign_id = ?)", (cid,))
    conn.execute("DELETE FROM journal_entries WHERE campaign_id = ?", (cid,))
    conn.execute("DELETE FROM encounters WHERE campaign_id = ?", (cid,))  # cascades combatants, log, hp changes
    conn.execute("DELETE FROM morality_events WHERE campaign_id = ?", (cid,))
    conn.execute("UPDATE combatants SET creature_id = NULL WHERE creature_id IN (SELECT id FROM creatures WHERE campaign_id = ?)", (cid,))
    conn.execute("DELETE FROM creatures WHERE campaign_id = ?", (cid,))
    conn.execute("UPDATE hp_changes SET character_id = NULL WHERE character_id IN (SELECT id FROM characters WHERE campaign_id = ?)", (cid,))
    conn.execute("DELETE FROM characters WHERE campaign_id = ?", (cid,))
    conn.execute("DELETE FROM campaigns WHERE id = ?", (cid,))


def import_campaign(conn, c, mode, lib_map):
    fresh = mode == "copy"
    camp_over = {}
    if mode == "copy":
        camp_over["name"] = f"{c['name']} (imported copy)"
    if mode == "replace":
        local = conn.execute("SELECT id FROM campaigns WHERE uid = ?", (c["uid"],)).fetchone()
        if local:
            delete_campaign_data(conn, local["id"])
    camp_over.update(join_code=None, live_map_id=None)  # join codes are per-install; live map remapped below
    cid = _insert_row(conn, "campaigns", c, camp_over, fresh)

    char_map, cr_map, ev_map, enc_map, comb_map = {}, dict(lib_map), {}, {}, {}
    for ch in c.get("characters", []):
        char_map[ch["id"]] = _insert_row(conn, "characters", ch, {"campaign_id": cid}, fresh)
    for cr in c.get("creatures", []):
        cr_map[cr["id"]] = _insert_row(conn, "creatures", cr, {"campaign_id": cid}, fresh)
    # Morality events: insert in id order so reversals can point at their originals.
    for ev in sorted(c.get("morality_events", []), key=lambda e: e["id"]):
        ev_map[ev["id"]] = _insert_row(conn, "morality_events", ev, {
            "campaign_id": cid, "character_id": char_map[ev["character_id"]],
            "reverses_id": ev_map.get(ev.get("reverses_id")),
        }, fresh)
    for e in c.get("encounters", []):
        eid = _insert_row(conn, "encounters", e, {"campaign_id": cid, "current_id": None}, fresh)
        enc_map[e["id"]] = eid
        for cb in e.get("combatants", []):
            conds = cb.get("conditions", "[]")
            comb_map[cb["id"]] = _insert_row(conn, "combatants", cb, {
                "encounter_id": eid,
                "character_id": char_map.get(cb.get("character_id")),
                "creature_id": cr_map.get(cb.get("creature_id")),
                "conditions": conds,
            }, fresh)
        if e.get("current_id") in comb_map:
            conn.execute("UPDATE encounters SET current_id = ? WHERE id = ?", (comb_map[e["current_id"]], eid))
        for h in e.get("hp_changes", []):
            _insert_row(conn, "hp_changes", h, {
                "encounter_id": eid, "combatant_id": comb_map.get(h.get("combatant_id")),
                "character_id": char_map.get(h.get("character_id")),
            })
        for lg in e.get("log", []):
            _insert_row(conn, "combat_log", lg, {"encounter_id": eid})
    # Condition durations reference combatant ids and encounter ids; remap them.
    _remap_conditions(conn, cid, enc_map, comb_map)
    map_map = {}
    for m in c.get("maps", []):
        mid = _insert_row(conn, "maps", m, {"campaign_id": cid, "encounter_id": enc_map.get(m.get("encounter_id"))}, fresh)
        map_map[m["id"]] = mid
        for t in m.get("tokens", []):
            _insert_row(conn, "map_tokens", t, {"map_id": mid, "character_id": char_map.get(t.get("character_id")),
                                                "combatant_id": comb_map.get(t.get("combatant_id"))}, fresh)
    if c.get("live_map_id") in map_map:
        conn.execute("UPDATE campaigns SET live_map_id = ? WHERE id = ?", (map_map[c["live_map_id"]], cid))
    for r in c.get("rolls", []):
        _insert_row(conn, "rolls", r, {"campaign_id": cid, "player_id": None, "op_id": None,
                                       "character_id": char_map.get(r.get("character_id")),
                                       "combatant_id": comb_map.get(r.get("combatant_id")),
                                       "encounter_id": enc_map.get(r.get("encounter_id"))}, fresh)
    targets = {"character": char_map, "encounter": enc_map, "morality": ev_map}
    for j in c.get("journal", []):
        jid = _insert_row(conn, "journal_entries", j, {"campaign_id": cid}, fresh)
        for l in j.get("links", []):
            m = targets.get(l.get("target_type"))
            if m and l.get("target_id") in m:
                conn.execute("INSERT OR IGNORE INTO journal_links (entry_id, target_type, target_id) VALUES (?,?,?)",
                             (jid, l["target_type"], m[l["target_id"]]))
    return cid


def _remap_conditions(conn, cid, enc_map, comb_map):
    def fix(conds):
        changed = False
        for cond in conds:
            if cond.get("encounter_id") in enc_map:
                cond["encounter_id"] = enc_map[cond["encounter_id"]]
                changed = True
            if cond.get("tick_on") in comb_map:
                cond["tick_on"] = comb_map[cond["tick_on"]]
                changed = True
        return changed
    for r in conn.execute("SELECT id, conditions FROM characters WHERE campaign_id = ?", (cid,)).fetchall():
        conds = json.loads(r["conditions"])
        if fix(conds):
            conn.execute("UPDATE characters SET conditions = ? WHERE id = ?", (json.dumps(conds), r["id"]))
    for r in conn.execute("SELECT c.id, c.conditions FROM combatants c JOIN encounters e ON e.id = c.encounter_id "
                          "WHERE e.campaign_id = ?", (cid,)).fetchall():
        conds = json.loads(r["conditions"])
        if fix(conds):
            conn.execute("UPDATE combatants SET conditions = ? WHERE id = ?", (json.dumps(conds), r["id"]))


def apply_import(payload, decisions):
    report, errors = validate_backup(payload)
    if errors:
        raise F.ApiError("The backup failed validation. Nothing was imported.", details=errors[:20])
    data = payload["data"]
    for c in report["campaigns"]:
        mode = decisions.get(c["uid"], "skip")
        if mode not in ("add", "replace", "copy", "skip"):
            raise F.ApiError(f"Unknown import choice '{mode}'")
        if mode == "add" and c["exists"]:
            raise F.ApiError(f"“{c['name']}” already exists here. Choose replace, copy or skip for it.")
        if mode == "replace" and not c["exists"]:
            decisions[c["uid"]] = "add"
    if not any(decisions.get(c["uid"], "skip") != "skip" for c in report["campaigns"]) and not decisions.get("_library"):
        raise F.ApiError("Nothing selected to import")

    snap = snapshot(current_app.config["DATABASE"], current_app.config["BACKUP_DIR"], "before-import")
    imported = []
    with tx() as conn:
        lib_map = {}
        for cr in data.get("library") or []:
            existing = conn.execute("SELECT id FROM creatures WHERE uid = ?", (cr["uid"],)).fetchone()
            if existing:
                lib_map[cr["id"]] = existing["id"]
            elif decisions.get("_library", True):
                lib_map[cr["id"]] = _insert_row(conn, "creatures", cr, {"campaign_id": None})
        for c in data.get("campaigns") or []:
            mode = decisions.get(c["uid"], "skip")
            if mode == "skip":
                continue
            new_id = import_campaign(conn, c, mode, lib_map)
            imported.append({"id": new_id, "name": c["name"], "mode": mode})
    up = current_app.config["UPLOAD_DIR"]
    for name, b64 in (data.get("files") or {}).items():
        p = os.path.join(up, os.path.basename(name))
        if not os.path.exists(p):
            with open(p, "wb") as fh:
                fh.write(base64.b64decode(b64))
    return {"imported": imported, "snapshot": os.path.basename(snap)}


@bp.post("/backup/import")
def api_import():
    body = request.get_json(silent=True) or {}
    token = str(body.get("token", ""))
    if not token.isalnum():
        raise F.ApiError("Upload the backup again")
    path = os.path.join(current_app.config["IMPORT_DIR"], f"{token}.json")
    if not os.path.exists(path):
        raise F.ApiError("That upload has expired. Choose the file again.")
    with open(path, "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8-sig"))
    result = apply_import(payload, dict(body.get("decisions") or {}))
    os.remove(path)
    return jsonify(result)
