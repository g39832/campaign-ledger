"""Start Campaign Ledger.

    python run.py                 # http://127.0.0.1:5050, opens your browser
    python run.py --port 8000
    python run.py --lan           # also reachable from phones/tablets on your Wi-Fi
    python run.py --no-browser
"""
import argparse
import socket
import threading
import webbrowser

from waitress import serve

from app import create_app


def lan_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def main():
    p = argparse.ArgumentParser(description="Run Campaign Ledger")
    p.add_argument("--port", type=int, default=5050)
    p.add_argument("--lan", action="store_true", help="listen on all network interfaces")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    app = create_app({"LAN_MODE": args.lan, "PORT": args.port})
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    url = f"http://127.0.0.1:{args.port}"
    print()
    print("  Campaign Ledger is running.")
    print(f"  Open {url} in your browser.")
    if args.lan:
        ip = lan_address()
        if ip:
            print(f"  On other devices on this network: http://{ip}:{args.port}")
    print(f"  Data is stored in: {app.config['DATA_DIR']}")
    print("  Press Ctrl+C (or close this window) to stop. Everything is already saved.")
    print()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(app, host=host, port=args.port, threads=8, ident="CampaignLedger")


if __name__ == "__main__":
    main()
