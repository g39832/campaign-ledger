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
TERRAIN = ("floor", "wall", "water", "difficult", "pit", "door", "foliage",
           "grass", "sand", "stone", "wood", "lava", "ice", "rubble", "tree", "table", "rock")
# Squares a token can't stand in when the app places tokens for you.
BLOCKING = {"wall", "pit", "water", "lava", "tree", "table", "rock"}
# Solid squares nobody can walk into or through (a player's move is refused).
SOLID = {"wall", "rock"}
# Ground a spell like Mend Earth puts right again.
MENDABLE = {"rock", "rubble", "difficult", "pit"}


def blocked_path(m, size, x0, y0, x1, y1):
    """The first solid square a token of this size would cross going from (x0, y0) to
    (x1, y1) in a straight line, or None. Checked every half square along the way."""
    terrain = m["terrain"]
    if not any(v in SOLID for v in terrain.values()):
        return None
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) * 2))
    for i in range(1, steps + 1):
        x, y = x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps
        for dx in range(size):
            for dy in range(size):
                k = f"{int(round(x)) + dx},{int(round(y)) + dy}"
                if terrain.get(k) in SOLID:
                    return k
    return None
SHAPE_KINDS = ("circle", "cone", "line", "square")


def map_dict(row):
    d = F.decode_row(row, F.MAP)
    d["terrain"] = json.loads(row["terrain"] or "{}")
    d["shapes"] = json.loads(row["shapes"] or "[]") if "shapes" in row.keys() else []
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


def _unlinked_party(conn, map_id):
    return conn.execute(
        "SELECT t.id, t.character_id FROM map_tokens t JOIN maps m ON m.id = t.map_id "
        "JOIN encounters e ON e.id = m.encounter_id AND e.status != 'ended' "
        "WHERE t.map_id = ? AND t.character_id IS NOT NULL AND t.combatant_id IS NULL", (map_id,)).fetchall()


def link_party(conn, map_id):
    """Heroes standing on a map are in its fight. A character's token joins the
    map's encounter (if they aren't in it yet) and points at their combatant, so
    they can be attacked, healed and buffed from the map. The token keeps its
    character, so it stays on the map even if the fight is deleted later.
    Returns the names that joined the fight."""
    from .combat import Ctx, _next_sort
    from .rules import derived
    rows = _unlinked_party(conn, map_id)
    if not rows:
        return []
    eid = conn.execute("SELECT encounter_id FROM maps WHERE id = ?", (map_id,)).fetchone()["encounter_id"]
    ctx, added = Ctx(conn, eid), []
    for t in rows:
        cb = conn.execute("SELECT id FROM combatants WHERE encounter_id = ? AND character_id = ?", (eid, t["character_id"])).fetchone()
        if cb is None:
            ch = conn.execute("SELECT * FROM characters WHERE id = ? AND campaign_id = ?", (t["character_id"], ctx.enc["campaign_id"])).fetchone()
            if ch is None:
                continue
            chd = F.decode_row(ch, F.CHARACTER)
            cur = conn.execute(
                """INSERT INTO combatants (uid, encounter_id, character_id, kind, name, init_mod, init_roll,
                   sort_order, max_hp, current_hp, ac, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_uid(), eid, ch["id"], ch["kind"], ch["name"], derived(chd)["initiative"], ch["initiative_roll"],
                 _next_sort(ctx), ch["max_hp"], ch["current_hp"], ch["ac"], now_iso()))
            cb_id = cur.lastrowid
            added.append(ch["name"])
        else:
            cb_id = cb["id"]
        conn.execute("UPDATE map_tokens SET combatant_id = ?, updated_at = ? WHERE id = ?", (cb_id, now_iso(), t["id"]))
    if added:
        ctx.log("roster", f"{', '.join(added)} joined the fight from the battle map")
    conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
    _bump(conn, map_id)
    return added


def dm_state(map_id):
    conn = get_db()
    if _unlinked_party(conn, map_id):  # maps made before heroes were linked automatically
        with tx() as c2:
            link_party(c2, map_id)
    m = map_dict(_map_row(conn, map_id))
    enc = encounter_summary(conn, m["encounter_id"])
    live = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (m["campaign_id"],)).fetchone()["live_map_id"]
    move = None
    zones = fight_zones(conn, map_id, enc)
    if enc and enc["status"] == "active" and enc["current_id"]:
        from .movement import turn_info
        move = turn_info(conn, enc["current_id"])  # how far whoever's turn it is can still go
    return {"map": m, "tokens": tokens_for(conn, map_id, enc["current_id"] if enc and enc["status"] == "active" else None),
            "encounter": enc, "live": live == map_id, "pings": recent_pings(map_id), "move": move, "zones": zones}


def fight_zones(conn, map_id, enc):
    """Zones up in this map's fight (Spirit Guardians around Lux), to draw: {token, half, name}."""
    if not enc or enc["status"] != "active":
        return []
    from .movement import _token_of, active_zones
    out = []
    for z in active_zones(conn, enc["id"]):
        t = conn.execute("SELECT t.id FROM map_tokens t LEFT JOIN combatants c ON c.id = ? WHERE t.map_id = ? AND (t.combatant_id = ? "
                         "OR (c.character_id IS NOT NULL AND t.character_id = c.character_id)) LIMIT 1",
                         (z["cb_id"], map_id, z["cb_id"])).fetchone()
        if t:
            out.append({"token": t["id"], "half": z["half"], "name": z["name"], "side": z["side"]})
    return out


def _disengaged(conn, char_id):
    from .play import is_disengaged
    return is_disengaged(conn, char_id)


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
        out = {k: t[k] for k in ("id", "kind", "x", "y", "size", "color", "display", "is_current", "portrait", "combatant_id")}
        out["status"] = t["status"] if t["status"] in ("dead", "defeated", "unconscious", "fled") else None
        out["movable"] = own and (bool(m["players_can_move"]) or _disengaged(conn, t["character_id"]))
        if out["movable"]:
            from .movement import fight_turn
            turn = fight_turn(conn, m, t["character_id"])
            out["movable"] = turn is None or (turn["my_turn"] and turn["left"] > 0)
        out["own"] = own
        if is_party:
            out.update(hp=t["hp"], max_hp=t["max_hp"], conditions=t["conditions"], character_id=t["character_id"])
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
    public["shapes"] = [{k: v for k, v in s.items() if k != "hidden"} for s in m["shapes"] if not s.get("hidden")]
    visible = {t["id"] for t in tokens}
    zones = [z for z in fight_zones(conn, map_id, enc) if z["token"] in visible]
    return {"map": public, "tokens": tokens, "pings": recent_pings(map_id), "zones": zones}


# ---- pings: "look here!" ripples that everyone sees for a few seconds --------------
# Kept in memory only: they're gone in seconds anyway.
PING_SECONDS = 6


def _ping_store():
    return current_app.extensions.setdefault("map_pings", {})


def recent_pings(map_id):
    import time
    now = time.time()
    store = _ping_store()
    keep = [p for p in store.get(map_id, []) if now - p["t"] < PING_SECONDS]
    store[map_id] = keep
    return [{"id": p["id"], "x": p["x"], "y": p["y"], "by": p["by"], "color": p["color"], "age": round(now - p["t"], 2)}
            | ({"fx": p["fx"]} if p.get("fx") else {}) for p in keep]


def add_ping(map_id, x, y, by, color):
    import time
    store = _ping_store()
    pings = [p for p in store.get(map_id, []) if time.time() - p["t"] < PING_SECONDS]
    mine = [p for p in pings if p["by"] == by and not p.get("fx")]
    if len(mine) >= 3:  # no spamming: three at a time each
        pings.remove(mine[0])
    pings.append({"id": uuid.uuid4().hex[:10], "x": round(float(x), 2), "y": round(float(y), 2), "by": str(by)[:40],
                  "color": color, "t": time.time()})
    store[map_id] = pings[-30:]


def add_fx(map_id, fx):
    """An attack's animation (a slash, a fire bolt...) that everyone looking at the map sees once.
    It rides along with the pings: short-lived, kept in memory only."""
    import time
    store = _ping_store()
    keep = [p for p in store.get(map_id, []) if time.time() - p["t"] < PING_SECONDS]
    x, y = fx["to"][0] if fx.get("to") else fx.get("from") or (0, 0)
    keep.append({"id": uuid.uuid4().hex[:10], "x": x, "y": y, "by": "", "color": "", "t": time.time(), "fx": fx})
    store[map_id] = keep[-40:]


def attack_fx(conn, enc_id, attacker_id, hits, name, kind="damage", damage_type=""):
    """Show an attack on every map of this fight: from the attacker's token to each target's.
    hits: [(combatant id, how)] with how = hit, crit, miss, saved, failed, auto."""
    from .movement import _token_of
    maps = conn.execute("SELECT id FROM maps WHERE encounter_id = ?", (enc_id,)).fetchall()
    for m in maps:
        a = _token_of(conn, m["id"], attacker_id) if attacker_id else None
        to, hows = [], []
        for cid, how in hits:
            t = _token_of(conn, m["id"], cid)
            if t:
                to.append([round(t["x"] + t["size"] / 2, 2), round(t["y"] + t["size"] / 2, 2)])
                hows.append(how)
        if not to and not a:
            continue
        add_fx(m["id"], {"name": str(name or "")[:60], "kind": kind or "damage", "type": str(damage_type or "")[:20],
                         "from": [round(a["x"] + a["size"] / 2, 2), round(a["y"] + a["size"] / 2, 2)] if a else None,
                         "to": to, "how": hows})


@bp.post("/maps/<int:map_id>/fx")
def api_fx(map_id):
    """The DM's map resolved an attack on its own (rolls, then HP): show it to everyone.
    {by: attacker combatant id, targets: [{id, how}], name, kind, damage_type}"""
    data = request.get_json(silent=True) or {}
    conn = get_db()
    m = map_dict(_map_row(conn, map_id))
    if not m["encounter_id"]:
        return jsonify({"pings": recent_pings(map_id)})
    hits = [(int(t["id"]), str(t.get("how") or "hit")[:10]) for t in (data.get("targets") or [])[:20] if isinstance(t, dict) and str(t.get("id", "")).isdigit()]
    attack_fx(conn, m["encounter_id"], int(data["by"]) if str(data.get("by", "")).isdigit() else None, hits,
              data.get("name"), data.get("kind") or "damage", data.get("damage_type") or "")
    return jsonify({"pings": recent_pings(map_id)})


def _ping_xy(data, m):
    try:
        x, y = float(data.get("x")), float(data.get("y"))
    except (TypeError, ValueError):
        raise F.ApiError("Ping needs x and y")
    if not (0 <= x <= m["cols"] and 0 <= y <= m["rows"]):
        raise F.ApiError("That's off the map")
    return x, y


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


@bp.get("/map-presets")
def api_presets():
    from .map_presets import listing
    return jsonify({"presets": listing()})


def create_map_from_preset(conn, cid, key, name=None, encounter_id=None):
    from .map_presets import build
    p = build(key)
    if p is None:
        raise F.ApiError("Unknown map preset")
    ts = now_iso()
    values = {"name": (name or p["name"])[:200], "cols": p["cols"], "rows": p["rows"], "bg_color": p["bg_color"],
              "encounter_id": encounter_id}
    mid = F.insert(conn, "maps", F.MAP, values, {"uid": new_uid(), "campaign_id": cid,
                                                 "revealed": "0" * (p["cols"] * p["rows"]), "created_at": ts, "updated_at": ts})
    conn.execute("UPDATE maps SET terrain = ? WHERE id = ?", (json.dumps(p["terrain"]), mid))
    return mid


@bp.post("/campaigns/<int:cid>/maps")
def api_create(cid):
    data = dict(request.get_json(silent=True) or {})
    if data.get("preset"):
        conn = get_db()
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
            raise F.NotFound("Campaign not found")
        _check_encounter(conn, cid, data.get("encounter_id"))
        with tx() as conn:
            mid = create_map_from_preset(conn, cid, str(data["preset"]), name=str(data.get("name") or "").strip() or None,
                                         encounter_id=data.get("encounter_id"))
        return jsonify(dm_state(mid)), 201
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
    pings = recent_pings(map_id)
    return jsonify({"rev": m["rev"], "encounter_rev": enc_rev, "ping": pings[-1]["id"] if pings else None})


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
        if "encounter_id" in updates:
            link_party(conn, map_id)
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
            if _has_character_token(conn, map_id, char_id):
                raise F.ApiError(f"{ch['name']} already has a token on this map")
            values.setdefault("kind", ch["kind"])
        if comb_id:
            cb = conn.execute("SELECT c.kind, c.character_id, e.campaign_id FROM combatants c JOIN encounters e "
                              "ON e.id = c.encounter_id WHERE c.id = ?", (comb_id,)).fetchone()
            if cb is None or cb["campaign_id"] != m["campaign_id"]:
                raise F.ApiError("Combatant isn't in this campaign")
            if conn.execute("SELECT 1 FROM map_tokens WHERE map_id = ? AND combatant_id = ?", (map_id, comb_id)).fetchone()                     or (cb["character_id"] and _has_character_token(conn, map_id, cb["character_id"])):
                raise F.ApiError("That combatant already has a token on this map")
            values.setdefault("kind", cb["kind"])
        if not (char_id or comb_id or values.get("label", "").strip()):
            raise F.ApiError("Give the token a label")
        ts = now_iso()
        F.insert(conn, "map_tokens", F.TOKEN, values, {"uid": new_uid(), "map_id": map_id, "character_id": char_id,
                                                       "combatant_id": comb_id, "created_at": ts, "updated_at": ts})
        _bump(conn, map_id)
    return jsonify(dm_state(map_id)), 201


def _has_character_token(conn, map_id, char_id):
    """True if the character is already on the map, directly or through a combatant."""
    return conn.execute(
        "SELECT 1 FROM map_tokens t LEFT JOIN combatants c ON c.id = t.combatant_id "
        "WHERE t.map_id = ? AND (t.character_id = ? OR c.character_id = ?)", (map_id, char_id, char_id)).fetchone() is not None


def place_encounter_tokens(conn, map_id):
    """Give every combatant in the map's linked encounter a token if it doesn't
    have one yet: the party down the left edge, enemies down the right edge,
    for the DM to arrange. Returns how many were placed."""
    m = map_dict(_map_row(conn, map_id))
    if not m["encounter_id"]:
        raise F.ApiError("Link this map to an encounter first")
    have = {r["combatant_id"] for r in conn.execute("SELECT combatant_id FROM map_tokens WHERE map_id = ?", (map_id,))}
    combs = conn.execute("SELECT * FROM combatants WHERE encounter_id = ? ORDER BY sort_order, id", (m["encounter_id"],)).fetchall()
    todo = [cb for cb in combs
            if cb["id"] not in have and not (cb["character_id"] and _has_character_token(conn, map_id, cb["character_id"]))]
    side_of = lambda cb: "right" if cb["kind"] == "enemy" else "left"
    # Leave a blank row between tokens when the map is tall enough, so name labels don't overlap.
    step = {s: 2 if 2 * sum(side_of(cb) == s for cb in todo) - 1 <= m["rows"] else 1 for s in ("left", "right")}
    taken = {(int(round(r["x"])), int(round(r["y"]))) for r in conn.execute("SELECT x, y FROM map_tokens WHERE map_id = ?", (map_id,))}
    open_ = lambda x, y: m["terrain"].get(f"{x},{y}") not in BLOCKING and (x, y) not in taken

    def spot(side, y):
        # Nearest open square to that edge on this row (then the rows around it).
        cols = range(m["cols"] - 1, -1, -1) if side == "right" else range(m["cols"])
        for dy in (0, 1, -1, 2, -2):
            yy = y + dy
            if 0 <= yy < m["rows"]:
                for x in list(cols)[: max(1, m["cols"] // 2)]:
                    if open_(x, yy):
                        return x, yy
        return (max(0, m["cols"] - 1) if side == "right" else 0), y
    ts, added, row = now_iso(), 0, {"left": 0, "right": 0}
    for cb in todo:
        side = side_of(cb)
        x, y = spot(side, min(m["rows"] - 1, row[side]))
        taken.add((x, y))
        row[side] += step[side]
        conn.execute(
            "INSERT INTO map_tokens (uid, map_id, kind, combatant_id, x, y, size, hidden, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?)",
            (new_uid(), map_id, cb["kind"], cb["id"], x, y, cb["hidden"], ts, ts))
        added += 1
    if added:
        _bump(conn, map_id)
    return added


@bp.post("/maps/<int:map_id>/tokens/from-encounter")
def api_tokens_from_encounter(map_id):
    with tx() as conn:
        if not place_encounter_tokens(conn, map_id):
            raise F.ApiError("Every combatant already has a token")
    return jsonify(dm_state(map_id))


@bp.post("/encounters/<int:enc_id>/map")
def api_encounter_map(enc_id):
    """The battle map for an encounter: the newest map linked to it, or a new
    map made for it. Either way, every combatant ends up with a token."""
    with tx() as conn:
        enc = conn.execute("SELECT id, campaign_id, name FROM encounters WHERE id = ?", (enc_id,)).fetchone()
        if enc is None:
            raise F.NotFound("Encounter not found")
        row = conn.execute("SELECT id FROM maps WHERE encounter_id = ? ORDER BY updated_at DESC LIMIT 1", (enc_id,)).fetchone()
        created = row is None
        if created:
            ts, cols, rows = now_iso(), 24, 16
            map_id = F.insert(conn, "maps", F.MAP, {"name": enc["name"], "cols": cols, "rows": rows, "encounter_id": enc_id},
                              {"uid": new_uid(), "campaign_id": enc["campaign_id"], "revealed": "0" * (cols * rows),
                               "created_at": ts, "updated_at": ts})
        else:
            map_id = row["id"]
        placed = place_encounter_tokens(conn, map_id)
    return jsonify({"map_id": map_id, "created": created, "placed": placed})


# ---- spell areas -----------------------------------------------------------------

def _shape(data, m, base=None):
    s = dict(base or {})
    if "kind" in data or base is None:
        kind = data.get("kind")
        if kind not in SHAPE_KINDS:
            raise F.ApiError("Area must be a circle, cone, line or square")
        s["kind"] = kind
    for key, lo, hi in (("x", -1, m["cols"] + 1), ("y", -1, m["rows"] + 1)):
        if key in data or base is None:
            try:
                v = float(data.get(key))
            except (TypeError, ValueError):
                raise F.ApiError(f"Area needs {key}")
            s[key] = round(max(lo, min(hi, v)), 2)
    if "size" in data or base is None:
        try:
            s["size"] = max(5, min(1000, int(data.get("size", 20))))
        except (TypeError, ValueError):
            raise F.ApiError("Size is in feet, like 20")
    if "width" in data or base is None:
        try:
            s["width"] = max(5, min(200, int(data.get("width") or 5)))
        except (TypeError, ValueError):
            raise F.ApiError("Width is in feet, like 5")
    if "dir" in data or base is None:
        try:
            s["dir"] = round(float(data.get("dir") or 0) % 360, 1)
        except (TypeError, ValueError):
            raise F.ApiError("Direction must be a number of degrees")
    if "color" in data or base is None:
        c = str(data.get("color") or "#e0714f")
        s["color"] = c if len(c) == 7 and c.startswith("#") else "#e0714f"
    if "label" in data or base is None:
        s["label"] = str(data.get("label") or "").strip()[:40]
    if "hidden" in data or base is None:
        s["hidden"] = bool(data.get("hidden"))
    return s


@bp.post("/maps/<int:map_id>/shapes")
def api_add_shape(map_id):
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        if len(m["shapes"]) >= 50:
            raise F.ApiError("That's a lot of areas — clear some first")
        s = _shape(data, m)
        s["id"] = uuid.uuid4().hex[:10]
        conn.execute("UPDATE maps SET shapes = ? WHERE id = ?", (json.dumps(m["shapes"] + [s]), map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id) | {"shape_id": s["id"]}), 201


@bp.patch("/maps/<int:map_id>/shapes/<shape_id>")
def api_patch_shape(map_id, shape_id):
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        shapes = m["shapes"]
        for i, s in enumerate(shapes):
            if s.get("id") == shape_id:
                shapes[i] = _shape(data, m, base=s)
                break
        else:
            raise F.NotFound("That area is gone")
        conn.execute("UPDATE maps SET shapes = ? WHERE id = ?", (json.dumps(shapes), map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.delete("/maps/<int:map_id>/shapes/<shape_id>")
def api_delete_shape(map_id, shape_id):
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        shapes = [s for s in m["shapes"] if s.get("id") != shape_id]
        conn.execute("UPDATE maps SET shapes = ? WHERE id = ?", (json.dumps(shapes), map_id))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.delete("/maps/<int:map_id>/shapes")
def api_clear_shapes(map_id):
    with tx() as conn:
        _map_row(conn, map_id)
        conn.execute("UPDATE maps SET shapes = '[]' WHERE id = ?", (map_id,))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/maps/<int:map_id>/ping")
def api_ping(map_id):
    data = request.get_json(silent=True) or {}
    m = map_dict(_map_row(get_db(), map_id))
    x, y = _ping_xy(data, m)
    add_ping(map_id, x, y, "DM", "#f3d58a")
    return jsonify({"pings": recent_pings(map_id)})


# ---- monsters straight onto the map ----------------------------------------------------

def _open_spots(m, taken, x, y, n):
    """The n nearest open squares to (x, y): not a wall, tree, water... and not already taken."""
    out, seen, ring = [], set(), 0
    x, y = int(x), int(y)
    while len(out) < n and ring <= max(m["cols"], m["rows"]):
        for dy in range(-ring, ring + 1):
            for dx in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                cx, cy = x + dx, y + dy
                if (cx, cy) in seen or not (0 <= cx < m["cols"] and 0 <= cy < m["rows"]):
                    continue
                seen.add((cx, cy))
                if m["terrain"].get(f"{cx},{cy}") not in BLOCKING and (cx, cy) not in taken:
                    out.append((cx, cy))
                    if len(out) == n:
                        return out
        ring += 1
    return out


@bp.post("/maps/<int:map_id>/monsters")
def api_add_monsters(map_id):
    """Add enemies from the creature library or the Monster Book to the map's
    encounter (making one if the map has none) and put their tokens around the
    square that was clicked."""
    from .combat import Ctx, _insert_enemy, _instance_names, _resort
    from .monster_book import BY_NAME
    data = request.get_json(silent=True) or {}
    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        raise F.ApiError("How many must be a number")
    if not 1 <= count <= 20:
        raise F.ApiError("Add between 1 and 20 at a time")
    with tx() as conn:
        m = map_dict(_map_row(conn, map_id))
        if data.get("creature_id"):
            cr = conn.execute("SELECT * FROM creatures WHERE id = ? AND (campaign_id IS NULL OR campaign_id = ?)",
                              (int(data["creature_id"]), m["campaign_id"])).fetchone()
            if cr is None:
                raise F.NotFound("That creature isn't in your library")
            block, base, creature_id = F.decode_row(cr, F.CREATURE), cr["name"], cr["id"]
        elif data.get("book") in BY_NAME:
            block, base, creature_id = F.validate_new(F.CREATURE, BY_NAME[data["book"]]), data["book"], None
        else:
            raise F.ApiError("Pick a monster")
        x, y = data.get("x", m["cols"] - 2), data.get("y", m["rows"] // 2)
        try:
            x, y = max(0, min(m["cols"] - 1, int(float(x)))), max(0, min(m["rows"] - 1, int(float(y))))
        except (TypeError, ValueError):
            raise F.ApiError("Where should they go?")
        created = False
        eid = m["encounter_id"]
        if not eid:
            ts = now_iso()
            eid = F.insert(conn, "encounters", F.ENCOUNTER, {"name": m["name"]},
                           {"uid": new_uid(), "campaign_id": m["campaign_id"], "created_at": ts, "updated_at": ts})
            conn.execute("INSERT INTO combat_log (encounter_id, round, kind, message, created_at) VALUES (?, 0, 'system', ?, ?)",
                         (eid, f"Encounter “{m['name']}” created from the battle map", ts))
            conn.execute("UPDATE maps SET encounter_id = ? WHERE id = ?", (eid, map_id))
            created = True
        ctx = Ctx(conn, eid)
        before = {c["id"] for c in ctx.combatants()}
        statblock = {k: block.get(k) for k in F.CREATURE if k != "name"}
        statblock["base_name"] = base
        names = _instance_names(ctx, base, count)
        hidden = bool(data.get("hidden"))
        for n in names:
            _insert_enemy(ctx, n, statblock, block["max_hp"], block["ac"], block["initiative_mod"], creature_id)
        if hidden:
            conn.execute(f"UPDATE combatants SET hidden = 1 WHERE encounter_id = ? AND name IN ({','.join('?' * len(names))})",
                         (eid, *names))
        ctx.log("roster", f"Added {', '.join(names)} from the battle map" + (" (hidden from players)" if hidden else ""))
        if ctx.settings["auto_sort"]:
            _resort(ctx)
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
        new = [c for c in ctx.combatants() if c["id"] not in before]
        link_party(conn, map_id)
        taken = {(int(round(r["x"])), int(round(r["y"]))) for r in conn.execute("SELECT x, y FROM map_tokens WHERE map_id = ?", (map_id,))}
        size = {"Large": 2, "Huge": 3, "Gargantuan": 4}.get(str(block.get("creature_type") or "").split(" ")[0], 1)
        spots = _open_spots(m, taken, x, y, len(new))
        ts = now_iso()
        for i, c in enumerate(new):
            sx, sy = spots[i] if i < len(spots) else (x, y)
            sx, sy = min(sx, m["cols"] - size), min(sy, m["rows"] - size)
            conn.execute("INSERT INTO map_tokens (uid, map_id, kind, combatant_id, x, y, size, hidden, created_at, updated_at) "
                         "VALUES (?,?,'enemy',?,?,?,?,0,?,?)", (new_uid(), map_id, c["id"], sx, sy, size, ts, ts))
            taken.add((sx, sy))
        _bump(conn, map_id)
    return jsonify(dm_state(map_id) | {"added": names, "encounter_created": created}), 201


@bp.post("/tokens/<int:token_id>/visibility")
def api_token_visibility(token_id):
    """Show or hide a token for players in one click. For an encounter
    combatant this hides the combatant itself, so it also leaves (or joins) the
    players' turn order."""
    data = request.get_json(silent=True) or {}
    hide = bool(data.get("hidden"))
    with tx() as conn:
        map_id = _token_map(conn, token_id)
        t = conn.execute("SELECT combatant_id FROM map_tokens WHERE id = ?", (token_id,)).fetchone()
        conn.execute("UPDATE map_tokens SET hidden = ?, updated_at = ? WHERE id = ?", (int(hide), now_iso(), token_id))
        if t["combatant_id"]:
            _set_combatant_hidden(conn, [t["combatant_id"]], hide)
        _bump(conn, map_id)
    return jsonify(dm_state(map_id))


@bp.post("/maps/<int:map_id>/reveal")
def api_reveal_all(map_id):
    """Show every hidden token on this map to players (the ambush springs)."""
    with tx() as conn:
        _map_row(conn, map_id)
        rows = conn.execute("SELECT t.id, t.combatant_id, cb.hidden AS cb_hidden FROM map_tokens t "
                            "LEFT JOIN combatants cb ON cb.id = t.combatant_id WHERE t.map_id = ? AND (t.hidden = 1 OR cb.hidden = 1) "
                            "AND t.kind NOT IN ('trap', 'marker')", (map_id,)).fetchall()
        conn.execute(f"UPDATE map_tokens SET hidden = 0 WHERE id IN ({','.join('?' * len(rows)) or 'NULL'})", [r["id"] for r in rows])
        _set_combatant_hidden(conn, [r["combatant_id"] for r in rows if r["combatant_id"] and r["cb_hidden"]], False)
        _bump(conn, map_id)
    return jsonify(dm_state(map_id) | {"revealed": len(rows)})


def _set_combatant_hidden(conn, combatant_ids, hide):
    from .combat import Ctx
    by_enc = {}
    for cid in combatant_ids:
        row = conn.execute("SELECT encounter_id, COALESCE(name, '') AS name, hidden FROM combatants WHERE id = ?", (cid,)).fetchone()
        if row and bool(row["hidden"]) != hide:
            by_enc.setdefault(row["encounter_id"], []).append((cid, row["name"]))
    for eid, items in by_enc.items():
        conn.execute(f"UPDATE combatants SET hidden = ? WHERE id IN ({','.join('?' * len(items))})", (int(hide), *[c for c, _ in items]))
        ctx = Ctx(conn, eid)
        names = [ctx.combatant(c)["name"] for c, _ in items]
        ctx.log("edit", ", ".join(names) + (" hidden from players" if hide else " revealed to players"))
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))


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
        t = conn.execute("SELECT * FROM map_tokens WHERE id = ?", (token_id,)).fetchone()
        x = F.coerce(F.TOKEN["x"], data.get("x"), "x")
        y = F.coerce(F.TOKEN["y"], data.get("y"), "y")
        x, y = clamp_position(m, t["size"], x, y)
        if not data.get("free"):  # in a fight: only on their turn and as far as their speed
            from .movement import check_dm_move
            check_dm_move(conn, m, t, x, y)
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
