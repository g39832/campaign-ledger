"""Saints & Sinners morality tracker: a -100..+100 score moved one point at a time."""
import os
import sqlite3

import pytest

from app import create_app, db as appdb
from app.rules import SAINTS_SINNERS_LEVELS, saints_sinners_level
from tests.conftest import Api

EXPECTED = {
    -100: "Absolute Sinner", -76: "Absolute Sinner",
    -75: "Notorious Villain", -51: "Notorious Villain",
    -50: "Corrupted", -26: "Corrupted",
    -25: "Morally Questionable", -1: "Morally Questionable",
    0: "Unproven",
    1: "Virtuous", 25: "Virtuous",
    26: "Hero", 50: "Hero",
    51: "Saint", 75: "Saint",
    76: "Paragon of Good", 100: "Paragon of Good",
}
DESCRIPTIONS = {
    "Absolute Sinner": "A merciless individual known for cruelty, destruction, and having little regard for innocent life.",
    "Notorious Villain": "A feared individual whose selfish or brutal actions have earned them a dangerous reputation.",
    "Corrupted": "Someone who frequently puts personal gain above the well-being of others.",
    "Morally Questionable": "Someone whose choices are often selfish or questionable, but who has not fully embraced evil.",
    "Unproven": "Someone whose moral reputation has not yet been established.",
    "Virtuous": "Someone who generally acts with fairness, compassion, and integrity.",
    "Hero": "Someone who regularly stands up for others and takes meaningful risks to do what is right.",
    "Saint": "Someone known for extraordinary kindness, sacrifice, and dedication to helping others.",
    "Paragon of Good": "A legendary example of compassion and selflessness whose actions inspire others.",
}


@pytest.mark.parametrize("score,title", sorted(EXPECTED.items()))
def test_every_boundary(score, title):
    lvl = saints_sinners_level(score)
    assert lvl["title"] == title and lvl["description"] == DESCRIPTIONS[title]
    assert lvl["side"] == ("saint" if score > 0 else "sinner" if score < 0 else "neutral")


def test_levels_cover_every_score_exactly_once():
    for score in range(-100, 101):
        matches = [t for lo, hi, t, _ in SAINTS_SINNERS_LEVELS if lo <= score <= hi]
        assert len(matches) == 1, score


def step(api, cid, n, expect=200):
    return api.post(f"/api/characters/{cid}/saints-sinners", {"step": n}, expect)


@pytest.fixture
def char(api):
    camp = api.campaign()
    return api.character(camp["id"], name="Mira")


def test_starts_at_zero_unproven(api, char):
    s = api.get(f"/api/characters/{char['id']}/morality")["saints_sinners"]
    assert s["score"] == 0 and s["title"] == "Unproven"
    assert api.get(f"/api/characters/{char['id']}")["character"]["morality_score"] == 0


def test_buttons_move_exactly_one_point(api, char):
    assert step(api, char["id"], 1)["saints_sinners"]["score"] == 1
    assert step(api, char["id"], 1)["saints_sinners"]["score"] == 2
    assert step(api, char["id"], -1)["saints_sinners"]["score"] == 1
    for bad in (2, -2, 0, 5, "1", True, None):
        api.post(f"/api/characters/{char['id']}/saints-sinners", {"step": bad}, 400)
    assert api.get(f"/api/characters/{char['id']}/morality")["saints_sinners"]["score"] == 1


def test_walking_the_whole_scale(api, char):
    """Every boundary reached through the buttons themselves, title and description always matching."""
    seen = {}
    score = 0
    for _ in range(100):
        score = step(api, char["id"], 1)["saints_sinners"]["score"]
        seen[score] = step_result = api.get(f"/api/characters/{char['id']}/morality")["saints_sinners"]
        assert step_result["title"] == saints_sinners_level(score)["title"]
    assert score == 100
    assert step(api, char["id"], 1)["saints_sinners"]["score"] == 100, "can't go above +100"
    for _ in range(200):
        r = step(api, char["id"], -1)["saints_sinners"]
        seen[r["score"]] = r
    assert r["score"] == -100
    assert step(api, char["id"], -1)["saints_sinners"]["score"] == -100, "can't go below -100"
    for s, title in EXPECTED.items():
        assert seen[s]["title"] == title and seen[s]["description"] == DESCRIPTIONS[title], s


def test_retried_click_counts_once(api, char):
    body = {"step": 1, "op_id": "same-click"}
    api.post(f"/api/characters/{char['id']}/saints-sinners", body)
    r = api.post(f"/api/characters/{char['id']}/saints-sinners", body)
    assert r["saints_sinners"]["score"] == 1


def test_scores_are_per_character(api):
    camp = api.campaign()
    a, b = api.character(camp["id"], name="A"), api.character(camp["id"], name="B")
    step(api, a["id"], -1)
    assert api.get(f"/api/characters/{b['id']}/morality")["saints_sinners"]["score"] == 0


def test_does_not_touch_the_existing_morality_system(api, char):
    url = f"/api/characters/{char['id']}/morality"
    api.post(url, {"title": "Spared the bandit", "good_delta": 20}, 201)
    before = api.get(url)
    step(api, char["id"], -1)
    after = api.get(url)
    for k in ("law", "good", "events", "timeline", "computed_alignment"):
        assert after[k] == before[k]
    assert after["character"]["alignment"] == before["character"]["alignment"]


def test_score_survives_restart(data_dir):
    a = Api(create_app({"DATA_DIR": data_dir}).test_client())
    cid = a.character(a.campaign()["id"], name="Kael")["id"]
    for _ in range(30):
        a.post(f"/api/characters/{cid}/saints-sinners", {"step": -1})
    b = Api(create_app({"DATA_DIR": data_dir}).test_client())
    s = b.get(f"/api/characters/{cid}/morality")["saints_sinners"]
    assert s["score"] == -30 and s["title"] == "Corrupted"


def test_existing_database_upgrades_without_changing_data(tmp_path):
    """A v2 database (before this feature) keeps every value; characters start at 0."""
    data = tmp_path / "data"
    data.mkdir()
    path = str(data / "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    for v in (1, 2):
        for stmt in appdb._split_sql(appdb.MIGRATIONS[v]):
            conn.execute(stmt)
    conn.execute("PRAGMA user_version = 2")
    conn.execute("INSERT INTO campaigns (uid, name, created_at, updated_at) VALUES ('c', 'Old', 'x', 'x')")
    conn.execute("INSERT INTO characters (uid, campaign_id, name, current_hp, max_hp, alignment, created_at, updated_at) "
                 "VALUES ('h', 1, 'Old Hero', 7, 20, 'Lawful Good', 'x', 'x')")
    conn.commit()
    before = dict(zip([d[0] for d in conn.execute("SELECT * FROM characters").description], conn.execute("SELECT * FROM characters").fetchone()))
    conn.close()
    app = create_app({"DATA_DIR": str(data), "AUTO_SNAPSHOT": False})
    assert any(f.startswith("pre-migration-v2-to-v3") for f in os.listdir(data / "backups"))
    ch = Api(app.test_client()).get("/api/characters/1")["character"]
    for k, v in before.items():
        if k in ("abilities", "save_profs", "save_bonus", "skill_profs", "skill_bonus", "attacks", "spell_slots",
                 "spells", "equipment", "currency", "conditions"):
            continue  # JSON columns come back decoded
        assert ch[k] == (bool(v) if k in ("archived", "inspiration", "auto_alignment") else v), k
    assert ch["morality_score"] == 0


def test_morality_page_shows_tracker(api, client, char):
    html = client.get(f"/characters/{char['id']}/morality").get_data(as_text=True)
    assert 'id="saints-sinners"' in html and "−1" in html and "+1" in html
