"""Battle maps: grid, tokens, terrain painting and fog of war.

Token positions live here and nowhere else. HP, conditions and turn order stay
on characters/combatants; a token only *points at* a character or combatant,
so moving a token never touches combat data and vice versa.

player_view() is the only thing players ever receive. It drops hidden tokens,
hidden combatants, DM notes and everything under fog, and uploaded images are
masked server-side (fog_image) so the raw picture never reaches players.
"""
import hashlib
import json
import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file

from . import fields as F
from .db import get_db, new_uid, now_iso, tx

bp = Blueprint("maps", __name__, url_prefix="/api")

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
TERRAIN = ("floor", "wall", "water", "difficult", "pit", "door", "foliage")


def map_dict(row):
    d = F.decode_row(row, F.MAP)
    d["terrain"] = json.loads(row["terrain"] or "{}")
    for k in ("id", "uid", "campaign_id", "image", "image_w", "image_h", "revealed", "rev", "created_at", "updated_at"):
        d[k] = row[k]
    return d


def _map_row(conn, map_id):
    row = conn.execute("SELECT * FROM maps WHERE id = ?", (map_id,)).fetchone()
    if row is None:
        raise F.NotFound("Map not found")
    return row


def _bump(conn, map_id):
    conn.execute("UPDATE maps SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), map_id))


# ---- fog bitmap -----------------------------------------------------------------

def fog_get(m, x, y):
    i = y * m["cols"] + x
    return 0 <= x < m["cols"] and 0 <= y < m["rows"] and i < len(m["revealed"]) and m["revealed"][i] == "1"


def resize_bitmap(bits, old_cols, old_rows, cols, rows):
    out = []
    for y in range(rows):
        for x in range(cols):
            i = y * old_cols + x
            out.append(bits[i] if x < old_cols and y < old_rows and i < len(bits) else "0")
    return "".join(out)


def token_cells(t):
    """Grid cells a token covers (using its rounded position)."""
    x0, y0 = int(round(t["x"])), int(round(t["y"]))
    return [(x0 + dx, y0 + dy) for dx in range(t["size"]) for dy in range(t["size"])]


# ---- reading -------------------------------------------------------------------------

def tokens_for(conn, map_id, encounter_current=None):
    rows = conn.execute(
        """SELECT t.*, ch.name AS ch_name, ch.current_hp AS ch_hp, ch.max_hp AS ch_max, ch.status AS ch_status,
                  ch.portrait AS ch_portrait, ch.kind AS ch_kind, ch.conditions AS ch_conditions,
                  cb.name AS cb_name, cb.current_hp AS cb_hp, cb.max_hp AS cb_max, cb.status AS cb_status,
                  cb.character_id AS cb_char, cb.hidden AS cb_hidden, cb.conditions AS cb_conditions, cb.encounter_id AS cb_enc
           FROM map_tokens t
           LEFT JOIN combatants cb ON cb.id = t.combatant_id
           LEFT JOIN characters ch ON ch.id = COALESCE(t.character_id, cb.character_id)
           WHERE t.map_id = ? ORDER BY t.id""", (map_id,)).fetchall()
    out = []
    for r in rows:
        t = {k: v for k, v in F.decode_row(r, F.TOKEN).items() if not k.startswith(("cb_", "ch_"))}
        t.update(id=r["id"], character_id=r["character_id"] or r["cb_char"], combatant_id=r["combatant_id"])
        if r["ch_name"] is not None:
            t.update(name=r["ch_name"], hp=r["ch_hp"], max_hp=r["ch_max"], status=r["ch_status"],
                     portrait=r["ch_portrait"], conditions=[c["name"] for c in json.loads(r["ch_conditions"] or "[]")])
        elif r["cb_name"] is not None:
            t.update(name=r["cb_name"], hp=r["cb_hp"], max_hp=r["cb_max"], status=r["cb_status"], portrait=None,
                     conditions=[c["name"] for c in json.loads(r["cb_conditions"] or "[]")])
        else:
            t.update(name=t["label"], hp=None, max_hp=None, status=None, portrait=None, conditions=[])
        t["display"] = t["label"] or t["name"] or "?"
        t["combatant_hidden"] = bool(r["cb_hidden"])
        t["is_current"] = bool(encounter_current and r["combatant_id"] == encounter_current)
        out.append(t)
    return out


def encounter_summary(conn, enc_id):
    if not enc_id:
        return None
    enc = conn.execute("SELECT id, name, status, round, current_id, rev FROM encounters WHERE id = ?", (enc_id,)).fetchone()
    if enc is None:
        return None
    order = conn.execute(
        """SELECT c.id, COALESCE(ch.name, c.name) AS name, c.init_roll, c.kind, c.hidden,
                  COALESCE(ch.status, c.status) AS status, COALESCE(ch.current_hp, c.current_hp) AS hp,
                  COALESCE(ch.max_hp, c.max_hp) AS max_hp, c.character_id
           FROM combatants c LEFT JOIN characters ch ON ch.id = c.character_id
           WHERE c.encounter_id = ? ORDER BY c.sort_order, c.id""", (enc_id,)).fetchall()
    return dict(enc) | {"order": [dict(o) for o in order]}


def dm_state(map_id):
    conn = get_db()
    m = map_dict(_map_row(conn, map_id))
    enc = encounter_summary(conn, m["encounter_id"])
    live = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (m["campaign_id"],)).fetchone()["live_map_id"]
    return {"map": m, "tokens": tokens_for(conn, map_id, enc["current_id"] if enc and enc["status"] == "active" else None),
            "encounter": enc, "live": live == map_id}


def player_view(conn, map_id, player):
    """Everything a player may see of a map — and nothing else."""
    m = map_dict(_map_row(conn, map_id))
    enc = encounter_summary(conn, m["encounter_id"])
    current = enc["current_id"] if enc and enc["status"] == "active" else None
    fog = m["fog_enabled"]
    tokens = []
    for t in tokens_for(conn, map_id, current):
        if t["hidden"] or t["combatant_hidden"]:
            continue
        if fog and not any(fog_get(m, x, y) for x, y in token_cells(t)):
            continue
        own = bool(player.get("character_id") and t["character_id"] == player["character_id"])
        is_party = t["kind"] in ("pc", "npc") and t["character_id"]
        out = {k: t[k] for k in ("id", "kind", "x", "y", "size", "color", "display", "is_current", "portrait")}
        out["status"] = t["status"] if t["status"] in ("dead", "defeated", "unconscious", "fled") else None
        out["movable"] = own and bool(m["players_can_move"])
        out["own"] = own
        if is_party:
            out.update(hp=t["hp"], max_hp=t["max_hp"], conditions=t["conditions"])
        elif t["hp"] is not None and t["max_hp"]:
            out["health"] = "down" if t["hp"] <= 0 else ("bloodied" if t["hp"] * 2 <= t["max_hp"] else "")
        tokens.append(out)
    terrain = m["terrain"]
    if fog:
        terrain = {k: v for k, v in terrain.items() if fog_get(m, *map(int, k.split(",")))}
    public = {k: m[k] for k in ("id", "name", "cols", "rows", "cell_px", "offset_x", "offset_y", "scale_value",
                                "scale_unit", "show_grid", "grid_color", "grid_opacity", "snap", "bg_color",
                                "fog_enabled", "players_can_move", "image_w", "image_h", "rev")}
    public["terrain"] = terrain
    public["revealed"] = m["revealed"] if fog else ""
    public["image_url"] = f"/api/play/map-image/{map_id}?v={m['rev']}" if m["image"] else None
    return {"map": public, "tokens": tokens}


def fog_image(m, upload_dir, cache_dir):
    """The map image with unrevealed cells painted black, rendered on the
    server so hidden areas are never sent to players."""
    from PIL import Image, ImageDraw
    src = os.path.join(upload_dir, os.path.basename(m["image"]))
    if not m["fog_enabled"]:
        return src
    os.makedirs(cache_dir, exist_ok=True)
    sig = hashlib.sha1(json.dumps([m["revealed"], m["cols"], m["rows"], m["cell_px"], m["offset_x"], m["offset_y"], m["image"]]).encode()).hexdigest()[:16]
    key = f"fog-{m['id']}-{sig}.jpg"
    dest = os.path.join(cache_dir, key)
    if os.path.exists(dest):
        return dest
    for old in os.listdir(cache_dir):
        if old.startswith(f"fog-{m['id']}-"):
            try:
                os.remove(os.path.join(cache_dir, old))
            except OSError:
                pass
    img = Image.open(src).convert("RGB")
    cp, ox, oy = m["cell_px"], m["offset_x"], m["offset_y"]
    # Everything outside revealed cells (including outside the grid) stays black.
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    for y in range(m["rows"]):
        for x in range(m["cols"]):
            if fog_get(m, x, y):
                md.rectangle([ox + x * cp, oy + y * cp, ox + (x + 1) * cp - 1, oy + (y + 1) * cp - 1], fill=255)
    black = Image.new("RGB", img.size, (8, 7, 6))
    out = Image.composite(img, black, mask)
    out.save(dest, "JPEG", quality=85)
    return dest


# ---- DM endpoints -----------------------------------------------------------------

@bp.get("/campaigns/<int:cid>/maps")
def api_list(cid):
    conn = get_db()
    live = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (cid,)).fetchone()
    rows = conn.execute(
        "SELECT m.*, (SELECT COUNT(*) FROM map_tokens WHERE map_id = m.id) AS token_count FROM maps m "
        "WHERE campaign_id = ? ORDER BY updated_at DESC", (cid,)).fetchall()
    return jsonify({"maps": [map_dict(r) | {"token_count": r["token_count"]} for r in rows],
                    "live_map_id": live["live_map_id"] if live else None})


@bp.post("/campaigns/<int:cid>/maps")
def api_create(cid):
    data = dict(request.get_json(silent=True) or {})
    values = F.validate_new(F.MAP, {k: v for k, v in data.items() if k in F.MAP})
    if not values.get("name", "").strip():
        raise F.ApiError("Name the map")
    conn = get_db()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    _check_encounter(conn, cid, values.get("encounter_id"))
    values.setdefault("cols", 24)
    values.setdefault("rows", 16)
    ts = now_iso()
    with tx() as conn:
        mid = F.insert(conn, "maps", F.MAP, values, {"uid": new_uid(), "campaign_id": cid,
                                                     "revealed": "0" * (values["cols"] * values["rows"]),
                                                     "created_at": ts, "updated_at": ts})
    return jsonify(dm_state(mid)), 201


def _check_encounter(conn, cid, enc_id):
    if enc_id is None:
        return
    row = conn.execute("SELECT campaign_id FROM encounters WHERE id = ?", (enc_id,)).fetchone()
    if row is None or row["campaign_id"] != cid:
        raise F.ApiError("That encounter isn't in this campaign")


@bp.get("/maps/<int:map_id>")
def api_get(map_id):
    return jsonify(dm_state(map_id))


@bp.get("/maps/<int:map_id>/rev")
def api_rev(map_id):
    conn = get_db()
    m = _map_row(conn, map_id)
    enc_rev = None
    if m["encounter_id"]:
        e = conn.execute("SELECT rev FROM encounters WHERE id = ?", (m["encounter_id"],)).fetchone()
        enc_rev = e["rev"] if e else None
    return jsonify({"rev": m["rev"], "encounter_rev": enc_rev})


@bp.patch("/maps/<int:map_id>")
def api_patch(map_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        before = map_dict(_map_row(conn, map_id))
        if isinstance(changes, dict) and "encounter_id" in changes:
            _check_encounter(conn, before["campaign_id"], changes["encounter_id"].get("to"))
        if isinstance(changes, dict) and "name" in changes and not str(changes["name"].get("to", "")).strip():
            raise F.ApiError("Name can't be empty")
        row, updates = F.cas_patch(conn, "maps", F.MAP, map_id, changes)
        if "cols" in updates or "rows" in updates:
            bits = resize_bitmap(before["revealed"], before["cols"], before["rows"], row["cols"], row["rows"])
            conn.execute("UPDATE maps SET revealed = ? WHERE id = ?", (bits, map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.delete("/maps/<int:map_id>")
def api_delete(map_id):
    with tx() as conn:
        m = _map_row(conn, map_id)
        conn.execute("UPDATE campaigns SET live_map_id = NULL WHERE live_map_id = ?", (map_id,))
        conn.execute("DELETE FROM maps WHERE id = ?", (map_id,))
    return jsonify({"deleted": map_id, "campaign_id": m["campaign_id"]})


@bp.post("/maps/<int:map_id>/image")
def api_image(map_id):
    f = request.files.get("file")
    if f is None or not f.filename:
        raise F.ApiError("Choose an image")
    ext = IMAGE_TYPES.get(f.mimetype)
    if ext is None:
        raise F.ApiError("Map images must be PNG, JPEG or WebP")
    name = f"map-{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config["UPLOAD_DIR"], name)
    f.save(path)
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        os.remove(path)
        raise F.ApiError("That file couldn't be read as an image")
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        cell = m["cell_px"]
        cols, rows = max(1, min(200, w // cell)), max(1, min(200, h // cell))
        bits = resize_bitmap(m["revealed"], m["cols"], m["rows"], cols, rows)
        conn.execute("UPDATE maps SET image = ?, image_w = ?, image_h = ?, cols = ?, rows = ?, revealed = ?, "
                     "offset_x = 0, offset_y = 0 WHERE id = ?", (name, w, h, cols, rows, bits, map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.delete("/maps/<int:map_id>/image")
def api_image_clear(map_id):
    with tx() as conn:
        _map_row(conn, map_id)
        conn.execute("UPDATE maps SET image = NULL, image_w = 0, image_h = 0 WHERE id = ?", (map_id,))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


def _cells(data, m):
    cells = data.get("cells")
    if not isinstance(cells, list) or len(cells) > 40000:
        raise F.ApiError("cells must be a list of [x, y]")
    out = []
    for c in cells:
        try:
            x, y = int(c[0]), int(c[1])
        except (TypeError, ValueError, IndexError, KeyError):
            raise F.ApiError("cells must be a list of [x, y]")
        if 0 <= x < m["cols"] and 0 <= y < m["rows"]:
            out.append((x, y))
    return out


@bp.post("/maps/<int:map_id>/fog")
def api_fog(map_id):
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        n = m["cols"] * m["rows"]
        bits = list((m["revealed"] + "0" * n)[:n])
        if data.get("all") in ("reveal", "conceal"):
            bits = ["1" if data["all"] == "reveal" else "0"] * n
        else:
            v = "1" if data.get("reveal", True) else "0"
            for x, y in _cells(data, m):
                bits[y * m["cols"] + x] = v
        conn.execute("UPDATE maps SET revealed = ? WHERE id = ?", ("".join(bits), map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/maps/<int:map_id>/terrain")
def api_terrain(map_id):
    data = request.get_json(silent=True) or {}
    value = data.get("value")
    if value is not None and value not in TERRAIN:
        raise F.ApiError("Unknown terrain")
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        terrain = m["terrain"]
        for x, y in _cells(data, m):
            if value is None:
                terrain.pop(f"{x},{y}", None)
            else:
                terrain[f"{x},{y}"] = value
        conn.execute("UPDATE maps SET terrain = ? WHERE id = ?", (json.dumps(terrain), map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/maps/<int:map_id>/tokens")
def api_add_token(map_id):
    data = dict(request.get_json(silent=True) or {})
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        char_id, comb_id = data.pop("character_id", None), data.pop("combatant_id", None)
        values = F.validate_new(F.TOKEN, {k: v for k, v in data.items() if k in F.TOKEN})
        if char_id:
            ch = conn.execute("SELECT kind, campaign_id, name FROM characters WHERE id = ?", (char_id,)).fetchone()
            if ch is None or ch["campaign_id"] != m["campaign_id"]:
                raise F.ApiError("Character isn't in this campaign")
            values.setdefault("kind", ch["kind"])
        if comb_id:
            cb = conn.execute("SELECT c.kind, c.character_id, e.campaign_id FROM combatants c JOIN encounters e "
                              "ON e.id = c.encounter_id WHERE c.id = ?", (comb_id,)).fetchone()
            if cb is None or cb["campaign_id"] != m["campaign_id"]:
                raise F.ApiError("Combatant isn't in this campaign")
            values.setdefault("kind", cb["kind"])
        if not (char_id or comb_id or values.get("label", "").strip()):
            raise F.ApiError("Give the token a label")
        ts = now_iso()
        F.insert(conn, "map_tokens", F.TOKEN, values, {"uid": new_uid(), "map_id": map_id, "character_id": char_id,
                                                       "combatant_id": comb_id, "created_at": ts, "updated_at": ts})
        _bump(conn, map_id)
    return jsonify(dm_state(map_id)), 201


@bp.post("/maps/<int:map_id>/tokens/from-encounter")
def api_tokens_from_encounter(map_id):
    """Place a token for every combatant in the linked encounter that doesn't
    have one yet, lined up along the left edge for the DM to arrange."""
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        if not m["encounter_id"]:
            raise F.ApiError("Link this map to an encounter first")
        have = {r["combatant_id"] for r in conn.execute("SELECT combatant_id FROM map_tokens WHERE map_id = ?", (map_id,))}
        have_chars = {r["character_id"] for r in conn.execute("SELECT character_id FROM map_tokens WHERE map_id = ? AND character_id IS NOT NULL", (map_id,))}
        combs = conn.execute("SELECT * FROM combatants WHERE encounter_id = ? ORDER BY sort_order, id", (m["encounter_id"],)).fetchall()
        ts, added, i = now_iso(), 0, 0
        for cb in combs:
            if cb["id"] in have or (cb["character_id"] and cb["character_id"] in have_chars):
                continue
            x = 0 if cb["kind"] != "enemy" else max(0, m["cols"] - 1)
            conn.execute(
                "INSERT INTO map_tokens (uid, map_id, kind, combatant_id, x, y, size, hidden, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,1,?,?,?)",
                (new_uid(), map_id, cb["kind"], cb["id"], x, min(m["rows"] - 1, i), cb["hidden"], ts, ts))
            i += 1
            added += 1
        if not added:
            raise F.ApiError("Every combatant already has a token")
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


def _token_map(conn, token_id):
    row = conn.execute("SELECT map_id FROM map_tokens WHERE id = ?", (token_id,)).fetchone()
    if row is None:
        raise F.NotFound("Token not found")
    return row["map_id"]


def clamp_position(m, size, x, y):
    if m["snap"]:
        x, y = round(x), round(y)
    x = max(0.0, min(float(m["cols"] - size), float(x)))
    y = max(0.0, min(float(m["rows"] - size), float(y)))
    return round(x, 3), round(y, 3)


@bp.patch("/tokens/<int:token_id>")
def api_patch_token(token_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        map_id = _token_map(conn, token_id)
        F.cas_patch(conn, "map_tokens", F.TOKEN, token_id, changes)
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/tokens/<int:token_id>/move")
def api_move_token(token_id):
    """Positions are last-write-wins: the newest drag is the truth."""
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        map_id = _token_map(conn, token_id)
        m = map_dict(_map_row(conn, map_id))
        t = conn.execute("SELECT size FROM map_tokens WHERE id = ?", (token_id,)).fetchone()
        x = F.coerce(F.TOKEN["x"], data.get("x"), "x")
        y = F.coerce(F.TOKEN["y"], data.get("y"), "y")
        x, y = clamp_position(m, t["size"], x, y)
        conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (x, y, now_iso(), token_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.delete("/tokens/<int:token_id>")
def api_delete_token(token_id):
    with tx() as conn:
        map_id = _token_map(conn, token_id)
        conn.execute("DELETE FROM map_tokens WHERE id = ?", (token_id,))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/campaigns/<int:cid>/live-map")
def api_live(cid):
    data = request.get_json(silent=True) or {}
    map_id = data.get("map_id")
    with tx() as conn:
        if map_id is not None:
            m = _map_row(conn, int(map_id))
            if m["campaign_id"] != cid:
                raise F.ApiError("That map isn't in this campaign")
        conn.execute("UPDATE campaigns SET live_map_id = ? WHERE id = ?", (map_id, cid))
        if map_id:
            _bump(conn, int(map_id))
    return jsonify({"live_map_id": map_id})


@bp.get("/maps/<int:map_id>/player-preview")
def api_preview(map_id):
    """What a player would receive, so the DM can check before revealing."""
    return jsonify(player_view(get_db(), map_id, {"character_id": None}))
