from __future__ import annotations

import base64
import io
import json
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from academic_profile import ai_provider, chatgpt_auth
from academic_profile.ai_provider import ChatGPTProvider
from academic_profile.chatgpt_auth import AIServiceError, ChatGPTAuth


class TestProtector:
    def protect(self, contents: bytes) -> bytes:
        return b"TEST-ENCRYPTED:" + bytes(value ^ 0xA5 for value in contents)

    def unprotect(self, contents: bytes) -> bytes:
        assert contents.startswith(b"TEST-ENCRYPTED:")
        return bytes(value ^ 0xA5 for value in contents[len(b"TEST-ENCRYPTED:"):])


@pytest.fixture
def auth(tmp_path):
    return ChatGPTAuth(tmp_path / "protected", protector=TestProtector())


@pytest.fixture
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()

    def encode_int(value):
        return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()

    jwk = {"kty": "RSA", "kid": "unit-test", "alg": "RS256", "n": encode_int(public.n), "e": encode_int(public.e)}
    return key, jwk


def _begin(auth):
    url = auth.begin("http://127.0.0.1:52847/auth/callback")
    params = {key: value[0] for key, value in parse_qs(urlparse(url).query).items()}
    return url, params


def _complete(auth, monkeypatch, signing_key, params, *, scope=chatgpt_auth.SCOPES, claims_override=None):
    key, jwk = signing_key
    claims = {
        "iss": chatgpt_auth.AUTHORITY,
        "sub": "account-123",
        "aud": "oaiapp_test-client",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "nonce": params["nonce"],
        "email": "student@example.com",
    }
    claims.update(claims_override or {})
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "unit-test"})
    calls = []

    def request(url, *, form=None):
        calls.append((url, form))
        if url == chatgpt_auth.TOKEN_URL:
            return {
                "id_token": token, "access_token": "access-secret", "refresh_token": "refresh-secret",
                "token_type": "Bearer", "expires_in": 3600, "scope": scope,
            }
        if url == chatgpt_auth.DISCOVERY_URL:
            return {"issuer": chatgpt_auth.AUTHORITY, "jwks_uri": f"{chatgpt_auth.AUTHORITY}/.well-known/jwks.json"}
        if url.endswith("/jwks.json"):
            return {"keys": [jwk]}
        raise AssertionError(url)

    monkeypatch.setattr(chatgpt_auth, "_json_request", request)
    result = auth.complete({"code": "one-time-code", "state": params["state"], "client_id": "oaiapp_test-client"})
    return result, calls


def test_first_registration_pkce_signed_identity_and_protected_storage(auth, monkeypatch, signing_key):
    url, params = _begin(auth)
    assert url.startswith(chatgpt_auth.AUTHORIZE_URL)
    assert params["client_id"] == "dynamic_agent_client"
    assert params["agent_name_hint"] == chatgpt_auth.APP_NAME
    assert params["scope"].split() == chatgpt_auth.SCOPES.split()
    assert params["ext_agent_host_id"].startswith("urn:uuid:")
    assert params["code_challenge_method"] == "S256"
    assert params["resource"] == chatgpt_auth.RESOURCE
    assert "access-secret" not in url
    result, calls = _complete(auth, monkeypatch, signing_key, params)
    assert result["connected"] is True
    assert result["sharing"] is True
    assert result["email"] == "student@example.com"
    assert "token" not in result
    exchange = calls[0][1]
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == "oaiapp_test-client"
    assert exchange["redirect_uri"] == "http://127.0.0.1:52847/auth/callback"
    assert exchange["resource"] == chatgpt_auth.RESOURCE
    assert exchange["code_verifier"]
    assert b"access-secret" not in auth._file.read_bytes()
    assert b"refresh-secret" not in auth._file.read_bytes()
    assert auth.access_token() == "access-secret"

    second_url, second = _begin(auth)
    assert second["client_id"] == "oaiapp_test-client"
    assert second["ext_agent_host_id"] == params["ext_agent_host_id"]
    assert "agent_name_hint" not in second
    assert "id_token_hint" not in second_url
    assert second["state"] != params["state"]


def test_callback_state_and_client_id_rejection(auth, monkeypatch):
    _, params = _begin(auth)
    with pytest.raises(AIServiceError, match="校验失败") as exc:
        auth.complete({"code": "x", "state": "wrong", "client_id": "oaiapp_test-client"})
    assert exc.value.code == "invalid_oauth_state"
    assert auth.status()["pending"] is True
    with pytest.raises(AIServiceError) as exc:
        auth.complete({"code": "x", "state": params["state"]})
    assert exc.value.code == "missing_client_id"
    assert auth.status()["pending"] is False


@pytest.mark.parametrize("override", [
    {"nonce": "wrong"}, {"aud": "wrong-client"}, {"iss": "https://example.invalid"},
    {"exp": 1}, {"sub": ""},
])
def test_identity_validation_rejects_wrong_claims(auth, monkeypatch, signing_key, override):
    _, params = _begin(auth)
    with pytest.raises(AIServiceError) as exc:
        _complete(auth, monkeypatch, signing_key, params, claims_override=override)
    assert exc.value.code == "invalid_id_token"
    assert not auth.status()["connected"]


def test_missing_plan_scope_never_used(auth, monkeypatch, signing_key):
    _, params = _begin(auth)
    result, _ = _complete(auth, monkeypatch, signing_key, params, scope="openid profile email offline_access")
    assert result["connected"] and not result["sharing"]
    with pytest.raises(AIServiceError) as exc:
        auth.access_token()
    assert exc.value.code == "plan_permission_missing"


def test_expired_access_refreshes_with_rotated_token(auth, monkeypatch, signing_key):
    _, params = _begin(auth)
    _complete(auth, monkeypatch, signing_key, params)
    saved = auth._load()
    saved["expires_at"] = time.time() - 1
    auth._save(saved)
    calls = []

    def refresh(url, *, form=None):
        calls.append(form)
        return {
            "access_token": "access-new", "refresh_token": "refresh-new",
            "expires_in": 3600, "scope": chatgpt_auth.SCOPES,
        }

    monkeypatch.setattr(chatgpt_auth, "_json_request", refresh)
    assert auth.access_token() == "access-new"
    assert auth.access_token() == "access-new"
    assert len(calls) == 1
    assert calls[0] == {
        "grant_type": "refresh_token", "client_id": "oaiapp_test-client",
        "refresh_token": "refresh-secret", "resource": chatgpt_auth.RESOURCE,
    }
    assert auth._load()["refresh_token"] == "refresh-new"


def test_terminal_refresh_error_clears_tokens_but_keeps_registration(auth, monkeypatch, signing_key):
    _, params = _begin(auth)
    _complete(auth, monkeypatch, signing_key, params)
    saved = auth._load()
    saved["expires_at"] = time.time() - 1
    auth._save(saved)

    def fail(url, *, form=None):
        raise AIServiceError("ChatGPT 登录已失效，请重新登录。", "invalid_grant", status=400)

    monkeypatch.setattr(chatgpt_auth, "_json_request", fail)
    with pytest.raises(AIServiceError) as exc:
        auth.access_token()
    assert exc.value.code == "invalid_grant"
    assert not auth.status()["connected"]
    assert auth.status()["can_reauthorize"]


def test_invalid_grant_retains_dynamic_registration_for_retry(auth, monkeypatch):
    _, params = _begin(auth)

    def fail(url, *, form=None):
        raise AIServiceError("授权码已过期。", "invalid_grant", status=400)

    monkeypatch.setattr(chatgpt_auth, "_json_request", fail)
    with pytest.raises(AIServiceError) as exc:
        auth.complete({"code": "expired", "state": params["state"], "client_id": "oaiapp_test-client"})
    assert exc.value.code == "invalid_grant"
    assert not auth.status()["connected"]
    assert _begin(auth)[1]["client_id"] == "oaiapp_test-client"


def test_disconnect_clears_local_tokens_even_if_remote_revoke_fails(auth, monkeypatch, signing_key):
    _, params = _begin(auth)
    _complete(auth, monkeypatch, signing_key, params)
    monkeypatch.setattr(chatgpt_auth, "_json_request", lambda url, *, form=None: {
        "issuer": chatgpt_auth.AUTHORITY,
        "revocation_endpoint": f"{chatgpt_auth.AUTHORITY}/api/accounts/oauth/revoke",
    })

    def fail(request, timeout):
        raise OSError("offline")

    monkeypatch.setattr(chatgpt_auth, "urlopen", fail)
    result = auth.disconnect()
    assert result["connected"] is False
    assert result["revocation_confirmed"] is False
    assert result["warning"]
    assert auth.status()["can_reauthorize"] is True
    assert "access_token" not in auth._load()


class StaticAuth:
    def access_token(self):
        return "oauth-plan-token"


def test_provider_catalog_only_visible_models(monkeypatch):
    captured = []

    def open_request(request, timeout):
        captured.append(request)
        return io.BytesIO(json.dumps({"models": [
            {"slug": "model-a", "display_name": "Model A", "visibility": "list"},
            {"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"},
        ]}).encode())

    monkeypatch.setattr(ai_provider, "urlopen", open_request)
    provider = ChatGPTProvider(StaticAuth())
    assert provider.list_models() == [{"slug": "model-a", "display_name": "Model A"}]
    assert captured[0].full_url == f"{chatgpt_auth.RESOURCE}/models"
    assert captured[0].get_header("Authorization") == "Bearer oauth-plan-token"


def test_provider_stream_requires_completion_and_exact_plan_body(monkeypatch):
    captured = []
    events = b"".join([
        b'data: {"type":"response.output_text.delta","delta":"Hello "}\n\n',
        b'data: {"type":"response.output_text.delta","delta":"world"}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n',
        b'data: [DONE]\n\n',
    ])

    def open_request(request, timeout):
        captured.append(request)
        return io.BytesIO(events)

    monkeypatch.setattr(ai_provider, "urlopen", open_request)
    provider = ChatGPTProvider(StaticAuth())
    assert provider.complete_text("model-a", "Return plain text", "Note") == "Hello world"
    request = captured[0]
    assert request.full_url == f"{chatgpt_auth.RESOURCE}/responses"
    assert request.get_header("Authorization") == "Bearer oauth-plan-token"
    body = json.loads(request.data)
    assert body == {
        "model": "model-a", "instructions": "Return plain text",
        "input": [{"role": "user", "content": "Note"}],
        "store": False, "stream": True,
    }


@pytest.mark.parametrize("events,expected", [
    (b'data: {"type":"response.output_text.delta","delta":"Partial"}\n\n', "stream_interrupted"),
    (b'data: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}}\n\n', "subscription_sharing_usage_limit_exceeded"),
    (b'data: {"type":"response.incomplete"}\n\n', "response_incomplete"),
])
def test_provider_rejects_failed_or_interrupted_stream(monkeypatch, events, expected):
    monkeypatch.setattr(ai_provider, "urlopen", lambda request, timeout: io.BytesIO(events))
    with pytest.raises(AIServiceError) as exc:
        ChatGPTProvider(StaticAuth()).complete_text("model-a", "instruction", "input")
    assert exc.value.code == expected


def test_provider_preserves_structured_http_error(monkeypatch):
    def fail(request, timeout):
        body = io.BytesIO(json.dumps({"error": {"code": "subscription_sharing_user_not_eligible"}}).encode())
        raise HTTPError(request.full_url, 403, "Forbidden", {"x-request-id": "req_123"}, body)

    monkeypatch.setattr(ai_provider, "urlopen", fail)
    with pytest.raises(AIServiceError) as exc:
        ChatGPTProvider(StaticAuth()).list_models()
    assert exc.value.code == "subscription_sharing_user_not_eligible"
    assert exc.value.status == 403
    assert exc.value.request_id == "req_123"
    assert "API" not in str(exc.value)
