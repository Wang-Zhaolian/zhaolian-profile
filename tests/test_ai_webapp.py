from __future__ import annotations

import json
import shutil
from io import BytesIO
from pathlib import Path

import yaml

from academic_profile.chatgpt_auth import AIServiceError
from academic_profile.webapp import create_app


ROOT = Path(__file__).resolve().parents[1]


class FakeAuth:
    def __init__(self, *, sharing: bool = True) -> None:
        self.sharing = sharing
        self.last_redirect_uri = ""

    def begin(self, redirect_uri: str) -> str:
        self.last_redirect_uri = redirect_uri
        return "https://auth.openai.com/example"

    def complete(self, query_params):
        if query_params.get("error") == "access_denied":
            raise AIServiceError("ChatGPT 授权已取消，未连接 AI。", "access_denied")
        return self.status()

    def status(self):
        return {
            "connected": self.sharing,
            "sharing": self.sharing,
            "email": "student@example.org" if self.sharing else None,
            "expires_at": None,
        }

    def disconnect(self):
        self.sharing = False
        return self.status()


class FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.input_text = ""
        self.instructions = ""
        self.model = ""
        self.input_content = []

    def list_models(self):
        return [{"slug": "test-model", "display_name": "Test Model"}]

    def complete_text(self, model: str, instructions: str, input_text: str) -> str:
        self.model = model
        self.instructions = instructions
        self.input_text = input_text
        return self.response

    def complete_content(self, model: str, instructions: str, content: list[dict]) -> str:
        self.model = model
        self.instructions = instructions
        self.input_content = content
        self.input_text = json.dumps(content, ensure_ascii=False)
        return self.response


class QuotaProvider(FakeProvider):
    def complete_text(self, model: str, instructions: str, input_text: str) -> str:
        raise AIServiceError(
            "ChatGPT 使用额度已达到当前上限，请到 ChatGPT 设置的 Usage 页面查看。",
            "subscription_sharing_usage_limit_exceeded",
            status=429,
            request_id="req-test-123",
        )


def _client(home: Path, *, auth=None, provider=None):
    home.mkdir(parents=True)
    for directory in ("data", "schemas", "profiles", "templates"):
        shutil.copytree(ROOT / directory, home / directory)
    (home / "private").mkdir(parents=True)
    basics_path = home / "data" / "basics.yaml"
    basics = yaml.safe_load(basics_path.read_text(encoding="utf-8"))
    basics.update({
        "name_en": "Example Student", "name_zh": "", "headline_en": "",
        "headline_zh": "", "research_interests": ["Example topic"],
    })
    basics_path.write_text(yaml.safe_dump(basics, sort_keys=False, allow_unicode=True), encoding="utf-8")
    app = create_app(home, static_root=ROOT, ai_auth=auth, ai_provider=provider)
    return app.test_client(), app


def _post(client, url: str, payload: dict):
    return client.post(
        url,
        json=payload,
        headers={"X-Academic-Profile": "local-ui"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )


def test_ai_connect_status_and_callback_stay_local_and_token_free(tmp_path: Path) -> None:
    auth = FakeAuth()
    provider = FakeProvider('{"candidates":[]}')
    client, _ = _client(tmp_path / "home", auth=auth, provider=provider)

    connect = _post(client, "/api/ai/connect", {})
    assert connect.status_code == 200
    assert connect.get_json()["authorization_url"].startswith("https://auth.openai.com/")
    assert auth.last_redirect_uri == "http://127.0.0.1:52847/auth/callback"

    status = client.get("/api/ai/status").get_json()
    assert status["connected"] is True
    assert status["sharing"] is True
    assert not any("token" in key.lower() for key in status)

    callback = client.get("/auth/callback?code=example&state=example")
    assert callback.status_code == 303
    assert callback.headers["Location"] == "/"
    assert callback.headers["Cache-Control"] == "no-store"

    denied = client.get("/auth/callback?error=access_denied&state=example")
    assert denied.status_code == 400
    assert "授权已取消" in denied.get_data(as_text=True)
    assert "example" not in denied.get_data(as_text=True)


def test_ai_saves_note_locally_builds_private_safe_context_and_returns_review_candidates(tmp_path: Path) -> None:
    note_text = "I led a microscopy segmentation study at Example Lab from 2024-01 to 2025-06."
    proposal = {
        "candidates": [{
            "category": "research",
            "fields": {
                "title": "Microscopy Segmentation Study",
                "institution": "Example Lab",
                "start_date": "2024-01",
                "end_date": "2025-06",
                "status": "completed",
                "cv_bullets_en": ["Led a microscopy segmentation study."],
            },
            "source_excerpt": note_text,
        }]
    }
    auth = FakeAuth()
    provider = FakeProvider(json.dumps(proposal))
    home = tmp_path / "home"
    client, _ = _client(home, auth=auth, provider=provider)

    # These private fields are deliberately planted in the local repository.
    (home / "private" / "contact.yaml").write_text(
        "email: confidential@example.org\nlocation: +1 415 555 0100\n", encoding="utf-8"
    )
    research_path = home / "data" / "research.yaml"
    research_path.write_text(
        research_path.read_text(encoding="utf-8").replace(
            "records: []", "records:\n  - id: research_001\n    title: Existing Record\n    record_state: draft\n    evidence:\n      - C:\\\\private\\\\certificate.pdf\n"
        ),
        encoding="utf-8",
    )

    saved = _post(client, "/api/ai/notes", {"text": note_text})
    assert saved.status_code == 201
    note = saved.get_json()["note"]
    note_file = home / "private" / "ai_notes" / f"{note['id']}.json"
    assert note_file.exists()
    assert note_text in note_file.read_text(encoding="utf-8")
    assert client.get("/api/ai/notes").get_json()["notes"][0]["id"] == note["id"]
    assert client.get(f"/api/ai/notes/{note['id']}").get_json()["note"]["text"] == note_text

    result = _post(client, "/api/ai/proposals", {"note_id": note["id"], "model": "test-model"})
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["context_mode"] == "full"
    assert payload["records_count"] == 1
    assert payload["candidates"][0]["category"] == "research"
    assert payload["candidates"][0]["fields"]["status"] == "completed"
    assert "confidential@example.org" not in provider.input_text
    assert "415 555 0100" not in provider.input_text
    assert "certificate.pdf" not in provider.input_text
    assert "research_001" in provider.input_text
    assert "不得编造" in provider.instructions

    # Proposals are never written into YAML without the user accepting them.
    saved_records = (home / "data" / "research.yaml").read_text(encoding="utf-8")
    assert "Microscopy Segmentation Study" not in saved_records


def test_ai_proposals_require_subscription_permission_and_a_listed_model(tmp_path: Path) -> None:
    auth = FakeAuth(sharing=False)
    provider = FakeProvider('{"candidates":[]}')
    client, _ = _client(tmp_path / "home", auth=auth, provider=provider)

    missing_permission = _post(client, "/api/ai/proposals", {"note_id": "x"})
    assert missing_permission.status_code == 409
    assert provider.input_text == ""

    auth.sharing = True
    note = _post(client, "/api/ai/notes", {"text": "A confirmed research experience."}).get_json()["note"]
    invalid_model = _post(client, "/api/ai/proposals", {"note_id": note["id"], "model": "unknown"})
    assert invalid_model.status_code == 409
    assert provider.input_text == ""


def test_quota_exhaustion_disables_ai_until_user_reauthorizes(tmp_path: Path) -> None:
    auth = FakeAuth()
    provider = QuotaProvider('{"candidates":[]}')
    client, _ = _client(tmp_path / "home", auth=auth, provider=provider)
    note = _post(client, "/api/ai/notes", {"text": "A confirmed research experience."}).get_json()["note"]

    exhausted = _post(client, "/api/ai/proposals", {"note_id": note["id"], "model": "test-model"})
    assert exhausted.status_code == 429
    assert exhausted.get_json()["request_id"] == "req-test-123"

    status = client.get("/api/ai/status").get_json()
    assert status["connected"] is True
    assert status["sharing"] is False
    assert status["ai_blocked"] is True
    assert "额度" in status["error"]
    disabled = client.get("/api/ai/models")
    assert disabled.status_code == 403
    assert disabled.get_json()["code"] == "subscription_sharing_usage_limit_exceeded"

    # An explicit reauthorization attempt clears the in-memory block; no
    # alternative provider or automatic retry is used.
    reauthorize = _post(client, "/api/ai/connect", {})
    assert reauthorize.status_code == 200
    assert "ai_blocked" not in client.get("/api/ai/status").get_json()


def test_image_attachment_is_local_until_selected_for_ai(tmp_path: Path) -> None:
    auth = FakeAuth()
    provider = FakeProvider('{"candidates":[]}')
    home = tmp_path / "home"
    client, _ = _client(home, auth=auth, provider=provider)
    png = b"\x89PNG\r\n\x1a\n" + b"local-image-data"
    saved = client.post(
        "/api/ai/notes",
        data={"text": "这是我的海报经历", "files": (BytesIO(png), "poster.png")},
        headers={"X-Academic-Profile": "local-ui"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert saved.status_code == 201
    note = saved.get_json()["note"]
    attachment = note["attachments"][0]
    local_path = home / "private" / "ai_notes" / "attachments" / note["id"] / f"{attachment['id']}.png"
    assert local_path.read_bytes() == png
    assert not (home / "data" / "ai_notes").exists()
    downloaded = client.get(f"/api/ai/notes/{note['id']}/attachments/{attachment['id']}")
    assert downloaded.data == png

    result = _post(client, "/api/ai/proposals", {
        "note_id": note["id"], "model": "test-model", "attachment_ids": [attachment["id"]],
    })
    assert result.status_code == 200
    assert any(item.get("type") == "input_image" for item in provider.input_content)
    assert "poster.png" in provider.input_text
