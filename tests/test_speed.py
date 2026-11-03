"""Smaller and cached: text is gzip-compressed for browsers that take it, versioned scripts and
styles are kept by the browser, and the live-update stream is left alone."""
import gzip


def test_static_files_are_compressed_and_kept(client):
    r = client.get("/static/js/core.js?v=1", headers={"Accept-Encoding": "gzip, br"})
    assert r.status_code == 200 and r.headers["Content-Encoding"] == "gzip"
    assert "immutable" in r.headers["Cache-Control"] and "Accept-Encoding" in r.headers["Vary"]
    body = gzip.decompress(r.data)
    assert b"window.L =" in body and len(r.data) < len(body) / 3
    again = client.get("/static/js/core.js?v=1", headers={"Accept-Encoding": "gzip"})
    assert again.data == r.data  # the compressed copy is kept
    plain = client.get("/static/js/core.js?v=1")
    assert "Content-Encoding" not in plain.headers and b"window.L =" in plain.data


def test_pages_and_data_are_compressed(client):
    r = client.get("/api/campaigns", headers={"Accept-Encoding": "gzip"})
    page = client.get("/", headers={"Accept-Encoding": "gzip"}, follow_redirects=True)
    assert page.headers.get("Content-Encoding") == "gzip" and b"<html" in gzip.decompress(page.data).lower()
    assert r.status_code == 200


def test_the_live_stream_is_not_compressed(client, monkeypatch):
    from app import events
    monkeypatch.setattr(events, "STREAM_SECONDS", 0.2)
    r = client.get("/api/play/events", headers={"Accept-Encoding": "gzip"})
    assert r.mimetype == "text/event-stream" and "Content-Encoding" not in r.headers


def test_small_copies_of_pictures_and_they_are_kept(app, client):
    import io, os
    from PIL import Image
    Image.new("RGB", (900, 600), "red").save(os.path.join(app.config["UPLOAD_DIR"], "abc123.png"))
    r = client.get("/api/uploads/abc123.png?w=128")
    assert r.status_code == 200 and "max-age=86400" in r.headers["Cache-Control"]
    im = Image.open(io.BytesIO(r.data))
    assert max(im.size) == 128
    assert client.get("/api/uploads/abc123.png").status_code == 200
    assert client.get("/api/uploads/missing.png?w=128").status_code == 404


def test_favicon_is_quiet(client):
    assert client.get("/favicon.ico").status_code == 204
