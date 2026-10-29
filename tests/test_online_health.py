"""The online link: when Cloudflare drops it (it stops reaching the app), the Players page says so
and Go online / Get a new link stops the dead tunnel and makes a new one."""
import time

from app import online


def wait_checks(api, n=3):
    s = None
    for _ in range(n):
        s = api.get("/api/online")
        time.sleep(0.15)
    return api.get("/api/online")


def test_a_dead_link_is_noticed(app, api, monkeypatch):
    monkeypatch.setattr(online, "find_cloudflared", lambda: "cloudflared.exe")
    monkeypatch.setattr(online, "left_running", lambda: ("https://dead-link.trycloudflare.com", 20241))
    monkeypatch.setattr(online, "CHECK_EVERY", 0)
    monkeypatch.setattr(online, "probe", lambda url: False)
    online._health.update(url=None, fails=0, busy=False)
    s = wait_checks(api)
    assert s["running"] and s.get("broken") and "stopped working" in s["error"]


def test_a_working_link_is_fine(app, api, monkeypatch):
    monkeypatch.setattr(online, "find_cloudflared", lambda: "cloudflared.exe")
    monkeypatch.setattr(online, "left_running", lambda: ("https://good-link.trycloudflare.com", 20241))
    monkeypatch.setattr(online, "CHECK_EVERY", 0)
    monkeypatch.setattr(online, "probe", lambda url: True)
    online._health.update(url=None, fails=0, busy=False)
    s = wait_checks(api)
    assert s["running"] and not s.get("broken") and s["url"] == "https://good-link.trycloudflare.com"


def test_get_a_new_link_replaces_the_dead_one(app, api, monkeypatch):
    calls = {"stopped": 0, "started": 0}
    state = {"left": ("https://dead-link.trycloudflare.com", 20241)}
    monkeypatch.setattr(online, "find_cloudflared", lambda: "cloudflared.exe")
    monkeypatch.setattr(online, "left_running", lambda: state["left"])
    monkeypatch.setattr(online, "CHECK_EVERY", 0)
    monkeypatch.setattr(online, "probe", lambda url: "dead" not in url)
    online._health.update(url=None, fails=0, busy=False)
    wait_checks(api)

    def stop_old():
        calls["stopped"] += 1
        state["left"] = None
    monkeypatch.setattr(online, "stop_left_running", stop_old)

    class FakeProc:
        def poll(self):
            return None
    def popen(*a, **k):
        calls["started"] += 1
        state["left"] = ("https://fresh-link.trycloudflare.com", 20242)
        return FakeProc()
    monkeypatch.setattr(online.subprocess, "Popen", popen)
    s = api.post("/api/online/start", {})
    assert calls == {"stopped": 1, "started": 1}
    assert s["url"] == "https://fresh-link.trycloudflare.com" and not s.get("broken")
    online._state.update(proc=None, url=None)
