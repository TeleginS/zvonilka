from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from zvonilka.config import GoogleSettings
from zvonilka.google_token import auth_url, exchange, pkce_pair

SETTINGS = GoogleSettings(client_id="id", client_secret="secret", refresh_token="")


def test_auth_url_asks_for_offline_access_with_pkce():
    verifier, challenge = pkce_pair()
    query = parse_qs(urlparse(auth_url("id", "http://127.0.0.1:5000", "st", challenge)).query)
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["code_challenge"] == [challenge] and query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["st"] and query["redirect_uri"] == ["http://127.0.0.1:5000"]
    assert verifier != challenge


def test_exchange_returns_refresh_token():
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["code"] == ["c"] and form["code_verifier"] == ["v"]
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert exchange(SETTINGS, "c", "http://127.0.0.1:5000", "v", http) == "r"


def test_exchange_without_refresh_token_fails_clearly():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "a"})))
    with pytest.raises(RuntimeError, match="no refresh_token"):
        exchange(SETTINGS, "c", "http://127.0.0.1:5000", "v", http)
