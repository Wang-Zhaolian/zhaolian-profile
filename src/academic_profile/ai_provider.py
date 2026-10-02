"""Small model-provider interface with a ChatGPT-plan-only implementation."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .chatgpt_auth import AIServiceError, ChatGPTAuth, RESOURCE


class AIProvider(Protocol):
    def list_models(self) -> list[dict[str, str]]: ...

    def complete_text(self, model: str, instructions: str, input_text: str) -> str: ...

    def complete_content(self, model: str, instructions: str, content: list[dict[str, Any]]) -> str: ...


def _response_error(error: Any, *, status: int | None = None, request_id: str | None = None) -> AIServiceError:
    reported_code = error.get("code") if isinstance(error, dict) else None
    code = str(reported_code or (f"http_{status}" if status else "response_failed"))
    messages = {
        "subscription_sharing_user_not_eligible": "此 ChatGPT 账号或工作区暂不符合订阅额度使用条件。",
        "subscription_sharing_usage_limit_exceeded": "ChatGPT 使用额度已达到当前上限，请到 ChatGPT 设置的 Usage 页面查看。",
        "subscription_sharing_usage_unavailable": "暂时无法核验 ChatGPT 用量，请稍后重试。",
        "subscription_sharing_unsupported_capability": "所选模型暂不支持这项请求，请换一个可用模型。",
        "subscription_sharing_route_not_supported": "当前 ChatGPT 订阅接口不支持此请求。",
        "subscription_sharing_invalid_user": "ChatGPT 账号验证失败，请重新登录。",
        "chatpass_v2_scope_not_authorized": "当前授权未包含 ChatGPT 订阅额度，请重新登录。",
        "chatpass_v2_invalid_authorization_context": "ChatGPT 授权信息无效，请重新登录。",
        "subscription_sharing_user_unavailable": "ChatGPT 账号信息暂不可用，请稍后重试。",
    }
    if code in messages:
        message = messages[code]
    elif status == 401:
        message = "ChatGPT 登录已失效，请重新登录。"
    elif status == 403:
        message = "当前账号、地区或策略不允许使用 ChatGPT 订阅功能。"
    elif status == 429:
        message = "ChatGPT 使用额度或请求频率达到上限，请稍后再试。"
    elif status == 413 or code in {"context_length_exceeded", "request_too_large"}:
        message = "本次内容超过 ChatGPT 的单次输入限制。请减少所选附件，或拆分文件后分批整理；本机素材不会丢失。"
    elif status and status >= 500:
        message = "ChatGPT 服务暂时不可用，请稍后重试。"
    else:
        message = "ChatGPT 请求未完成，请重试。"
    return AIServiceError(message, code, status=status, request_id=request_id)


def _http_error(exc: HTTPError) -> AIServiceError:
    request_id = exc.headers.get("x-request-id") or exc.headers.get("openai-request-id")
    try:
        payload = json.loads(exc.read(65536).decode("utf-8"))
    except (ValueError, UnicodeError, OSError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    return _response_error(error, status=exc.code, request_id=request_id)


class ChatGPTProvider:
    """Use only OAuth plan credentials against the documented public endpoint."""

    def __init__(self, auth: ChatGPTAuth) -> None:
        self.auth = auth

    def list_models(self) -> list[dict[str, str]]:
        token = self.auth.access_token()
        request = Request(
            f"{RESOURCE}/models",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise _http_error(exc) from None
        except (URLError, OSError, TimeoutError):
            raise AIServiceError("无法连接 ChatGPT，请检查网络后重试。", "offline") from None
        except (ValueError, UnicodeError):
            raise AIServiceError("ChatGPT 模型列表格式不正确。", "invalid_model_list") from None
        rows = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise AIServiceError("ChatGPT 未返回可用模型列表。", "invalid_model_list")
        return [
            {"slug": row["slug"], "display_name": row.get("display_name") or row["slug"]}
            for row in rows
            if isinstance(row, dict)
            and row.get("visibility") == "list"
            and isinstance(row.get("slug"), str)
            and row["slug"]
        ]

    def complete_text(self, model: str, instructions: str, input_text: str) -> str:
        if not isinstance(input_text, str) or not input_text.strip():
            raise AIServiceError("请先输入要整理的文字。", "missing_input")
        return self.complete_content(model, instructions, [{"type": "input_text", "text": input_text}])

    def complete_content(self, model: str, instructions: str, content: list[dict[str, Any]]) -> str:
        if not isinstance(model, str) or not model.strip():
            raise AIServiceError("请选择一个 ChatGPT 模型。", "missing_model")
        if not isinstance(content, list) or not content:
            raise AIServiceError("请先输入文字或选择文件。", "missing_input")
        token = self.auth.access_token()
        body = {
            "model": model,
            "instructions": instructions,
            "input": [{
                "role": "user",
                "content": content[0]["text"]
                if len(content) == 1 and content[0].get("type") == "input_text"
                else content,
            }],
            "store": False,
            "stream": True,
        }
        request = Request(
            f"{RESOURCE}/responses",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        deltas: list[str] = []
        completed = False

        def process(lines: list[str]) -> None:
            nonlocal completed
            if not lines:
                return
            data = "\n".join(lines)
            if data == "[DONE]":
                return
            try:
                event = json.loads(data)
            except ValueError:
                raise AIServiceError("ChatGPT 返回了无法读取的流式数据。", "invalid_stream") from None
            if not isinstance(event, dict):
                raise AIServiceError("ChatGPT 返回了无法读取的流式数据。", "invalid_stream")
            event_type = event.get("type")
            if event_type == "response.output_text.delta" and isinstance(event.get("delta"), str):
                deltas.append(event["delta"])
            elif event_type in ("response.failed", "response.incomplete", "error"):
                details = event.get("response") if isinstance(event.get("response"), dict) else {}
                error = details.get("error") or event.get("error")
                if event_type == "response.incomplete" and not error:
                    error = {"code": "response_incomplete"}
                raise _response_error(error)
            elif event_type == "response.completed":
                completed = True
                if not deltas:
                    response = event.get("response")
                    if isinstance(response, dict):
                        for item in response.get("output", []):
                            if isinstance(item, dict):
                                for part in item.get("content", []):
                                    if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                                        deltas.append(part["text"])

        try:
            with urlopen(request, timeout=180) as response:
                data_lines: list[str] = []
                for raw in response:
                    try:
                        line = raw.decode("utf-8").rstrip("\r\n")
                    except UnicodeError:
                        raise AIServiceError("ChatGPT 返回的文字编码不正确。", "invalid_stream") from None
                    if not line:
                        process(data_lines)
                        data_lines = []
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" "))
                process(data_lines)
        except HTTPError as exc:
            raise _http_error(exc) from None
        except (URLError, OSError, TimeoutError):
            raise AIServiceError("ChatGPT 连接中断，请检查网络后重试。", "offline") from None
        if not completed:
            raise AIServiceError("ChatGPT 回复未完整结束，请重试。", "stream_interrupted")
        result = "".join(deltas)
        if not result.strip():
            raise AIServiceError("ChatGPT 未返回可用的文字，请重试。", "empty_response")
        return result
