from flask import Blueprint, abort, redirect, render_template, url_for

from . import fields as F, spell_book
from .campaigns import active_campaign, get_campaign, list_campaigns
from .characters import get_character, list_characters
from .combat import encounter_state, list_encounters
from .creatures import list_creatures
from .db import get_db, get_setting, set_setting, tx
from .journal import search_entries
from .morality import morality_state
from .rules import ABILITY_NAMES, ABILITIES, ALIGNMENTS, CONDITIONS, SKILLS, ac_bonus

bp = Blueprint("pages", __name__)


@bp.app_context_processor
def _globals():
    return {
        "theme": get_setting("theme", "dark"),
        "ABILITIES": ABILITIES,
        "ABILITY_NAMES": ABILITY_NAMES,
        "SKILLS": SKILLS,
        "ALIGNMENTS": ALIGNMENTS,
        "CONDITIONS": CONDITIONS,
        "JOURNAL_KINDS": F.JOURNAL_KINDS,
        "ac_bonus": ac_bonus,
        "SPELL_BOOK": spell_book.book(),
    }


def _fight(campaign, enc_id=None):
    """The fight the Combat and Battle map buttons jump to: the one on screen, or
    else the running fight most recently worked on. With the map it's on, if any."""
    if campaign is None:
        return None
    conn = get_db()
    if enc_id:
        enc = conn.execute("SELECT id, name, status FROM encounters WHERE id = ?", (enc_id,)).fetchone()
    else:
        enc = conn.execute("SELECT id, name, status FROM encounters WHERE campaign_id = ? AND status = 'active' "
                           "ORDER BY updated_at DESC LIMIT 1", (campaign["id"],)).fetchone()
    if enc is None:
        return None
    m = conn.execute("SELECT id FROM maps WHERE encounter_id = ? ORDER BY updated_at DESC LIMIT 1", (enc["id"],)).fetchone()
    return {"eid": enc["id"], "name": enc["name"], "status": enc["status"], "map_id": m["id"] if m else None}


def _shell(section, campaign, fight_id=None, **ctx):
    # page_fight: the fight on this page (the Combat | Map switch); fight: what the top menu jumps to
    page_fight = _fight(campaign, fight_id) if fight_id else None
    return dict(section=section, campaign=campaign, campaigns=[c for c in list_campaigns() if not c["archived"]],
                page_fight=page_fight, fight=page_fight or _fight(campaign), **ctx)


def _require_campaign():
    camp = active_campaign()
    if camp is None:
        return None
    return camp


def _switch_to(campaign_id):
    """Opening something from another campaign makes that campaign active, so
    the navigation and lists always match what's on screen."""
    if get_setting("active_campaign_id") != campaign_id:
        with tx() as conn:
            set_setting(conn, "active_campaign_id", campaign_id)
    return get_campaign(campaign_id)


@bp.get("/")
def dashboard():
    camp = _require_campaign()
    if camp is None:
        return render_template("welcome.html", **_shell("dashboard", None))
    conn = get_db()
    chars = list_characters(camp["id"])
    encounters = list_encounters(camp["id"])
    active_enc = next((e for e in encounters if e["status"] == "active"), None)
    active_state = encounter_state(active_enc["id"]) if active_enc else None
    journal = search_entries(camp["id"], limit=6)
    sessions = [j for j in search_entries(camp["id"], kind="session", limit=1)]
    open_threads = conn.execute(
        """SELECT id, kind, title, status FROM journal_entries WHERE campaign_id = ?
           AND kind IN ('quest','mystery','hook') AND status NOT IN ('completed','failed','solved','used','resolved')
           ORDER BY updated_at DESC LIMIT 8""", (camp["id"],)).fetchall()
    morality = conn.execute(
        """SELECT m.*, c.name AS character_name FROM morality_events m JOIN characters c ON c.id = m.character_id
           WHERE m.campaign_id = ? ORDER BY m.created_at DESC LIMIT 5""", (camp["id"],)).fetchall()
    from .morality import team_morality
    return render_template(
        "dashboard.html", saints_sinners=team_morality(camp["id"]),
        **_shell("dashboard", camp, characters=chars, encounters=encounters[:5], active=active_state,
                 journal=journal, last_session=sessions[0] if sessions else None,
                 threads=[dict(r) for r in open_threads], morality=[dict(r) for r in morality]))


@bp.get("/campaigns")
def campaigns():
    return render_template("campaigns.html", **_shell("campaigns", active_campaign(), all_campaigns=list_campaigns()))


@bp.get("/characters")
def characters():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    return render_template("characters.html", **_shell(
        "characters", camp, characters=list_characters(camp["id"]),
        archived=[c for c in list_characters(camp["id"], True) if c["archived"]]))


@bp.get("/characters/<int:char_id>")
def sheet(char_id):
    try:
        char = get_character(char_id)
    except F.NotFound:
        abort(404)
    camp = _switch_to(char["campaign_id"])
    return render_template("sheet.html", **_shell("characters", camp, char=char))


@bp.get("/characters/<int:char_id>/morality")
def character_morality(char_id):
    """Morality is tracked for the whole party now; old links go to the team page."""
    try:
        char = get_character(char_id)
    except F.NotFound:
        abort(404)
    _switch_to(char["campaign_id"])
    return redirect(url_for("pages.morality_overview"))


@bp.get("/morality")
def morality_overview():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    from .morality import team_morality
    from .rules import saints_sinners_all
    return render_template("morality.html", **_shell("morality", camp, saints_sinners=team_morality(camp["id"]),
                                                     levels=saints_sinners_all()))


@bp.get("/combat")
def combat_list():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    from .encounter_presets import listing as encounter_presets
    return render_template("combat_list.html", **_shell("combat", camp, encounters=list_encounters(camp["id"]),
                                                        encounter_presets=encounter_presets()))


@bp.get("/combat/<int:enc_id>")
def combat(enc_id):
    try:
        state = encounter_state(enc_id)
    except F.NotFound:
        abort(404)
    camp = _switch_to(state["encounter"]["campaign_id"])
    return render_template("combat.html", **_shell(
        "combat", camp, fight_id=enc_id, state=state, characters=list_characters(camp["id"]),
        creatures=list_creatures(camp["id"])))


@bp.get("/journal")
def journal():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    conn = get_db()
    linkables = {
        "character": [dict(id=r["id"], label=r["name"]) for r in conn.execute(
            "SELECT id, name FROM characters WHERE campaign_id = ? AND archived = 0 ORDER BY name", (camp["id"],))],
        "encounter": [dict(id=r["id"], label=r["name"]) for r in conn.execute(
            "SELECT id, name FROM encounters WHERE campaign_id = ? ORDER BY created_at DESC", (camp["id"],))],
        "morality": [dict(id=r["id"], label=f"{r['title']} ({r['name']})") for r in conn.execute(
            "SELECT m.id, m.title, c.name FROM morality_events m JOIN characters c ON c.id = m.character_id "
            "WHERE m.campaign_id = ? ORDER BY m.created_at DESC", (camp["id"],))],
    }
    return render_template("journal.html", **_shell("journal", camp, entries=search_entries(camp["id"]),
                                                    linkables=linkables))


@bp.get("/creatures")
def creatures():
    camp = active_campaign()
    encounters = [e for e in list_encounters(camp["id"]) if e["status"] != "ended"] if camp else []
    return render_template("creatures.html", **_shell(
        "creatures", camp, creatures=list_creatures(camp["id"] if camp else None), encounters=encounters))


@bp.get("/settings")
def settings():
    return render_template("settings.html", **_shell("settings", active_campaign(), all_campaigns=list_campaigns()))


@bp.get("/map")
def maps():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    conn = get_db()
    rows = conn.execute(
        "SELECT m.id, m.name, m.cols, m.rows, m.image, m.fog_enabled, m.updated_at, e.name AS encounter_name, "
        "(SELECT COUNT(*) FROM map_tokens WHERE map_id = m.id) AS token_count FROM maps m "
        "LEFT JOIN encounters e ON e.id = m.encounter_id WHERE m.campaign_id = ? ORDER BY m.updated_at DESC",
        (camp["id"],)).fetchall()
    from .map_presets import build, listing
    presets = listing()
    return render_template("maps.html", **_shell("map", camp, maps=[dict(r) for r in rows],
                                                 encounters=list_encounters(camp["id"]), map_presets=presets,
                                                 preset_terrain={p["key"]: build(p["key"]) for p in presets}))


@bp.get("/map/<int:map_id>")
def map_edit(map_id):
    from .maps import dm_state
    try:
        state = dm_state(map_id)
    except F.NotFound:
        abort(404)
    camp = _switch_to(state["map"]["campaign_id"])
    return render_template("map.html", **_shell("map", camp, fight_id=state["map"]["encounter_id"], state=state, characters=list_characters(camp["id"]),
                                                encounters=list_encounters(camp["id"])))


@bp.get("/table")
def table():
    camp = _require_campaign()
    if camp is None:
        return redirect(url_for("pages.dashboard"))
    from flask import current_app
    conn = get_db()
    maps_ = [dict(r) for r in conn.execute("SELECT id, name FROM maps WHERE campaign_id = ? ORDER BY updated_at DESC", (camp["id"],))]
    return render_template("table.html", **_shell("table", camp, maps=maps_, lan_mode=current_app.config["LAN_MODE"],
                                                  characters=[c for c in list_characters(camp["id"]) if c["kind"] == "pc"]))
