"""SQLite storage: connection handling, schema migrations, transactions, snapshots.

The database file is the single source of truth. Every write runs inside an
explicit transaction (BEGIN IMMEDIATE) so related rows change together or not
at all, and the connection uses WAL + synchronous=FULL so a committed write
survives a crash or power loss.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA_VERSION = 10

MIGRATIONS = {
    1: """
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE campaigns (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        archived INTEGER NOT NULL DEFAULT 0,
        archived_at TEXT,
        settings TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE characters (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        kind TEXT NOT NULL DEFAULT 'pc',
        archived INTEGER NOT NULL DEFAULT 0,
        name TEXT NOT NULL DEFAULT '',
        player_name TEXT NOT NULL DEFAULT '',
        race TEXT NOT NULL DEFAULT '',
        class_name TEXT NOT NULL DEFAULT '',
        subclass TEXT NOT NULL DEFAULT '',
        level INTEGER NOT NULL DEFAULT 1,
        background TEXT NOT NULL DEFAULT '',
        alignment TEXT NOT NULL DEFAULT '',
        xp INTEGER NOT NULL DEFAULT 0,
        portrait TEXT,
        max_hp INTEGER NOT NULL DEFAULT 0,
        current_hp INTEGER NOT NULL DEFAULT 0,
        temp_hp INTEGER NOT NULL DEFAULT 0,
        ac INTEGER NOT NULL DEFAULT 10,
        initiative_bonus INTEGER NOT NULL DEFAULT 0,
        initiative_override INTEGER,
        initiative_roll INTEGER,
        speed TEXT NOT NULL DEFAULT '30 ft.',
        prof_override INTEGER,
        hit_dice TEXT NOT NULL DEFAULT '',
        hit_dice_used INTEGER NOT NULL DEFAULT 0,
        death_successes INTEGER NOT NULL DEFAULT 0,
        death_failures INTEGER NOT NULL DEFAULT 0,
        exhaustion INTEGER NOT NULL DEFAULT 0,
        inspiration INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ok',
        conditions TEXT NOT NULL DEFAULT '[]',
        abilities TEXT NOT NULL DEFAULT '{}',
        save_profs TEXT NOT NULL DEFAULT '[]',
        save_bonus TEXT NOT NULL DEFAULT '{}',
        skill_profs TEXT NOT NULL DEFAULT '{}',
        skill_bonus TEXT NOT NULL DEFAULT '{}',
        attacks TEXT NOT NULL DEFAULT '[]',
        spellcasting_ability TEXT NOT NULL DEFAULT '',
        spell_slots TEXT NOT NULL DEFAULT '{}',
        spells TEXT NOT NULL DEFAULT '[]',
        features TEXT NOT NULL DEFAULT '',
        proficiencies TEXT NOT NULL DEFAULT '',
        equipment TEXT NOT NULL DEFAULT '[]',
        currency TEXT NOT NULL DEFAULT '{}',
        appearance TEXT NOT NULL DEFAULT '',
        personality TEXT NOT NULL DEFAULT '',
        ideals TEXT NOT NULL DEFAULT '',
        bonds TEXT NOT NULL DEFAULT '',
        flaws TEXT NOT NULL DEFAULT '',
        backstory TEXT NOT NULL DEFAULT '',
        goals TEXT NOT NULL DEFAULT '',
        relationships TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        law_start INTEGER NOT NULL DEFAULT 0,
        good_start INTEGER NOT NULL DEFAULT 0,
        auto_alignment INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_characters_campaign ON characters(campaign_id);

    CREATE TABLE morality_events (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        session_label TEXT NOT NULL DEFAULT '',
        occurred_on TEXT NOT NULL DEFAULT '',
        law_delta INTEGER NOT NULL DEFAULT 0,
        good_delta INTEGER NOT NULL DEFAULT 0,
        dm_notes TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        reverses_id INTEGER REFERENCES morality_events(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_morality_character ON morality_events(character_id, seq);

    CREATE TABLE creatures (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER REFERENCES campaigns(id),
        name TEXT NOT NULL,
        creature_type TEXT NOT NULL DEFAULT '',
        cr TEXT NOT NULL DEFAULT '',
        max_hp INTEGER NOT NULL DEFAULT 1,
        ac INTEGER NOT NULL DEFAULT 10,
        initiative_mod INTEGER NOT NULL DEFAULT 0,
        speed TEXT NOT NULL DEFAULT '30 ft.',
        abilities TEXT NOT NULL DEFAULT '{}',
        attacks TEXT NOT NULL DEFAULT '',
        traits TEXT NOT NULL DEFAULT '',
        resistances TEXT NOT NULL DEFAULT '',
        immunities TEXT NOT NULL DEFAULT '',
        vulnerabilities TEXT NOT NULL DEFAULT '',
        condition_immunities TEXT NOT NULL DEFAULT '',
        senses TEXT NOT NULL DEFAULT '',
        languages TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE encounters (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planning',
        round INTEGER NOT NULL DEFAULT 0,
        current_id INTEGER,
        location TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        rev INTEGER NOT NULL DEFAULT 0,
        started_at TEXT,
        ended_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_encounters_campaign ON encounters(campaign_id);

    CREATE TABLE combatants (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        encounter_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
        creature_id INTEGER REFERENCES creatures(id) ON DELETE SET NULL,
        kind TEXT NOT NULL DEFAULT 'enemy',
        name TEXT NOT NULL,
        init_roll INTEGER,
        init_mod INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        max_hp INTEGER NOT NULL DEFAULT 0,
        current_hp INTEGER NOT NULL DEFAULT 0,
        temp_hp INTEGER NOT NULL DEFAULT 0,
        ac INTEGER NOT NULL DEFAULT 10,
        status TEXT NOT NULL DEFAULT 'ok',
        conditions TEXT NOT NULL DEFAULT '[]',
        statblock TEXT NOT NULL DEFAULT '{}',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_combatants_encounter ON combatants(encounter_id);

    CREATE TABLE hp_changes (
        id INTEGER PRIMARY KEY,
        encounter_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        combatant_id INTEGER REFERENCES combatants(id) ON DELETE SET NULL,
        character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
        label TEXT NOT NULL,
        before TEXT NOT NULL,
        after TEXT NOT NULL,
        undone INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_hp_changes_encounter ON hp_changes(encounter_id, id);

    CREATE TABLE combat_log (
        id INTEGER PRIMARY KEY,
        encounter_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        round INTEGER NOT NULL DEFAULT 0,
        turn_name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_combat_log_encounter ON combat_log(encounter_id, id);

    CREATE TABLE journal_entries (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        kind TEXT NOT NULL DEFAULT 'note',
        title TEXT NOT NULL DEFAULT '',
        session_number INTEGER,
        session_date TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        pinned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_journal_campaign ON journal_entries(campaign_id, kind);

    CREATE TABLE journal_links (
        entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        PRIMARY KEY (entry_id, target_type, target_id)
    );

    CREATE TABLE ops (
        op_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    );
    """,
    # v2: dice rolls, players who join from other devices, battle maps.
    # Purely additive: new tables and new nullable/defaulted columns.
    2: """
    ALTER TABLE campaigns ADD COLUMN join_code TEXT;
    ALTER TABLE campaigns ADD COLUMN live_map_id INTEGER;
    ALTER TABLE combatants ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;

    CREATE TABLE players (
        id INTEGER PRIMARY KEY,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
        token_hash TEXT NOT NULL UNIQUE,
        revoked INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
    CREATE INDEX idx_players_campaign ON players(campaign_id);

    CREATE TABLE rolls (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        op_id TEXT UNIQUE,
        campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
        roller_kind TEXT NOT NULL DEFAULT 'dm',
        player_id INTEGER REFERENCES players(id) ON DELETE SET NULL,
        roller_name TEXT NOT NULL DEFAULT 'DM',
        character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
        combatant_id INTEGER REFERENCES combatants(id) ON DELETE SET NULL,
        encounter_id INTEGER REFERENCES encounters(id) ON DELETE SET NULL,
        subject TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'custom',
        expression TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'normal',
        visibility TEXT NOT NULL DEFAULT 'public',
        result TEXT NOT NULL,
        total INTEGER NOT NULL,
        outcome TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_rolls_campaign ON rolls(campaign_id, id);

    CREATE TABLE maps (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        encounter_id INTEGER REFERENCES encounters(id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        image TEXT,
        image_w INTEGER NOT NULL DEFAULT 0,
        image_h INTEGER NOT NULL DEFAULT 0,
        cols INTEGER NOT NULL DEFAULT 24,
        rows INTEGER NOT NULL DEFAULT 16,
        cell_px INTEGER NOT NULL DEFAULT 50,
        offset_x INTEGER NOT NULL DEFAULT 0,
        offset_y INTEGER NOT NULL DEFAULT 0,
        scale_value INTEGER NOT NULL DEFAULT 5,
        scale_unit TEXT NOT NULL DEFAULT 'ft',
        show_grid INTEGER NOT NULL DEFAULT 1,
        grid_color TEXT NOT NULL DEFAULT '#000000',
        grid_opacity INTEGER NOT NULL DEFAULT 35,
        snap INTEGER NOT NULL DEFAULT 1,
        bg_color TEXT NOT NULL DEFAULT '#d9ccae',
        terrain TEXT NOT NULL DEFAULT '{}',
        fog_enabled INTEGER NOT NULL DEFAULT 0,
        revealed TEXT NOT NULL DEFAULT '',
        players_can_move INTEGER NOT NULL DEFAULT 1,
        notes TEXT NOT NULL DEFAULT '',
        rev INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_maps_campaign ON maps(campaign_id);

    CREATE TABLE map_tokens (
        id INTEGER PRIMARY KEY,
        uid TEXT NOT NULL UNIQUE,
        map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'marker',
        label TEXT NOT NULL DEFAULT '',
        character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
        combatant_id INTEGER REFERENCES combatants(id) ON DELETE SET NULL,
        x REAL NOT NULL DEFAULT 0,
        y REAL NOT NULL DEFAULT 0,
        size INTEGER NOT NULL DEFAULT 1,
        color TEXT NOT NULL DEFAULT '',
        hidden INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_tokens_map ON map_tokens(map_id);
    """,
    # v3: Saints & Sinners morality score per character (-100..+100, starts at 0).
    # Additive only: existing rows get the starting score of 0.
    3: """
    ALTER TABLE characters ADD COLUMN morality_score INTEGER NOT NULL DEFAULT 0;
    """,
    # v4: Saints & Sinners is one score for the whole party, kept on the campaign.
    # Additive only (the per-character column from v3 is left as it was).
    4: """
    ALTER TABLE campaigns ADD COLUMN morality_score INTEGER NOT NULL DEFAULT 0;
    """,
    # v5: spell areas (circles, cones, lines, squares) drawn on a battle map.
    5: """
    ALTER TABLE maps ADD COLUMN shapes TEXT NOT NULL DEFAULT '[]';
    """,
    # v6: monsters can have spells (one per line, like their attacks).
    6: """
    ALTER TABLE creatures ADD COLUMN spells TEXT NOT NULL DEFAULT '';
    """,
    # v7: how far each hero has moved this turn (players move only as far as their speed).
    7: """
    ALTER TABLE combatants ADD COLUMN moved TEXT NOT NULL DEFAULT '';
    """,
    # v8: skills typed in by hand ({"perception": 7}) instead of worked out from the abilities.
    8: """
    ALTER TABLE characters ADD COLUMN skill_set TEXT NOT NULL DEFAULT '{}';
    """,
    9: """
    ALTER TABLE characters ADD COLUMN dice_style TEXT NOT NULL DEFAULT '{}';
    """,
    10: """
    ALTER TABLE creatures ADD COLUMN boss INTEGER NOT NULL DEFAULT 0;
    """,
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_uid():
    return uuid.uuid4().hex


def _connect(path):
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def tx():
    """Write transaction. Takes the write lock up front so a read-modify-write
    sequence inside cannot interleave with another request's writes."""
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def migrate(path, backup_dir=None):
    conn = _connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{version} is newer than this app (v{SCHEMA_VERSION}). "
                "Update the app before opening this database."
            )
        if 0 < version < SCHEMA_VERSION and backup_dir:
            # Existing data is about to be upgraded: keep a verified copy first.
            snap = snapshot(path, backup_dir, f"pre-migration-v{version}-to-v{SCHEMA_VERSION}")
            check = sqlite3.connect(snap)
            try:
                ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                same = check.execute("PRAGMA user_version").fetchone()[0] == version
            finally:
                check.close()
            if not (ok and same):
                raise RuntimeError(f"Pre-migration backup {snap} failed verification; database left untouched.")
        for v in range(version + 1, SCHEMA_VERSION + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _split_sql(MIGRATIONS[v]):
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {v}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()


def _split_sql(script):
    return [s.strip() for s in script.split(";") if s.strip()]


def snapshot(path, dest_dir, label):
    """Consistent copy of the live database using SQLite's online backup API."""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(dest_dir, f"{label}-{stamp}.sqlite3")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(dest_dir, f"{label}-{stamp}-{n}.sqlite3")
    src = _connect(path)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dest


def daily_snapshot(path, dest_dir, keep=14):
    """Take at most one automatic snapshot per day and prune old ones."""
    if not os.path.exists(path):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    existing = sorted(f for f in os.listdir(dest_dir) if f.startswith("daily-"))
    made = None
    if not any(f.startswith(f"daily-{today}") for f in existing):
        made = snapshot(path, dest_dir, "daily")
        existing = sorted(f for f in os.listdir(dest_dir) if f.startswith("daily-"))
    for old in existing[:-keep]:
        try:
            os.remove(os.path.join(dest_dir, old))
        except OSError:
            pass
    return made


# ---- small helpers shared by the API modules -------------------------------

def row_to_dict(row, json_fields=()):
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            d[f] = json.loads(d[f])
    return d


def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def claim_op(conn, op_id):
    """Record a client operation id. Returns False if it was already applied,
    which makes retried requests (e.g. after a dropped response) harmless."""
    if not op_id:
        return True
    try:
        conn.execute("INSERT INTO ops(op_id, created_at) VALUES(?, ?)", (str(op_id)[:80], now_iso()))
        return True
    except sqlite3.IntegrityError:
        return False


def prune_ops(path, older_than_days=30):
    conn = _connect(path)
    try:
        cutoff = datetime.fromtimestamp(time.time() - older_than_days * 86400, timezone.utc)
        conn.execute("DELETE FROM ops WHERE created_at < ?", (cutoff.strftime("%Y-%m-%dT%H:%M:%S"),))
    finally:
        conn.close()
