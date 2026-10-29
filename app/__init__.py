import os
import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from . import db
from .fields import ApiError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(config=None):
    app = Flask(__name__)
    data_dir = os.environ.get("DND_TRACKER_DATA", os.path.join(BASE_DIR, "data"))
    app.config.update(
        DATA_DIR=data_dir,
        DATABASE=os.path.join(data_dir, "dnd_tracker.sqlite3"),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        AUTO_SNAPSHOT=True,
        BUILD=str(int(time.time() * 1000)),  # new every time the server starts: open pages reload onto the update
    )
    if config:
        app.config.update(config)
        if "DATA_DIR" in config and "DATABASE" not in config:
            app.config["DATABASE"] = os.path.join(config["DATA_DIR"], "dnd_tracker.sqlite3")
    data_dir = app.config["DATA_DIR"]
    app.config.setdefault("UPLOAD_DIR", os.path.join(data_dir, "uploads"))
    app.config.setdefault("BACKUP_DIR", os.path.join(data_dir, "backups"))
    app.config.setdefault("IMPORT_DIR", os.path.join(data_dir, "imports"))
    app.config.setdefault("CACHE_DIR", os.path.join(data_dir, "cache"))
    app.config.setdefault("LAN_MODE", False)
    for d in (data_dir, app.config["UPLOAD_DIR"], app.config["BACKUP_DIR"], app.config["IMPORT_DIR"], app.config["CACHE_DIR"]):
        os.makedirs(d, exist_ok=True)

    if app.config["AUTO_SNAPSHOT"]:
        db.daily_snapshot(app.config["DATABASE"], app.config["BACKUP_DIR"])
    db.migrate(app.config["DATABASE"], app.config["BACKUP_DIR"])
    db.prune_ops(app.config["DATABASE"])

    app.teardown_appcontext(db.close_db)

    from . import (auth, backup, campaigns, characters, combat, creatures, encounter_presets, journal, maps, morality,
                   online, pages, play, rest, rolls, spells, aura, handouts)
    for module in (auth, campaigns, characters, morality, combat, encounter_presets, creatures, journal, backup, rolls,
                   maps, play, rest, spells, aura, handouts, online, pages):
        app.register_blueprint(module.bp)
    # Every request passes the DM/player permission check first.
    app.before_request(auth.guard)

    @app.errorhandler(ApiError)
    def _api_error(err):
        body = {"error": err.message}
        body.update(err.extra)
        return jsonify(body), err.status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if request.path.startswith("/api/"):
            return jsonify({"error": err.description or err.name}), err.code
        return err

    @app.errorhandler(Exception)
    def _unexpected(err):
        app.logger.exception("Unhandled error")
        if request.path.startswith("/api/"):
            return jsonify({"error": "Server error — nothing was saved for this request."}), 500
        return "Something went wrong. Check the server window for details.", 500

    @app.after_request
    def _no_cache_api(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
            # anything changed: every open page hears about it at once (app/events.py)
            if request.method in ("POST", "PATCH", "PUT", "DELETE") and resp.status_code < 400:
                from . import events
                events.publish()
        return resp

    return app
