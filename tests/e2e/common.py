"""Where the browser tests find things on this computer: the app folder, the test server, this
computer's Wi-Fi address (phones join through it, so it's worked out each run), and folders for
screenshots and scratch files. run.py sets E2E_PORT."""
import os
import socket

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIR = os.path.join(HERE, "shots")
TMP_DIR = os.path.join(HERE, ".tmp")
os.makedirs(SHOTS_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)


def lan_ip():
    """This computer's address on the local network (no data is sent: a UDP socket only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


PORT = int(os.environ.get("E2E_PORT", "5077"))
LAN_IP = os.environ.get("E2E_LAN_IP") or lan_ip()
DM_URL = f"http://127.0.0.1:{PORT}"
LAN_URL = f"http://{LAN_IP}:{PORT}"
