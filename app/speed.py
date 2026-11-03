"""Faster over the online link: smaller responses and files the browser keeps.

- Text (pages, data, scripts, styles, the icon sprite) is gzip-compressed when the browser accepts
  it: about a fifth of the size, which matters most over the Cloudflare link to players' phones.
- Scripts and styles are loaded with ?v=N, which changes with every update, so the browser may
  keep them for a year without asking again. Fonts keep for 30 days, pictures people upload for a day.
- The live-update stream is never compressed or held back (it's a trickle of tiny messages).
"""
import gzip
import os
import threading

from flask import request

COMPRESSIBLE = ("text/html", "text/css", "application/json", "application/javascript", "text/javascript", "image/svg+xml", "text/plain")
MIN_SIZE = 1024
_cache, _lock = {}, threading.Lock()  # static file -> its gzip bytes (by path, size and time changed)


def _gzip_static(resp):
    path = getattr(resp, "_static_path", None)
    key = None
    if path:
        try:
            st = os.stat(path)
            key = (path, st.st_size, st.st_mtime_ns)
        except OSError:
            key = None
    if key:
        with _lock:
            hit = _cache.get(key)
        if hit is not None:
            return hit
    resp.direct_passthrough = False
    body = gzip.compress(resp.get_data(), compresslevel=6)
    if key:
        with _lock:
            if len(_cache) > 200:
                _cache.clear()
            _cache[key] = body
    return body


def after(resp):
    p = request.path
    if p.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if request.args.get("v") \
            else "public, max-age=2592000" if p.startswith("/static/fonts/") else "public, max-age=3600"
    elif p.startswith("/api/uploads/") and resp.status_code == 200:
        resp.headers["Cache-Control"] = "private, max-age=86400"
    if (resp.status_code != 200 or resp.is_streamed and not resp.direct_passthrough or resp.mimetype == "text/event-stream"
            or "gzip" not in (request.headers.get("Accept-Encoding") or "").lower() or resp.headers.get("Content-Encoding")
            or resp.mimetype not in COMPRESSIBLE or request.headers.get("Range")):
        return resp
    if resp.direct_passthrough:  # a file sent from disk (scripts, styles)
        if (resp.content_length or 0) < MIN_SIZE:
            return resp
        body = _gzip_static(resp)
    else:
        data = resp.get_data()
        if len(data) < MIN_SIZE:
            return resp
        body = gzip.compress(data, compresslevel=5)
    resp.set_data(body)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(body))
    vary = resp.headers.get("Vary")
    resp.headers["Vary"] = (vary + ", Accept-Encoding") if vary and "accept-encoding" not in vary.lower() else (vary or "Accept-Encoding")
    return resp


def setup(app):
    """Hook it in. Static files remember where they came from, so their compressed copy is kept."""
    orig = app.send_static_file

    def send_static_file(filename):
        resp = orig(filename)
        resp._static_path = os.path.join(app.static_folder, filename)
        return resp
    app.send_static_file = send_static_file
    app.view_functions["static"] = send_static_file
    app.after_request(after)

    @app.get("/favicon.ico")
    def favicon():
        """The pages have their icon built in; this stops browsers fetching an error page for it every time."""
        from flask import Response
        return Response(status=204, headers={"Cache-Control": "public, max-age=2592000"})
