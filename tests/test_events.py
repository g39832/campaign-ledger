"""Instant updates: any change (a write) tells every open page at once; reads don't; a burst of
changes is one message; connections ping now and then and end so the browser reconnects."""
import threading
import time

from app import events
from tests.test_dice_map_players import joined  # noqa: F401  (fixture)


def collect(gen, until):
    out = []
    for chunk in gen:
        out.append(chunk)
        if until(out):
            break
    return out


def test_a_change_reaches_an_open_page(api):
    gen = events.stream(seconds=5, ping=5)
    assert next(gen).startswith("retry:")
    got = []
    t = threading.Thread(target=lambda: got.extend(collect(gen, lambda o: any("event: change" in c for c in o))))
    t.start()
    time.sleep(0.2)
    api.post("/api/campaigns", {"name": "Live"}, 201)           # any write
    t.join(3)
    assert any("event: change" in c for c in got)
    gen.close()
    assert events.listeners() == 0                                # closed pages stop listening


def test_reads_dont_count_and_bursts_are_one(api):
    gen = events.stream(seconds=1.2, ping=0.3)
    next(gen)
    api.get("/api/campaigns")                                     # a read: nothing
    for _ in range(5):                                            # a burst
        events.publish()
    chunks = list(gen)                                            # the stream ends by itself
    changes = [c for c in chunks if c.startswith("event: change")]
    assert len(changes) == 1
    assert any(c.startswith(": ping") for c in chunks)            # it keeps the connection open


def test_the_events_endpoint_is_for_players_and_dm(app, api, joined):
    r = joined["pa"].c.get("/api/play/events", buffered=False)
    assert r.status_code == 200 and r.mimetype == "text/event-stream"
    assert next(iter(r.response)).startswith(b"retry:")
    r.close()
