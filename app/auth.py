"""Who is making this request: the DM, a player who joined, or nobody.

* The DM is anyone using the app on this computer (a direct request to
  127.0.0.1/localhost, not relayed through a proxy or tunnel), or a device that
  opened a DM link generated on the Table page.
* Players join a campaign with its join code and get a random token in a
  cookie. Only a hash of the token is stored.
* Everything that isn't explicitly player-facing requires the DM. This is
  checked on the server for every request, not by hiding buttons.
"""
import hashlib
import secrets
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, jsonify, redirect, request

from .db import get_db, get_setting, now_iso, set_setting, tx

bp = Blueprint("auth", __name__)

PLAYER_COOKIE = "cl_player"
DM_COOKIE = "cl_dm"
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP")

# Paths a joined player may use. Each of these endpoints does its own
# per-player checks (own campaign, own character, visibility).
PLAYER_PREFIXES = ("/play", "/api/play/", "/api/rolls", "/api/uploads/", "/join", "/api/join")
PUBLIC_PREFIXES = ("/static/", "/join", "/api/join", "/dm-login")


def token_hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_local_request():
    if not current_app.config.get("TRUST_LOCALHOST", True):
        return False
    if request.remote_addr not in LOOPBACK:
        return False
    if any(h in request.headers for h in PROXY_HEADERS):
        return False  # relayed by a tunnel/proxy: the real client is elsewhere
    host = (request.host or "").lower()
    hostname = host[:host.index("]") + 1] if host.startswith("[") and "]" in host else host.split(":")[0]
    return hostname in LOCAL_HOSTS


def current_identity():
    if "identity" in g:
        return g.identity
    ident = None
    if is_local_request():
        ident = {"role": "dm", "name": "DM"}
    else:
        raw = request.cookies.get(DM_COOKIE)
        stored = get_setting("dm_key_hash")
        if raw and stored and secrets.compare_digest(token_hash(raw), stored):
            ident = {"role": "dm", "name": "DM"}
    if ident is None:
        raw = request.cookies.get(PLAYER_COOKIE)
        if raw:
            row = get_db().execute(
                "SELECT p.*, c.archived AS campaign_archived FROM players p JOIN campaigns c ON c.id = p.campaign_id "
                "WHERE p.token_hash = ? AND p.revoked = 0", (token_hash(raw),)).fetchone()
            if row and not row["campaign_archived"]:
                ident = {"role": "player", "id": row["id"], "name": row["name"],
                         "campaign_id": row["campaign_id"], "character_id": row["character_id"]}
    g.identity = ident
    return ident


def is_dm():
    ident = current_identity()
    return bool(ident and ident["role"] == "dm")


def cross_site():
    """Reject state-changing requests that come from another website open in
    the same browser (cross-site request forgery)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return True
    origin = request.headers.get("Origin")
    if origin and origin != "null":
        return urlparse(origin).netloc.lower() != (request.host or "").lower()
    return origin == "null"


def guard():
    path = request.path
    if cross_site():
        return jsonify({"error": "Blocked a request from another website."}), 403
    if path.startswith("/static/") or path == "/dm-login":
        # The DM-link page checks its own key, and must work on a device that
        # already joined as a player (otherwise it would bounce to /play).
        return None
    ident = current_identity()
    if ident and ident["role"] == "dm":
        return None
    if ident and ident["role"] == "player":
        if path.startswith(PLAYER_PREFIXES):
            _touch_player(ident["id"])
            return None
        if path.startswith("/api/"):
            return jsonify({"error": "Only the DM can do that."}), 403
        return redirect("/play")
    if path.startswith(PUBLIC_PREFIXES):
        return None
    if path.startswith("/api/"):
        return jsonify({"error": "Join the game first."}), 401
    return redirect("/join")


def _touch_player(pid):
    # At most one write a minute per player, to show "last seen" on the Table page.
    now = now_iso()
    conn = get_db()
    row = conn.execute("SELECT last_seen FROM players WHERE id = ?", (pid,)).fetchone()
    if row and row["last_seen"][:16] != now[:16]:
        with tx() as c:
            c.execute("UPDATE players SET last_seen = ? WHERE id = ?", (now, pid))


@bp.post("/api/dm-key")
def api_dm_key():
    if not is_dm():
        return jsonify({"error": "Only the DM can do that."}), 403
    raw = secrets.token_urlsafe(24)
    with tx() as conn:
        set_setting(conn, "dm_key_hash", token_hash(raw))
    return jsonify({"key": raw})


@bp.delete("/api/dm-key")
def api_dm_key_revoke():
    if not is_dm():
        return jsonify({"error": "Only the DM can do that."}), 403
    with tx() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = 'dm_key_hash'")
    return jsonify({"revoked": True})


@bp.get("/dm-login")
def dm_login():
    raw = request.args.get("key", "")
    stored = get_setting("dm_key_hash")
    if not raw or not stored or not secrets.compare_digest(token_hash(raw), stored):
        return ("That DM link is invalid or has been replaced by a newer one. "
                "On the DM's computer, open Players and click Make DM link, then use the newest link."), 403
    resp = redirect("/")
    resp.set_cookie(DM_COOKIE, raw, max_age=60 * 60 * 24 * 365, httponly=True, samesite="Lax")
    return resp
