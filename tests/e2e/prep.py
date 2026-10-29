"""Test copies start with every switched-on aura (Moni's magic item) off, so speeds and HP are
the sheets' own. Only ever run against the test server (run.py starts it on a copy of the data)."""
import json, urllib.request, uuid

import os
B = "http://127.0.0.1:" + os.environ.get("PORT", "5077")


def call(m, p, b=None):
    d = json.dumps(dict(b or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(B + p, data=d, method=m, headers={"Content-Type": "application/json"})))


for c in call("GET", "/api/campaigns/1/characters")["characters"]:
    ch = call("GET", f"/api/characters/{c['id']}")["character"]
    for i, s in enumerate(ch.get("spells") or []):
        if s.get("aura"):
            call("POST", f"/api/characters/{c['id']}/aura", {"index": i, "on": False})
            print("switched off", c["name"], s.get("name"))
