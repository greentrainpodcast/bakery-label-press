"""One-time helper to mint a Google OAuth refresh token for the labels pipeline.

Run this on your laptop (NOT inside CI). It opens a browser, asks you to log
in to the Google account that owns the Lully Drive folder + Sheet, and prints
the refresh token + the matching client ID/secret to stdout. Paste those
three values into GitHub repository secrets.

Prerequisite — create an OAuth client one time:
  1. https://console.cloud.google.com/apis/credentials → Create Credentials →
     OAuth client ID → Desktop app. Save client_id + client_secret.
  2. Enable Sheets API + Drive API for that GCP project.
  3. https://console.cloud.google.com/apis/credentials/consent → add your
     Google account as a test user (External, in-test mode is fine).

Then:
  python3 scripts/oauth-setup.py --client-id <ID> --client-secret <SECRET>
"""
from __future__ import annotations

import argparse
import http.server
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

import requests

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",      # files we create only
    "https://www.googleapis.com/auth/spreadsheets",    # read/write the Sheet
]
PORT = 8765
REDIRECT = f"http://localhost:{PORT}/callback"


class _Catcher(http.server.BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802 — http.server API
        qs = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(qs))
        # Only accept the real OAuth callback. Ignore favicons, preflights,
        # browser preloads, leftover tabs from previous runs, etc.
        if "code" in params and "state" in params:
            _Catcher.captured = params
            body = (b"<html><body style='font-family:sans-serif;text-align:center;"
                    b"padding-top:40px'><h2>Got it.</h2><p>You can close this tab "
                    b"and return to the terminal.</p></body></html>")
        else:
            print(f"  [debug] ignoring request to {self.path}", file=sys.stderr)
            body = b"<html><body>(ignored - waiting for OAuth callback)</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a, **kw):  # noqa: D401 — silence default logging
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", required=True)
    args = p.parse_args()

    state = secrets.token_urlsafe(16)
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id":     args.client_id,
        "redirect_uri":  REDIRECT,
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         state,
    })

    print(f"Opening browser for OAuth consent…\n  {auth_url}\n")
    server = http.server.HTTPServer(("localhost", PORT), _Catcher)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(auth_url)

    while not _Catcher.captured:
        time.sleep(0.1)
    server.shutdown()
    captured = _Catcher.captured

    if captured.get("state") != state:
        print("✗ State mismatch. Aborting.", file=sys.stderr)
        return 1
    if "code" not in captured:
        print(f"✗ No code in callback: {captured}", file=sys.stderr)
        return 1

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code":          captured["code"],
        "client_id":     args.client_id,
        "client_secret": args.client_secret,
        "redirect_uri":  REDIRECT,
        "grant_type":    "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    refresh = tok.get("refresh_token")
    if not refresh:
        print("✗ Google did not return a refresh_token. Likely the OAuth client "
              "has been authorised before — revoke it at "
              "https://myaccount.google.com/permissions and re-run.", file=sys.stderr)
        return 1

    print("\n✓ Done. Add these as GitHub repository secrets")
    print("  (Settings → Secrets and variables → Actions → New repository secret):\n")
    print(f"  GOOGLE_OAUTH_CLIENT_ID      = {args.client_id}")
    print(f"  GOOGLE_OAUTH_CLIENT_SECRET  = {args.client_secret}")
    print(f"  GOOGLE_OAUTH_REFRESH_TOKEN  = {refresh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
