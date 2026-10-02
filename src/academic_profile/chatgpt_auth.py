"""Sign in with ChatGPT for the local, single-user Academic Profile app.

Only OpenAI's documented open-source ChatGPT-plan flow is supported here.  In
particular, this module never obtains an API key or selects another billable
provider when plan permission is unavailable.
"""

from __future__ import annotations

import base64
import contextlib
import ctypes
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import jwt


AUTHORITY = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTHORITY}/api/accounts/authorize"
TOKEN_URL = f"{AUTHORITY}/api/accounts/oauth/token"
DISCOVERY_URL = f"{AUTHORITY}/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
APP_NAME = "昭濂学术档案"
_TIMEOUT = 25


class AIServiceError(RuntimeError):
    """A safe message for the UI, with a machine-readable recovery code."""

    def __init__(
        self,
        message: str,
        code: str = "ai_error",
        *,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id


def _network_error(exc: BaseException) -> AIServiceError:
    if isinstance(exc, HTTPError):
        status = exc.code
        request_id = exc.headers.get("x-request-id") or exc.headers.get("openai-request-id")
        try:
            body = json.loads(exc.read(65536).decode("utf-8"))
        except (UnicodeError, ValueError, OSError):
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if not code and isinstance(error, str):
            code = error
        code = str(code or f"http_{status}")
        if code in {"invalid_grant", "invalid_refresh_token", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused", "token_expired"}:
            message = "ChatGPT 登录已失效，请重新登录。"
        elif status == 401:
            message = "ChatGPT 授权未通过，请重新登录。"
        elif status == 403:
            message = "当前 ChatGPT 账号或地区暂不能使用此功能。"
        elif status == 429:
            message = "ChatGPT 请求过于频繁，请稍后重试。"
        elif status >= 500:
            message = "ChatGPT 服务暂时不可用，请稍后重试。"
        else:
            message = "ChatGPT 授权请求失败，请重试。"
        return AIServiceError(message, code, status=status, request_id=request_id)
    return AIServiceError("无法连接 ChatGPT，请检查网络后重试。", "offline")


def _json_request(url: str, *, form: Mapping[str, str] | None = None) -> dict[str, Any]:
    data = urlencode(form).encode("utf-8") if form is not None else None
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", **({"Content-Type": "application/x-www-form-urlencoded"} if data is not None else {})},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            result = json.load(response)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise _network_error(exc) from None
    except (ValueError, UnicodeError):
        raise AIServiceError("ChatGPT 返回的数据无法读取，请稍后重试。", "invalid_response") from None
    if not isinstance(result, dict):
        raise AIServiceError("ChatGPT 返回的数据格式不正确。", "invalid_response")
    return result


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDPAPI:
    """Windows current-user DPAPI, deliberately without a plaintext fallback."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise AIServiceError("令牌保护仅支持 Windows，AI 登录已停用。", "secure_storage_unavailable")
        self.crypt32 = ctypes.WinDLL("crypt32.dll")
        self.kernel32 = ctypes.WinDLL("kernel32.dll")
        for name in ("CryptProtectData", "CryptUnprotectData"):
            function = getattr(self.crypt32, name)
            function.argtypes = [
                ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_DATA_BLOB),
                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
            ] if name == "CryptProtectData" else [
                ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DATA_BLOB),
                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
            ]
            function.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p

    def _transform(self, contents: bytes, *, protect: bool) -> bytes:
        source_buffer = (ctypes.c_ubyte * len(contents)).from_buffer_copy(contents)
        source = _DATA_BLOB(len(contents), source_buffer)
        destination = _DATA_BLOB()
        method = self.crypt32.CryptProtectData if protect else self.crypt32.CryptUnprotectData
        if protect:
            success = method(ctypes.byref(source), APP_NAME, None, None, None, 1, ctypes.byref(destination))
        else:
            success = method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination))
        if not success:
            raise AIServiceError("无法访问 Windows 加密的 ChatGPT 登录信息。", "secure_storage_unavailable")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            self.kernel32.LocalFree(ctypes.cast(destination.pbData, ctypes.c_void_p))

    def protect(self, contents: bytes) -> bytes:
        return self._transform(contents, protect=True)

    def unprotect(self, contents: bytes) -> bytes:
        return self._transform(contents, protect=False)


def default_auth_home() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local_app_data:
        raise AIServiceError("无法找到 Windows 用户数据目录，AI 登录已停用。", "secure_storage_unavailable")
    return Path(local_app_data) / "AcademicProfile" / "chatgpt"


class ChatGPTAuth:
    """Single active ChatGPT registration; credentials remain in DPAPI storage."""

    def __init__(self, home: Path | None = None, *, protector: Any | None = None) -> None:
        self.home = Path(home) if home is not None else default_auth_home()
        self._file = self.home / "auth.bin"
        self._protector = protector if protector is not None else WindowsDPAPI()
        self._lock = threading.RLock()
        self._pending: dict[str, Any] | None = None

    @contextlib.contextmanager
    def _storage_lock(self):
        """Serialize rotating refresh tokens across local service processes."""
        with self._lock:
            if os.name != "nt":
                yield
                return
            kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            digest = hashlib.sha256(str(self.home.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
            handle = kernel32.CreateMutexW(None, False, f"Local\\AcademicProfileChatGPT_{digest}")
            if not handle:
                raise AIServiceError("无法锁定 ChatGPT 登录信息，请重试。", "secure_storage_unavailable")
            acquired = False
            try:
                result = kernel32.WaitForSingleObject(handle, 30000)
                acquired = result in (0, 0x80)  # WAIT_OBJECT_0 or abandoned mutex
                if not acquired:
                    raise AIServiceError("ChatGPT 登录信息正在被其他窗口使用，请重试。", "storage_busy")
                yield
            finally:
                if acquired:
                    kernel32.ReleaseMutex(handle)
                kernel32.CloseHandle(handle)

    def _load(self) -> dict[str, Any]:
        try:
            ciphertext = self._file.read_bytes()
        except FileNotFoundError:
            return {}
        try:
            contents = json.loads(self._protector.unprotect(ciphertext).decode("utf-8"))
        except AIServiceError:
            raise
        except (UnicodeError, ValueError, OSError):
            raise AIServiceError("ChatGPT 登录信息损坏或无法解密，请重新连接。", "secure_storage_unavailable") from None
        if not isinstance(contents, dict):
            raise AIServiceError("ChatGPT 登录信息格式不正确。", "secure_storage_unavailable")
        return contents

    def _save(self, contents: Mapping[str, Any]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(contents, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self._protector.protect(payload)
        fd, temp_name = tempfile.mkstemp(prefix="chatgpt-", suffix=".tmp", dir=self.home)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self._file)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise

    @staticmethod
    def _safe_status(contents: Mapping[str, Any], pending: bool) -> dict[str, Any]:
        token = contents.get("access_token")
        refresh = contents.get("refresh_token")
        scopes = contents.get("scopes") or []
        expires = contents.get("expires_at")
        return {
            "connected": bool(token and refresh),
            "sharing": bool(token and refresh and DIRECT_SCOPE in scopes),
            "email": contents.get("email") or None,
            "name": contents.get("name") or None,
            "account": contents.get("email") or contents.get("name") or None,
            "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat() if isinstance(expires, (int, float)) else None,
            "pending": pending,
            "can_reauthorize": bool(contents.get("client_id")),
        }

    def status(self) -> dict[str, Any]:
        with self._storage_lock():
            return self._safe_status(self._load(), self._pending is not None)

    def begin(self, redirect_uri: str) -> str:
        parsed = urlparse(redirect_uri)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not port or parsed.path != "/auth/callback" or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise AIServiceError("ChatGPT 登录回调必须使用本机指定地址。", "invalid_redirect_uri")
        with self._storage_lock():
            contents = self._load()
            if not contents.get("host_id"):
                contents["host_id"] = f"urn:uuid:{uuid.uuid4()}"
                self._save(contents)
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            client_id = contents.get("client_id") or "dynamic_agent_client"
            self._pending = {
                "state": state, "nonce": nonce, "verifier": verifier,
                "redirect_uri": redirect_uri, "client_id": client_id,
                "subject": contents.get("subject"), "expires_at": time.time() + 600,
            }
            params = {
                "client_id": client_id,
                "ext_agent_host_id": contents["host_id"],
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "resource": RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
            if client_id == "dynamic_agent_client":
                params["agent_name_hint"] = APP_NAME
            elif contents.get("email"):
                # The authorize URL is returned to the local browser.  Avoid
                # putting a retained ID token in that browser-visible URL.
                params["login_hint"] = contents["email"]
            return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def _verify_id_token(self, token: str, client_id: str, nonce: str) -> dict[str, Any]:
        discovery = _json_request(DISCOVERY_URL)
        if discovery.get("issuer") != AUTHORITY:
            raise AIServiceError("ChatGPT 身份服务校验失败。", "invalid_issuer")
        jwks_uri = discovery.get("jwks_uri")
        parsed = urlparse(str(jwks_uri))
        if parsed.scheme != "https" or parsed.hostname != "auth.openai.com" or parsed.username or parsed.password or parsed.port:
            raise AIServiceError("ChatGPT 签名密钥地址不可信。", "invalid_jwks_uri")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError("Unsupported ID token header")
            jwks = _json_request(str(jwks_uri)).get("keys", [])
            key_record = next((key for key in jwks if key.get("kid") == header["kid"] and key.get("kty") == "RSA"), None)
            if key_record is None:
                raise ValueError("Unrecognized signing key")
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_record)
            claims = jwt.decode(
                token, public_key, algorithms=["RS256"], audience=client_id,
                issuer=AUTHORITY, leeway=5,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
            if not secrets.compare_digest(str(claims["nonce"]), nonce) or not claims.get("sub"):
                raise ValueError("Invalid nonce or subject")
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            raise AIServiceError("ChatGPT 身份验证失败，请重新登录。", "invalid_id_token") from None
        return claims

    def complete(self, query_params: Mapping[str, str]) -> dict[str, Any]:
        with self._storage_lock():
            pending = self._pending
            if not pending or time.time() >= pending["expires_at"]:
                self._pending = None
                raise AIServiceError("登录请求已过期，请重新点击登录。", "expired_oauth_state")
            returned_state = query_params.get("state") or ""
            if not secrets.compare_digest(returned_state, pending["state"]):
                raise AIServiceError("登录回调校验失败，请重新点击登录。", "invalid_oauth_state")
            self._pending = None  # The authorization code is single-use.
            if query_params.get("error"):
                raise AIServiceError("ChatGPT 授权已取消，未连接 AI。", "access_denied")
            code = query_params.get("code")
            if not code:
                raise AIServiceError("ChatGPT 登录未返回授权码，请重试。", "missing_oauth_code")
            issued_id = query_params.get("client_id")
            if pending["client_id"] == "dynamic_agent_client":
                if not issued_id or issued_id == "dynamic_agent_client":
                    raise AIServiceError("ChatGPT 注册未完成，请重新登录。", "missing_client_id")
                client_id = issued_id
            else:
                client_id = pending["client_id"]
                if issued_id and issued_id != client_id:
                    raise AIServiceError("ChatGPT 注册信息不一致，请重新登录。", "client_id_mismatch")
            try:
                tokens = _json_request(TOKEN_URL, form={
                    "grant_type": "authorization_code", "client_id": client_id,
                    "code": code, "code_verifier": pending["verifier"],
                    "redirect_uri": pending["redirect_uri"], "resource": RESOURCE,
                })
            except AIServiceError as exc:
                # OpenAI can issue the dynamic client successfully but reject
                # an expired/reused code.  Reuse that issued ID on the next
                # attempt instead of registering yet another client.
                if exc.code == "invalid_grant" and pending["client_id"] == "dynamic_agent_client":
                    contents = self._load()
                    contents["client_id"] = client_id
                    self._save(contents)
                raise
            id_token = tokens.get("id_token")
            if not isinstance(id_token, str):
                raise AIServiceError("ChatGPT 未返回身份信息，请重试。", "missing_id_token")
            claims = self._verify_id_token(id_token, client_id, pending["nonce"])
            if pending.get("subject") and pending["subject"] != claims["sub"]:
                raise AIServiceError("登录了不同的 ChatGPT 账号，请重新连接。", "account_mismatch")
            access = tokens.get("access_token")
            refresh = tokens.get("refresh_token")
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise AIServiceError("ChatGPT 未返回可续期的授权信息，请重试。", "missing_tokens")
            if tokens.get("token_type", "Bearer").lower() != "bearer":
                raise AIServiceError("ChatGPT 返回了不支持的授权类型。", "unsupported_token_type")
            try:
                expires_in = int(tokens["expires_in"])
                if expires_in <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise AIServiceError("ChatGPT 授权期限无效，请重试。", "invalid_token_expiry") from None
            contents = self._load()
            contents.update({
                "client_id": client_id, "subject": claims["sub"],
                "email": claims.get("email"), "name": claims.get("name"),
                "id_token": id_token, "access_token": access, "refresh_token": refresh,
                "scopes": str(tokens.get("scope", "")).split(),
                "expires_at": time.time() + expires_in,
            })
            self._save(contents)
            return self._safe_status(contents, False)

    def access_token(self) -> str:
        with self._storage_lock():
            contents = self._load()
            if not contents.get("access_token") or not contents.get("refresh_token"):
                raise AIServiceError("请先使用 ChatGPT 登录。", "not_connected")
            if DIRECT_SCOPE not in contents.get("scopes", []):
                raise AIServiceError("尚未授权使用 ChatGPT 订阅额度，请重新登录并授权。", "plan_permission_missing")
            if contents.get("expires_at", 0) > time.time() + 90:
                return str(contents["access_token"])
            try:
                updated = _json_request(TOKEN_URL, form={
                    "grant_type": "refresh_token", "client_id": contents["client_id"],
                    "refresh_token": contents["refresh_token"], "resource": RESOURCE,
                })
            except AIServiceError as exc:
                if exc.code in {"invalid_grant", "invalid_refresh_token", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused", "token_expired"}:
                    for key in ("access_token", "refresh_token", "id_token", "expires_at"):
                        contents.pop(key, None)
                    self._save(contents)
                raise
            access = updated.get("access_token")
            if not isinstance(access, str) or not access:
                raise AIServiceError("ChatGPT 续期失败，请重新登录。", "invalid_refresh_response")
            contents["access_token"] = access
            if updated.get("refresh_token"):
                contents["refresh_token"] = updated["refresh_token"]
            if updated.get("scope") is not None:
                contents["scopes"] = str(updated["scope"]).split()
            if DIRECT_SCOPE not in contents.get("scopes", []):
                contents["expires_at"] = 0
                self._save(contents)
                raise AIServiceError("ChatGPT 订阅额度授权已失效，请重新登录。", "plan_permission_missing")
            try:
                expires_in = int(updated["expires_in"])
                if expires_in <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise AIServiceError("ChatGPT 续期信息不完整，请重新登录。", "invalid_refresh_response") from None
            contents["expires_at"] = time.time() + expires_in
            self._save(contents)
            return access

    def disconnect(self) -> dict[str, Any]:
        with self._storage_lock():
            contents = self._load()
            confirmed = True
            warning = None
            refresh = contents.get("refresh_token")
            if refresh and contents.get("client_id"):
                try:
                    discovery = _json_request(DISCOVERY_URL)
                    if discovery.get("issuer") != AUTHORITY:
                        raise AIServiceError("ChatGPT 身份服务校验失败。", "invalid_issuer")
                    endpoint = discovery.get("revocation_endpoint")
                    parsed = urlparse(str(endpoint))
                    if parsed.scheme != "https" or parsed.hostname != "auth.openai.com" or parsed.port:
                        raise AIServiceError("ChatGPT 注销地址不可信。", "invalid_revocation_uri")
                    data = urlencode({"token": refresh, "token_type_hint": "refresh_token", "client_id": contents["client_id"]}).encode("utf-8")
                    request = Request(str(endpoint), data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
                    with urlopen(request, timeout=_TIMEOUT):
                        pass
                except (AIServiceError, HTTPError, URLError, OSError, TimeoutError):
                    confirmed = False
                    warning = "本机已断开连接，但网络注销未确认。请到 ChatGPT 设置中检查此应用的访问权限。"
            for key in ("access_token", "refresh_token", "id_token", "expires_at", "scopes"):
                contents.pop(key, None)
            self._pending = None
            if contents:
                self._save(contents)
            result = self._safe_status(contents, False)
            result.update({"revocation_confirmed": confirmed, "warning": warning})
            return result
