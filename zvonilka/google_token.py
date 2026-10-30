"""Get GOOGLE_REFRESH_TOKEN for the calendar, once (spec 7.1).

    uv run zvonilka-google-token

Reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from .env (an OAuth client of
the Desktop type), opens the Google sign-in in the browser, catches the
redirect on localhost and prints the line to put into .env.

While the OAuth app is in Testing status, Google expires its refresh tokens
after 7 days; publish the app (Audience → Publish app) to keep the token.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import load_dotenv

from zvonilka.config import GoogleSettings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# Read-only is enough: the bot only asks the calendar for busy intervals.
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    # access_type=offline and prompt=consent: without them Google returns no
    # refresh token when the account has already granted access once.
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def exchange(settings: GoogleSettings, code: str, redirect_uri: str, verifier: str,
             http: httpx.Client | None = None) -> str:
    http = http or httpx.Client(timeout=15)
    response = http.post(TOKEN_URL, data={
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    response.raise_for_status()
    token = response.json().get("refresh_token")
    if not token:
        raise RuntimeError("Google returned no refresh_token; revoke the app's access in your Google account and retry")
    return token


def wait_for_redirect(server: HTTPServer) -> dict[str, str]:
    """Serve one request on the loopback address and return its query."""
    query: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Done, you can close this tab and go back to the terminal.".encode())

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    while not query:
        server.handle_request()
    return query


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    settings = GoogleSettings.from_env(os.environ)
    if not settings.client_id or not settings.client_secret:
        print("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env", file=sys.stderr)
        return 1

    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    url = auth_url(settings.client_id, redirect_uri, state, challenge)

    print(f"Opening the browser. If it doesn't open, go to:\n\n{url}\n")
    webbrowser.open(url)
    try:
        query = wait_for_redirect(server)
    finally:
        server.server_close()

    if query.get("state") != state:
        print("state mismatch, try again", file=sys.stderr)
        return 1
    if "error" in query:
        print(f"Google refused: {query['error']}", file=sys.stderr)
        return 1

    token = exchange(settings, query["code"], redirect_uri, verifier)
    print(f"Put this into .env:\n\nGOOGLE_REFRESH_TOKEN={token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
