"""Hosted mode: the app runs on the Pi cluster at a fixed public address, behind the
cluster's Cloudflare connector (LEDGER_PUBLIC_URL + LEDGER_TRUSTED_PROXIES)."""
import pytest

from app import create_app
from tests.conftest import Api

PUBLIC = "https://dnd.example.org"
PROXY_IP = "10.42.1.6"           # the Cloudflare connector's pod address
CF = {"CF-Connecting-IP": "203.0.113.9", "Host": "dnd.example.org"}


@pytest.fixture
def hosted(data_dir):
    return create_app({"DATA_DIR": data_dir, "TESTING": True, "PUBLIC_URL": PUBLIC,
                       "TRUSTED_PROXIES": ["10.42.0.0/16"]})


def via_tunnel(app, visitor="203.0.113.9"):
    """A client reaching the app the way a friend does: through the cluster's connector."""
    c = app.test_client()
    c.environ_base["REMOTE_ADDR"] = PROXY_IP
    c.environ_base["HTTP_CF_CONNECTING_IP"] = visitor
    c.environ_base["HTTP_HOST"] = "dnd.example.org"
    return c


def test_online_panel_reports_the_fixed_address(hosted):
    dm = Api(hosted.test_client())
    s = dm.get("/api/online")
    assert s["hosted"] and s["running"] and s["url"] == PUBLIC
    assert dm.post("/api/online/start")["url"] == PUBLIC      # no quick tunnel is started
    assert dm.post("/api/online/stop")["running"]             # and it can't be "stopped"


def test_players_page_gets_the_public_link(hosted):
    dm = Api(hosted.test_client())
    camp = dm.campaign()
    info = dm.get(f"/api/campaigns/{camp['id']}/players")
    assert info["public_url"] == PUBLIC
    assert info["addresses"] == []                            # container addresses mean nothing to players


def test_visitors_through_the_connector_are_never_the_dm(hosted):
    friend = via_tunnel(hosted)
    assert friend.get("/api/online").status_code == 401
    assert friend.post("/api/dm-key", json={}).status_code == 401


def test_dm_link_made_inside_the_container_works_through_the_tunnel(hosted):
    key = Api(hosted.test_client()).post("/api/dm-key")["key"]   # e.g. kubectl exec ... on 127.0.0.1
    tablet = via_tunnel(hosted)
    r = tablet.get(f"/dm-login?key={key}")
    assert r.status_code == 302
    assert Api(tablet).get("/api/online")["hosted"]


def test_code_guessing_is_limited_per_visitor_not_per_connector(hosted):
    dm = Api(hosted.test_client())
    camp = dm.campaign()
    code = dm.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    guesser = Api(via_tunnel(hosted, visitor="198.51.100.66"))
    for _ in range(10):
        guesser.post("/api/join", {"code": "ZZZZZZ", "name": "X"}, 404)
    guesser.post("/api/join", {"code": code, "name": "X"}, 429)    # the guesser is slowed down...
    friend = Api(via_tunnel(hosted, visitor="203.0.113.10"))
    friend.post("/api/join", {"code": code, "name": "Sam"})        # ...but a friend still gets in


def test_forwarded_address_ignored_from_untrusted_sources(hosted):
    dm = Api(hosted.test_client())
    camp = dm.campaign()
    dm.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})
    stranger = hosted.test_client()
    stranger.environ_base["REMOTE_ADDR"] = "192.168.1.77"   # not a trusted proxy
    s = Api(stranger)
    for i in range(10):    # rotating a fake header doesn't dodge the limit
        stranger.environ_base["HTTP_CF_CONNECTING_IP"] = f"203.0.113.{i}"
        s.post("/api/join", {"code": "ZZZZZZ", "name": "X"}, 404)
    s.post("/api/join", {"code": "ZZZZZZ", "name": "X"}, 429)


def test_not_hosted_by_default(app):
    s = Api(app.test_client()).get("/api/online")
    assert not s.get("hosted")
