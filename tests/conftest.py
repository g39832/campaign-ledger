import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


@pytest.fixture
def data_dir(tmp_path):
    """Every test gets its own throwaway data folder; real data is never touched."""
    return str(tmp_path / "data")


@pytest.fixture
def app(data_dir):
    return create_app({"DATA_DIR": data_dir, "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


class Api:
    def __init__(self, client):
        self.c = client

    def _check(self, resp, expect):
        assert resp.status_code == expect, f"{resp.status_code}: {resp.get_data(as_text=True)}"
        return resp.get_json()

    def get(self, url, expect=200):
        return self._check(self.c.get(url), expect)

    def post(self, url, body=None, expect=200):
        return self._check(self.c.post(url, json=body or {}), expect)

    def patch(self, url, body, expect=200):
        return self._check(self.c.patch(url, json=body), expect)

    def delete(self, url, body=None, expect=200):
        return self._check(self.c.delete(url, json=body or {}), expect)

    # conveniences
    def campaign(self, name="Test Campaign"):
        return self.post("/api/campaigns", {"name": name}, 201)["campaign"]

    def character(self, cid, **fields):
        fields.setdefault("name", "Hero")
        return self.post(f"/api/campaigns/{cid}/characters", fields, 201)["character"]

    def set_char(self, char, **values):
        changes = {k: {"from": char[k], "to": v} for k, v in values.items()}
        return self.patch(f"/api/characters/{char['id']}", {"changes": changes})["character"]

    def encounter(self, cid, name="Ambush"):
        return self.post(f"/api/campaigns/{cid}/encounters", {"name": name}, 201)


@pytest.fixture
def api(client):
    return Api(client)
