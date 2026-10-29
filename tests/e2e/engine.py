"""Which browser engine the E2E scripts run in: ENGINE=chromium (Chrome, Edge, Opera GX, Samsung
Internet), firefox, or webkit (Safari on iPhone and iPad)."""
import os

NAME = os.environ.get("ENGINE", "chromium")


def launch(p):
    if NAME == "chromium":
        return p.chromium.launch(channel="chrome", headless=True)
    return getattr(p, NAME).launch(headless=True)


def mobile():
    """Phone settings for a browser context (Firefox has no 'mobile' mode, only touch)."""
    return {} if NAME == "firefox" else {"is_mobile": True}
