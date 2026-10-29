"""Instant updates: every open page keeps one connection (server-sent events) and hears
"something changed" the moment anyone changes anything, then reloads what it shows the way it
always has. No game data goes down this connection, only a counter, so players learn nothing they
couldn't already see. Pages still check every few seconds as a fallback if the connection drops."""
import queue
import threading
import time

_subs = set()
_lock = threading.Lock()
_count = 0
STREAM_SECONDS = 240  # each connection ends after this; the browser reconnects by itself
PING_SECONDS = 15     # a comment now and then keeps the connection (and any tunnel) open


def publish():
    """Tell every open page that something changed."""
    global _count
    with _lock:
        _count += 1
        n, subs = _count, list(_subs)
    for q in subs:
        try:
            q.put_nowait(n)
        except queue.Full:
            pass  # that page is behind; it reloads on the next one anyway


def listeners():
    with _lock:
        return len(_subs)


def stream(seconds=None, ping=None):
    """The event stream for one page (a generator of text/event-stream chunks)."""
    q = queue.Queue(maxsize=50)
    with _lock:
        _subs.add(q)
    seconds = STREAM_SECONDS if seconds is None else seconds
    ping = PING_SECONDS if ping is None else ping

    def gen():
        try:
            yield "retry: 2000\n\n"
            end = time.time() + seconds
            while True:
                left = end - time.time()
                if left <= 0:
                    return
                try:
                    n = q.get(timeout=min(ping, left))
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                while True:  # a burst of changes is one reload
                    try:
                        n = q.get_nowait()
                    except queue.Empty:
                        break
                yield f"event: change\ndata: {n}\n\n"
        finally:
            with _lock:
                _subs.discard(q)
    return gen()
