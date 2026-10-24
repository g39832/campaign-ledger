"""Players joining from their own devices, and everything they can see.

Every response in this module is built for a player: no DM notes, no hidden
combatants or tokens, nothing under fog of war, no other campaign's data.
"""
import json
import secrets
import socket
import time

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from . import fields as F
from .auth import PLAYER_COOKIE, current_identity, is_dm, token_hash
from .db import get_db, now_iso, tx
from .maps import _bump, clamp_position, map_dict, player_view, fog_image
from .rules import derived

bp = Blueprint("play", __name__)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _failures(key, window=60):
    store = current_app.extensions.setdefault("join_failures", {})
    now = time.time()
    store[key] = [t for t in store.get(key, []) if now - t < window]
    return store[key]


def _limited(key, limit=10):
    """Too many wrong codes from one address in a minute: slow down guessing."""
    return len(_failures(key)) >= limit


def _record_failure(key):
    _failures(key).append(time.time())


def _campaign_by_code(code):
    code = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    if len(code) < 4:
        return None
    return get_db().execute("SELECT * FROM campaigns WHERE join_code = ? AND archived = 0", (code,)).fetchone()


def _player_required():
    ident = current_identity()
    if not ident or ident["role"] != "player":
        raise F.ApiError("Join the game first", status=401)
    return ident


# ---- joining ------------------------------------------------------------------

@bp.get("/join")
def join_page():
    ident = current_identity()
    return render_template("join.html", ident=ident, prefill=request.args.get("code", ""))


@bp.get("/api/join/lookup")
def api_lookup():
    if _limited(request.remote_addr):
        raise F.ApiError("Too many tries. Wait a minute and try again.", status=429)
    camp = _campaign_by_code(request.args.get("code"))
    if camp is None:
        _record_failure(request.remote_addr)
        raise F.NotFound("No game with that code. Check it with your DM.")
    conn = get_db()
    claimed = {r["character_id"] for r in conn.execute(
        "SELECT character_id FROM players WHERE campaign_id = ? AND revoked = 0 AND character_id IS NOT NULL", (camp["id"],))}
    chars = conn.execute("SELECT id, name, class_name, level FROM characters WHERE campaign_id = ? AND archived = 0 "
                         "AND kind = 'pc' ORDER BY name COLLATE NOCASE", (camp["id"],)).fetchall()
    return jsonify({"campaign": camp["name"],
                    "characters": [dict(c) | {"claimed": c["id"] in claimed} for c in chars]})


@bp.post("/api/join")
def api_join():
    if _limited(request.remote_addr):
        raise F.ApiError("Too many tries. Wait a minute and try again.", status=429)
    data = request.get_json(silent=True) or {}
    camp = _campaign_by_code(data.get("code"))
    if camp is None:
        _record_failure(request.remote_addr)
        raise F.NotFound("No game with that code. Check it with your DM.")
    name = str(data.get("name", "")).strip()[:40]
    if not name:
        raise F.ApiError("Enter your name")
    char_id = data.get("character_id")
    conn = get_db()
    if char_id:
        ch = conn.execute("SELECT id FROM characters WHERE id = ? AND campaign_id = ? AND kind = 'pc' AND archived = 0",
                          (char_id, camp["id"])).fetchone()
        if ch is None:
            raise F.ApiError("That character isn't in this game")
        if conn.execute("SELECT 1 FROM players WHERE character_id = ? AND revoked = 0", (char_id,)).fetchone():
            raise F.ApiError("Someone has already joined as that character. Ask your DM to free it up.")
    raw = secrets.token_urlsafe(32)
    ts = now_iso()
    with tx() as conn:
        conn.execute("INSERT INTO players (campaign_id, name, character_id, token_hash, created_at, last_seen) "
                     "VALUES (?,?,?,?,?,?)", (camp["id"], name, char_id or None, token_hash(raw), ts, ts))
    resp = jsonify({"joined": camp["name"]})
    resp.set_cookie(PLAYER_COOKIE, raw, max_age=60 * 60 * 24 * 180, httponly=True, samesite="Lax")
    return resp


@bp.post("/api/play/leave")
def api_leave():
    ident = current_identity()
    if ident and ident["role"] == "player":
        with tx() as conn:
            conn.execute("UPDATE players SET revoked = 1 WHERE id = ?", (ident["id"],))
    resp = jsonify({"left": True})
    resp.delete_cookie(PLAYER_COOKIE)
    return resp


# ---- the player's screen --------------------------------------------------------------

@bp.get("/play")
def play_page():
    ident = current_identity()
    if not ident or ident["role"] != "player":
        from flask import redirect
        return redirect("/join")
    camp = get_db().execute("SELECT name FROM campaigns WHERE id = ?", (ident["campaign_id"],)).fetchone()
    return render_template("play.html", ident=ident, campaign_name=camp["name"])


def _own_character(conn, char_id):
    if not char_id:
        return None
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    if row is None:
        return None
    c = F.decode_row(row, F.CHARACTER)
    d = derived(c)
    keep = ("id", "name", "class_name", "subclass", "level", "race", "current_hp", "max_hp", "temp_hp", "ac", "speed",
            "status", "death_successes", "death_failures", "exhaustion", "portrait", "abilities", "save_profs",
            "skill_profs", "spell_slots", "spellcasting_ability", "inspiration", "hit_dice", "hit_dice_used")
    out = {k: c[k] for k in keep}
    out["conditions"] = [x["name"] for x in c["conditions"]]
    out["attacks"] = [{"index": i, "name": a.get("name", ""), "bonus": a.get("bonus", ""), "damage": a.get("damage", "")}
                      for i, a in enumerate(c["attacks"] or [])]
    out["derived"] = d
    from .campaigns import get_campaign
    from .rules import parse_hit_dice
    out["can"] = get_campaign(c["campaign_id"])["settings"]["players"]
    out["hit_dice_total"] = sum(n for n, _ in parse_hit_dice(c["hit_dice"]))
    out["hit_dice_sizes"] = sorted({s for _, s in parse_hit_dice(c["hit_dice"])}, reverse=True)
    return out


def _player_encounter(conn, campaign_id, live_map):
    enc = None
    if live_map and live_map["encounter_id"]:
        enc = conn.execute("SELECT * FROM encounters WHERE id = ? AND status = 'active'", (live_map["encounter_id"],)).fetchone()
    if enc is None:
        enc = conn.execute("SELECT * FROM encounters WHERE campaign_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                           (campaign_id,)).fetchone()
    if enc is None:
        return None
    rows = conn.execute(
        """SELECT c.id, c.kind, c.hidden, c.character_id, COALESCE(ch.name, c.name) AS name,
                  COALESCE(ch.current_hp, c.current_hp) AS hp, COALESCE(ch.max_hp, c.max_hp) AS max_hp,
                  COALESCE(ch.status, c.status) AS status, c.init_roll
           FROM combatants c LEFT JOIN characters ch ON ch.id = c.character_id
           WHERE c.encounter_id = ? ORDER BY c.sort_order, c.id""", (enc["id"],)).fetchall()
    order, current_name = [], None
    for r in rows:
        if r["hidden"]:
            continue
        item = {"id": r["id"], "name": r["name"], "kind": r["kind"], "is_current": r["id"] == enc["current_id"],
                "init": r["init_roll"],
                "status": r["status"] if r["status"] in ("dead", "defeated", "unconscious", "fled", "stable") else None}
        if r["character_id"]:
            item.update(hp=r["hp"], max_hp=r["max_hp"])
        elif r["max_hp"]:
            item["health"] = "down" if r["hp"] <= 0 else ("bloodied" if r["hp"] * 2 <= r["max_hp"] else "")
        if item["is_current"]:
            current_name = r["name"]
        order.append(item)
    return {"id": enc["id"], "name": enc["name"], "round": enc["round"], "current": current_name, "order": order}


@bp.get("/api/play/state")
def api_state():
    ident = _player_required()
    conn = get_db()
    camp = conn.execute("SELECT id, name, live_map_id FROM campaigns WHERE id = ?", (ident["campaign_id"],)).fetchone()
    live = conn.execute("SELECT * FROM maps WHERE id = ? AND campaign_id = ?", (camp["live_map_id"], camp["id"])).fetchone() \
        if camp["live_map_id"] else None
    party = [dict(r) | {"conditions": [c["name"] for c in json.loads(r["conditions"])]} for r in conn.execute(
        "SELECT id, name, class_name, level, current_hp, max_hp, temp_hp, ac, status, conditions, portrait FROM characters "
        "WHERE campaign_id = ? AND archived = 0 AND kind = 'pc' ORDER BY name COLLATE NOCASE", (camp["id"],))]
    return jsonify({
        "me": {"name": ident["name"], "character_id": ident["character_id"]},
        "campaign": camp["name"],
        "character": _own_character(conn, ident["character_id"]),
        "party": party,
        "encounter": _player_encounter(conn, camp["id"], live),
        "map": player_view(conn, live["id"], ident) if live else None,
    })


@bp.post("/api/play/tokens/<int:token_id>/move")
def api_move(token_id):
    ident = _player_required()
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        t = conn.execute(
            "SELECT t.*, cb.character_id AS cb_char FROM map_tokens t LEFT JOIN combatants cb ON cb.id = t.combatant_id "
            "WHERE t.id = ?", (token_id,)).fetchone()
        if t is None:
            raise F.NotFound("Token not found")
        m = conn.execute("SELECT * FROM maps WHERE id = ?", (t["map_id"],)).fetchone()
        camp = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (ident["campaign_id"],)).fetchone()
        owner = t["character_id"] or t["cb_char"]
        if (m["campaign_id"] != ident["campaign_id"] or camp["live_map_id"] != m["id"] or not owner
                or owner != ident["character_id"] or t["hidden"]):
            raise F.ApiError("You can only move your own character's token", status=403)
        if not m["players_can_move"]:
            raise F.ApiError("The DM has locked token movement", status=403)
        md = map_dict(m)
        x = F.coerce(F.TOKEN["x"], data.get("x"), "x")
        y = F.coerce(F.TOKEN["y"], data.get("y"), "y")
        x, y = clamp_position(md, t["size"], x, y)
        conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (x, y, now_iso(), token_id))
        _bump(conn, m["id"])
    return jsonify({"ok": True, "x": x, "y": y})


@bp.get("/api/play/map-image/<int:map_id>")
def api_map_image(map_id):
    ident = current_identity()
    conn = get_db()
    m = conn.execute("SELECT * FROM maps WHERE id = ?", (map_id,)).fetchone()
    if m is None or not m["image"]:
        raise F.NotFound("Not found")
    if not is_dm():
        camp = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (ident["campaign_id"],)).fetchone()
        if camp["live_map_id"] != map_id:
            raise F.NotFound("Not found")
    path = fog_image(map_dict(m), current_app.config["UPLOAD_DIR"], current_app.config["CACHE_DIR"])
    resp = send_file(path, max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---- players updating their own character ---------------------------------------------

def _own(action):
    """The player's character id, if the DM allows this action."""
    from .campaigns import get_campaign
    ident = _player_required()
    if not ident["character_id"]:
        raise F.ApiError("Ask the DM to give you a character first", status=403)
    rules = get_campaign(ident["campaign_id"])["settings"]["players"]
    if action and not rules.get(action):
        raise F.ApiError("The DM has turned this off for players", status=403)
    return ident, ident["character_id"]


@bp.post("/api/play/me/hp")
def api_me_hp():
    from .rest import change_character_hp
    ident, char_id = _own("edit_hp")
    data = request.get_json(silent=True) or {}
    if data.get("op") not in ("damage", "heal", "temp", "set"):
        raise F.ApiError("op must be damage, heal, temp or set")
    body = {k: data[k] for k in ("op", "amount", "hp", "max_hp", "temp_hp") if k in data}
    if body["op"] == "set":
        body.pop("max_hp", None)  # max HP is the DM's call
    with tx() as conn:
        change_character_hp(conn, char_id, body, by=ident["name"])
    return jsonify({"character": _own_character(get_db(), char_id)})


@bp.post("/api/play/me/slot")
def api_me_slot():
    ident, char_id = _own("spend_slots")
    data = request.get_json(silent=True) or {}
    level = str(data.get("level"))
    with tx() as conn:
        row = conn.execute("SELECT spell_slots FROM characters WHERE id = ?", (char_id,)).fetchone()
        slots = json.loads(row["spell_slots"] or "{}")
        slot = slots.get(level)
        if not slot or not slot.get("max"):
            raise F.ApiError("No spell slots of that level")
        try:
            used = int(data.get("used"))
        except (TypeError, ValueError):
            raise F.ApiError("used must be a number")
        slot["used"] = max(0, min(slot["max"], used))
        conn.execute("UPDATE characters SET spell_slots = ?, updated_at = ? WHERE id = ?", (json.dumps(slots), now_iso(), char_id))
    return jsonify({"character": _own_character(get_db(), char_id)})


@bp.post("/api/play/me/death")
def api_me_death():
    ident, char_id = _own("edit_hp")
    data = request.get_json(silent=True) or {}
    field = data.get("field")
    if field not in ("death_successes", "death_failures"):
        raise F.ApiError("field must be death_successes or death_failures")
    try:
        value = max(0, min(3, int(data.get("value"))))
    except (TypeError, ValueError):
        raise F.ApiError("value must be 0-3")
    with tx() as conn:
        conn.execute(f"UPDATE characters SET {field} = ?, updated_at = ? WHERE id = ?", (value, now_iso(), char_id))
        from .characters import _touch_encounters
        _touch_encounters(conn, char_id)
    return jsonify({"character": _own_character(get_db(), char_id)})


@bp.post("/api/play/me/hit-die")
def api_me_hit_die():
    from .rest import spend_hit_die
    from .rolls import roll_dict
    ident, char_id = _own("hit_dice")
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        roll_id = spend_hit_die(conn, ident, char_id, data.get("sides"), data.get("op_id"))
    row = get_db().execute("SELECT * FROM rolls WHERE id = ?", (roll_id,)).fetchone()
    return jsonify({"roll": roll_dict(row, ident), "character": _own_character(get_db(), char_id)})


# ---- DM: managing who's at the table ---------------------------------------------------

def _dm_required():
    if not is_dm():
        raise F.ApiError("Only the DM can do that.", status=403)


@bp.get("/api/campaigns/<int:cid>/players")
def api_players(cid):
    _dm_required()
    conn = get_db()
    camp = conn.execute("SELECT join_code, live_map_id FROM campaigns WHERE id = ?", (cid,)).fetchone()
    if camp is None:
        raise F.NotFound("Campaign not found")
    rows = conn.execute(
        "SELECT p.id, p.name, p.character_id, p.created_at, p.last_seen, ch.name AS character_name FROM players p "
        "LEFT JOIN characters ch ON ch.id = p.character_id WHERE p.campaign_id = ? AND p.revoked = 0 ORDER BY p.created_at",
        (cid,)).fetchall()
    return jsonify({"join_code": camp["join_code"], "live_map_id": camp["live_map_id"],
                    "players": [dict(r) for r in rows], "addresses": lan_addresses(),
                    "port": request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"})


@bp.post("/api/campaigns/<int:cid>/join-code")
def api_join_code(cid):
    _dm_required()
    action = (request.get_json(silent=True) or {}).get("action", "new")
    code = None
    with tx() as conn:
        if action == "new":
            while True:
                code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
                if not conn.execute("SELECT 1 FROM campaigns WHERE join_code = ?", (code,)).fetchone():
                    break
        conn.execute("UPDATE campaigns SET join_code = ? WHERE id = ?", (code, cid))
    return jsonify({"join_code": code})


@bp.patch("/api/players/<int:pid>")
def api_player_patch(pid):
    _dm_required()
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        p = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
        if p is None:
            raise F.NotFound("Player not found")
        char_id = data.get("character_id")
        if char_id:
            ok = conn.execute("SELECT 1 FROM characters WHERE id = ? AND campaign_id = ?", (char_id, p["campaign_id"])).fetchone()
            if not ok:
                raise F.ApiError("That character isn't in this campaign")
            conn.execute("UPDATE players SET character_id = NULL WHERE character_id = ? AND id != ?", (char_id, pid))
        conn.execute("UPDATE players SET character_id = ? WHERE id = ?", (char_id or None, pid))
    return jsonify({"ok": True})


@bp.delete("/api/players/<int:pid>")
def api_player_kick(pid):
    _dm_required()
    with tx() as conn:
        conn.execute("UPDATE players SET revoked = 1 WHERE id = ?", (pid,))
    return jsonify({"ok": True})


def lan_addresses():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)
