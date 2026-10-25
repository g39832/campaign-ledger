"""Saints & Sinners: one -100..+100 morality score for the whole party (campaign),
moved with +1/-1 buttons or set by typing a number."""
import os
import sqlite3

import pytest

from app import create_app, db as appdb
from app import dice
from app.rules import SAINTS_SINNERS_DETAILS, SAINTS_SINNERS_LEVELS, saints_sinners_level
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
        assert len([t for lo, hi, t, _ in SAINTS_SINNERS_LEVELS if lo <= score <= hi]) == 1, score


@pytest.fixture
def camp(api):
    return api.campaign("Party")


def url(c):
    return f"/api/campaigns/{c['id']}/saints-sinners"


def score(api, c):
    return api.get(url(c))["saints_sinners"]


def test_party_starts_at_zero_unproven(api, camp):
    s = score(api, camp)
    assert s["score"] == 0 and s["title"] == "Unproven"


def test_buttons_move_exactly_one_point(api, camp):
    assert api.post(url(camp), {"step": 1})["saints_sinners"]["score"] == 1
    assert api.post(url(camp), {"step": 1})["saints_sinners"]["score"] == 2
    assert api.post(url(camp), {"step": -1})["saints_sinners"]["score"] == 1
    for bad in (2, -2, 0, "1", True, None):
        api.post(url(camp), {"step": bad}, 400)
    assert score(api, camp)["score"] == 1


def test_typing_a_number(api, camp):
    s = api.post(url(camp), {"value": -42})["saints_sinners"]
    assert s["score"] == -42 and s["title"] == "Corrupted" and s["description"] == DESCRIPTIONS["Corrupted"]
    assert api.post(url(camp), {"value": "57"})["saints_sinners"]["title"] == "Saint", "typed text numbers work"
    assert api.post(url(camp), {"value": 0})["saints_sinners"]["title"] == "Unproven"
    assert api.post(url(camp), {"value": 250})["saints_sinners"]["score"] == 100, "kept within +100"
    assert api.post(url(camp), {"value": -999})["saints_sinners"]["score"] == -100, "kept within -100"
    for bad in ("abc", "1.5", 1.5, "", True, [3]):
        api.post(url(camp), {"value": bad}, 400)
    assert score(api, camp)["score"] == -100


def test_walking_the_whole_scale(api, camp):
    seen = {}
    for _ in range(100):
        r = api.post(url(camp), {"step": 1})["saints_sinners"]
        seen[r["score"]] = r
    assert r["score"] == 100
    assert api.post(url(camp), {"step": 1})["saints_sinners"]["score"] == 100, "can't go above +100"
    for _ in range(200):
        r = api.post(url(camp), {"step": -1})["saints_sinners"]
        seen[r["score"]] = r
    assert r["score"] == -100
    assert api.post(url(camp), {"step": -1})["saints_sinners"]["score"] == -100, "can't go below -100"
    assert len(seen) == 201
    for s, title in EXPECTED.items():
        assert seen[s]["title"] == title and seen[s]["description"] == DESCRIPTIONS[title], s


def test_retried_click_counts_once(api, camp):
    body = {"step": 1, "op_id": "same-click"}
    api.post(url(camp), body)
    assert api.post(url(camp), body)["saints_sinners"]["score"] == 1


def test_one_score_per_party_and_campaigns_are_separate(api, camp):
    api.character(camp["id"], name="A")
    api.character(camp["id"], name="B")
    api.post(url(camp), {"value": 30})
    other = api.campaign("Other party")
    assert score(api, other)["score"] == 0
    assert score(api, camp)["score"] == 30


def test_leaves_the_old_deed_data_alone(api, camp):
    ch = api.character(camp["id"], name="Mira")
    murl = f"/api/characters/{ch['id']}/morality"
    api.post(murl, {"title": "Spared the bandit", "good_delta": 20}, 201)
    before = api.get(murl)
    api.post(url(camp), {"value": -60})
    after = api.get(murl)
    for k in ("law", "good", "events", "computed_alignment"):
        assert after[k] == before[k]


def test_score_survives_restart(data_dir):
    a = Api(create_app({"DATA_DIR": data_dir}).test_client())
    c = a.campaign("Persist")
    for _ in range(30):
        a.post(url(c), {"step": -1})
    b = Api(create_app({"DATA_DIR": data_dir}).test_client())
    s = score(b, c)
    assert s["score"] == -30 and s["title"] == "Corrupted"


def test_existing_database_upgrades_without_changing_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = str(data / "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    for v in (1, 2, 3):
        for stmt in appdb._split_sql(appdb.MIGRATIONS[v]):
            conn.execute(stmt)
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO campaigns (uid, name, description, created_at, updated_at) VALUES ('c', 'Old', 'kept', 'x', 'x')")
    conn.execute("INSERT INTO characters (uid, campaign_id, name, current_hp, max_hp, morality_score, created_at, updated_at) "
                 "VALUES ('h', 1, 'Old Hero', 7, 20, 12, 'x', 'x')")
    conn.commit()
    conn.close()
    app = create_app({"DATA_DIR": str(data), "AUTO_SNAPSHOT": False})
    assert any(f.startswith("pre-migration-v3-to-v4") for f in os.listdir(data / "backups"))
    a = Api(app.test_client())
    camp = a.get("/api/campaigns")["campaigns"][0]
    assert camp["name"] == "Old" and camp["description"] == "kept"
    ch = a.get("/api/characters/1")["character"]
    assert (ch["name"], ch["current_hp"], ch["max_hp"], ch["morality_score"]) == ("Old Hero", 7, 20, 12), "existing data untouched"
    assert score(a, camp)["score"] == 0


def test_morality_page_is_just_the_tracker(api, client, camp):
    html = client.get("/morality").get_data(as_text=True)
    assert 'id="saints-sinners"' in html and 'id="ss-score"' in html and 'type="number"' in html
    assert "−1" in html and "+1" in html
    for gone in ('id="deed-form"', 'id="chart"', 'id="deeds"', 'id="manual-align"'):
        assert gone not in html
    ch = api.character(camp["id"], name="Mira")
    r = client.get(f"/characters/{ch['id']}/morality")
    assert r.status_code == 302 and r.headers["Location"].endswith("/morality")
    assert "Saints &amp; Sinners" in client.get("/").get_data(as_text=True)


PROS_CONS = {  # from the DM's Saints & Sinners table
    "Absolute Sinner": ("Feared by enemies", "Authorities hunt you"),
    "Notorious Villain": ("Criminal factions may offer deals", "Higher scrutiny from law enforcement"),
    "Corrupted": ("Easier access to shady contacts", "Honest NPCs become wary"),
    "Morally Questionable": ("Flexibility to negotiate with either side", "People may hesitate to trust you"),
    "Unproven": ("No established reputation", "No reputation-based favors"),
    "Virtuous": ("Civilians are more welcoming", "Criminals may see you as an obstacle"),
    "Hero": ("Better cooperation from communities", "Enemies may target you to damage your reputation"),
    "Saint": ("Strong community support", "Greater scrutiny"),
    "Paragon of Good": ("Legendary reputation", "Major enemies take notice"),
}


@pytest.mark.parametrize("title", [t for _, _, t, _ in SAINTS_SINNERS_LEVELS])
def test_every_level_has_benefits_drawbacks_examples_and_valid_rolls(title):
    d = SAINTS_SINNERS_DETAILS[title]
    assert d["pros"][0] == PROS_CONS[title][0] and d["cons"][0] == PROS_CONS[title][1]
    assert d["modifiers"] and len(d["examples"]) >= 2 and d["rolls"]
    for r in d["rolls"]:
        dice.parse(r["expression"])  # every roll button is a valid dice expression
        assert r["label"]


def test_details_follow_the_score(api, camp):
    s = api.post(url(camp), {"value": -80})["saints_sinners"]
    assert s["title"] == "Absolute Sinner" and s["pros"][0] == "Feared by enemies" and s["range"] == [-100, -76]
    s = api.post(url(camp), {"value": 80})["saints_sinners"]
    assert s["title"] == "Paragon of Good" and s["cons"][0] == "Major enemies take notice"


def test_page_shows_effects_and_all_levels(api, client, camp):
    html = client.get("/morality").get_data(as_text=True)
    for piece in ('id="ss-pros"', 'id="ss-cons"', 'id="ss-mods"', 'id="ss-examples"', 'id="ss-rolls"', "All levels"):
        assert piece in html, piece
    for _, _, title, _ in SAINTS_SINNERS_LEVELS:
        assert f'data-title="{title}"' in html


def test_effect_rolls_go_through_the_dice_roller(api, camp):
    r = SAINTS_SINNERS_DETAILS["Notorious Villain"]["rolls"][0]
    roll = api.post("/api/rolls", {"expression": r["expression"], "label": "Notorious Villain: " + r["label"],
                                   "campaign_id": camp["id"]}, 201)["roll"]
    assert 1 <= roll["total"] <= 6 and roll["label"].startswith("Notorious Villain")
