"""OpenRouter chat-completions client with SSE streaming + OpenAI-style tool calling."""
import json
from collections.abc import AsyncIterator

import httpx

from . import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GOOGLE_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
PROVIDER_PREFIXES = ("openrouter", "google", "custom")


def split_model_id(model: str | None = None) -> tuple[str, str]:
    """Tách provider khỏi model ID; ID legacy giữ semantics của active config."""
    raw = (model or config.get_model() or config.FALLBACK_MODEL).strip()
    prefix, sep, bare = raw.partition(":")
    if sep and prefix.lower() in PROVIDER_PREFIXES and bare:
        return prefix.lower(), bare
    return config.get_provider(), raw


def qualify_model(model: str | None, provider: str | None = None) -> str:
    raw = (model or config.get_model() or config.FALLBACK_MODEL).strip()
    detected, _ = split_model_id(raw)
    prefix, sep, _ = raw.partition(":")
    if sep and prefix.lower() in PROVIDER_PREFIXES:
        return raw
    return f"{provider or detected}:{raw}"


def resolve_model(model: str | None = None) -> str:
    """Model cuối cùng sẽ gọi: config/env + hậu tố :online khi bật web_search.

    Web search của OpenRouter (~$4/1000 kết quả, mặc định 5 kết quả/lượt):
    suffix ":online" = shorthand của plugins:[{id:"web"}].
    """
    from fnmatch import fnmatch
    raw = (model or config.get_model() or config.FALLBACK_MODEL).strip()
    provider, m = split_model_id(raw)
    cfg = config.load_config()
    if cfg.get("web_search") and provider == "openrouter" and not m.endswith(":online"):
        bypass = cfg.get("web_search_skip") or []
        if not any(fnmatch(m.lower(), str(p).lower()) for p in bypass):
            m = m + ":online"
    return f"{provider}:{m}" if raw.partition(":")[0].lower() in PROVIDER_PREFIXES and raw.partition(":")[1] else m


class LLMError(Exception):
    pass


def _provider_label(provider: str | None = None) -> str:
    return {"google": "Google Gemini", "custom": "Custom provider"}.get(
        provider or config.get_provider(), "OpenRouter")


def _redact_error(text: str, headers: dict) -> str:
    """Không để provider echo Authorization/API key vào SSE, response hoặc log."""
    out = str(text)
    for name, value in headers.items():
        if name.lower() not in {"authorization", "x-goog-api-key"}:
            continue
        raw = str(value)
        candidates = {raw, raw.removeprefix("Bearer ")}
        for secret in candidates:
            if len(secret) >= 4:
                out = out.replace(secret, "<redacted>")
    return out


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter attribution headers (optional but recommended)
        "HTTP-Referer": "https://github.com/forge-agent",
        "X-Title": "Forge Agent",
    }


def resolve_sub_model(model_str: str | None, parent_model: str | None = None) -> str | None:
    """Alias model cho sub-agent (chuẩn Claude Code — MULTI_MODEL.md §2.1).

    '' / inherit / same → None (thừa kế model phiên cha)
    cheap / free / fast → config.model_roles.cheap  (mặc định: openrouter/free)
    strong / best       → config.model_roles.strong (mặc định: model cha hoặc config)
    còn lại             → ID đầy đủ, giữ nguyên
    """
    raw = (model_str or "inherit").strip()
    low = raw.lower()
    if low in ("", "inherit", "same", "parent"):
        return None
    cfg = config.load_config()
    roles = cfg.get("model_roles") or {}
    if low in ("cheap", "free", "fast", "low"):
        return ((roles.get("cheap") or "").strip()
                or ("openrouter/free" if config.get_provider() == "openrouter"
                    else (parent_model or config.get_model())))
    if low in ("strong", "best", "powerful", "high"):
        return ((roles.get("strong") or "").strip()
                or (parent_model or "").strip()
                or config.get_model())
    return raw


_FALLBACK_MARKS = ("402", "429", "HTTP 500", "HTTP 502", "HTTP 503")


def pick_fallback(model: str | None, err: Exception) -> str | None:
    """Availability fallback (tách bạch khỏi quality routing): model lỗi 402/429/5xx
    → model dự phòng đầu tiên trong config.model_fallbacks khác model hiện tại."""
    msg = str(err)
    if not any(mk in msg for mk in _FALLBACK_MARKS):
        return None
    cfg = config.load_config()
    provider, current = split_model_id(model or config.get_model())
    fallbacks = cfg.get("model_fallbacks")
    if fallbacks is None:
        fallbacks = ["openrouter/free"] if provider == "openrouter" else []
    cur = current.removesuffix(":online").strip().lower()
    prefixed = bool(model and model.partition(":")[0].lower() in PROVIDER_PREFIXES
                    and model.partition(":")[1])
    for item in fallbacks:
        fb = str(item).strip()
        if not fb:
            continue
        fb_provider, fb_model = split_model_id(fb)
        if ":" not in fb.partition("/")[0]:
            fb_provider = provider
        if fb_model.removesuffix(":online").strip().lower() != cur:
            return qualify_model(fb, fb_provider) if prefixed else fb
    return None


def _endpoint(api_key: str | None, provider: str | None = None) -> tuple[str, dict]:
    """Chọn endpoint + headers: base URL tuỳ chỉnh (Ollama/LM Studio/vLLM…) hoặc OpenRouter.

    - Base URL custom: key TÙY CHỌN (lấy custom_api_key nếu có — Ollama không cần).
    - OpenRouter: bắt buộc key.
    """
    provider = provider or config.get_provider()
    if provider == "google":
        key = api_key or config.get_google_api_key()
        if not key:
            raise LLMError(
                "Chưa cấu hình Google API key. Chạy `python scripts/setup_keys.py` "
                "trong terminal (nhập ẩn) hoặc đặt GOOGLE_API_KEY cho tiến trình server."
            )
        return GOOGLE_OPENAI_URL, {
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        }
    base = config.get_base_url()
    if provider == "custom":
        if not base:
            raise LLMError("Provider=custom nhưng thiếu custom_base_url — chạy scripts/setup_keys.py.")
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/forge-agent",
            "X-Title": "Forge Agent",
        }
        ck = api_key or config.get_custom_api_key()
        if ck:
            headers["Authorization"] = f"Bearer {ck}"
        return base + "/chat/completions", headers
    key = api_key or config.get_api_key()
    if not key:
        raise LLMError(
            "Chưa cấu hình API key OpenRouter. Đặt biến môi trường OPENROUTER_API_KEY "
            "hoặc nhập key trong phần Settings — hoặc đặt 'Base URL tuỳ chỉnh' "
            "(vd http://localhost:11434/v1 cho Ollama) để dùng model cục bộ."
        )
    return OPENROUTER_URL, _headers(key)


async def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[dict]:
    """Yield events:
      {"type": "reasoning", "text": str}
      {"type": "delta",     "text": str}
      {"type": "tool_calls","tool_calls": [normalized openai tool_call dicts]}
      {"type": "finish",    "reason": str|None}
      {"type": "usage",     "usage": dict}
    Raises LLMError on HTTP/network failures.
    """
    provider, _ = split_model_id(model or config.get_model())
    url, headers = _endpoint(api_key, provider)
    resolved = resolve_model(model or config.get_model())
    resolved_provider, resolved_model = split_model_id(resolved)
    payload: dict = {
        "model": (resolved_model.removeprefix("google/").removesuffix(":online")
                  if resolved_provider == "google" else resolved_model),
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": config.get_max_tokens(),
    }
    effort = config.get_reasoning_effort()
    if effort and resolved_provider == "openrouter":
        # D3 — chỉ gửi qua OpenRouter (server OpenAI-compat lạ có thể từ chối field lạ)
        payload["reasoning"] = {"effort": effort}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    acc_tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage = None

    timeout = httpx.Timeout(180.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST", url, headers=headers, json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = _redact_error(
                        (await resp.aread()).decode("utf-8", "replace")[:2000], headers)
                    label = _provider_label(provider)
                    if resp.status_code == 401:
                        if resolved_provider == "openrouter":
                            raise LLMError(
                                "OpenRouter 401 — API key KHÔNG HỢP LỆ (\"User not found\" = key sai, "
                                "thiếu ký tự hoặc đã bị xóa). Hãy tạo key mới tại https://openrouter.ai/keys, "
                                "copy ĐỦ toàn bộ chuỗi sk-or-v1-... rồi nhập lại bằng secure setup. "
                                f"Chi tiết từ OpenRouter: {body[:300]}")
                        raise LLMError(
                            f"{label} 401 — API key không hợp lệ hoặc thiếu quyền. "
                            "Kiểm tra key bằng python scripts/setup_keys.py --check. "
                            f"Chi tiết đã redact: {body[:300]}")
                    if resp.status_code == 402:
                        if resolved_provider == "openrouter":
                            raise LLMError(
                                "OpenRouter 402 — Key hợp lệ nhưng tài khoản KHÔNG ĐỦ CREDIT cho model trả phí này. "
                                "3 cách xử lý: (1) ⚙ Cài đặt → lọc model 'free' → chọn model miễn phí "
                                "(vd: openrouter/free, cohere/north-mini-code:free); "
                                "(2) nạp credit tại https://openrouter.ai/credits nếu muốn dùng Claude/GPT; "
                                "(3) giảm 'Max tokens' trong ⚙ Cài đặt để giảm số credit cần đặt cọc. "
                                f"Chi tiết: {body[:250]}")
                        raise LLMError(f"{label} 402 — hết hạn mức/credit. Chi tiết đã redact: {body[:250]}")
                    if resp.status_code == 501:
                        raise LLMError(
                            f"{label} HTTP 501 — provider/model không hỗ trợ request hiện tại. "
                            "Nguyên nhân thường gặp: tool calling, streaming hoặc reasoning chưa được "
                            "model/endpoint hỗ trợ. Hãy chọn model khác cho Agent; có thể thử chế độ "
                            "Direct (không tools) hoặc tắt Effort suy luận để chẩn đoán. "
                            f"Chi tiết đã redact: {body[:500]}")
                    raise LLMError(f"{label} HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        raise LLMError(f"{_provider_label(provider)} error: {_redact_error(str(obj['error']), headers)}")
                    if obj.get("usage"):
                        usage = obj["usage"]
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                    if reasoning:
                        yield {"type": "reasoning", "text": reasoning}
                    content = delta.get("content")
                    if content:
                        yield {"type": "delta", "text": content}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = acc_tool_calls.setdefault(
                            idx,
                            {"id": "", "type": "function",
                             "function": {"name": "", "arguments": ""}},
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = (
                                slot["function"]["name"] + fn["name"]
                                if slot["function"]["name"] else fn["name"]
                            )
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
        except httpx.HTTPError as e:
            raise LLMError(f"Lỗi kết nối {_provider_label(provider)}: {e}") from e

    if acc_tool_calls:
        tool_calls = [acc_tool_calls[i] for i in sorted(acc_tool_calls)]
        for tc in tool_calls:
            if not tc["id"]:
                tc["id"] = "call_" + str(abs(hash(tc["function"]["name"])) % 10**10)
        yield {"type": "tool_calls", "tool_calls": tool_calls}
    yield {"type": "finish", "reason": finish_reason}
    if usage:
        yield {"type": "usage", "usage": usage}


def build_assistant_message(content: str | None, tool_calls: list[dict] | None) -> dict:
    msg: dict = {"role": "assistant"}
    msg["content"] = content if content else None
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


async def check_key(api_key: str | None = None, provider: str | None = None) -> dict:
    """Verify key theo provider; key chỉ đi trong header, không vào URL/log."""
    provider = provider or config.get_provider()
    if provider == "google":
        key = api_key or config.get_google_api_key()
        if not key:
            return {"valid": False, "error": "Chưa có Google API key",
                    "hint": "Chạy python scripts/setup_keys.py hoặc tạo key tại aistudio.google.com/api-keys."}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(GOOGLE_MODELS_URL, headers={"x-goog-api-key": key})
        except httpx.HTTPError as e:
            return {"valid": False, "error": f"Lỗi kết nối Google AI Studio: {e}", "hint": ""}
        if r.status_code == 200:
            return {"valid": True, "label": "Google Gemini API", "usage": None,
                    "limit": None, "is_free_tier": None}
        return {"valid": False, "error": f"Google từ chối key (HTTP {r.status_code})",
                "hint": "Kiểm tra lại key tại https://aistudio.google.com/api-keys và hạn mức Free Tier."}
    key = api_key or config.get_api_key()
    if not key:
        return {"valid": False, "error": "Chưa có key nào được cấu hình",
                "hint": "Tạo key tại https://openrouter.ai/keys rồi dán vào Cài đặt."}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://openrouter.ai/api/v1/auth/key",
                            headers=_headers(key))
    except httpx.HTTPError as e:
        return {"valid": False, "error": f"Lỗi kết nối OpenRouter: {e}", "hint": ""}
    if r.status_code == 200:
        d = r.json().get("data", {}) or {}
        return {
            "valid": True,
            "label": d.get("label") or "(không tên)",
            "usage": d.get("usage"),       # USD đã dùng
            "limit": d.get("limit"),       # None = không giới hạn / free tier
            "is_free_tier": d.get("is_free_tier"),
        }
    try:
        msg = _redact_error((r.json().get("error") or {}).get("message")                             or f"HTTP {r.status_code}", _headers(key))
    except Exception:
        msg = f"HTTP {r.status_code}"
    hint = ""
    if "User not found" in msg:
        hint = ("Key KHÔNG tồn tại trên OpenRouter. Thường do: (1) copy thiếu/thừa ký tự — "
                "key dạng sk-or-v1- gồm 71 ký tự, phải copy ĐỦ toàn bộ; (2) key đã bị xóa; "
                "(3) dán nhầm key của dịch vụ khác. Hãy tạo key mới tại openrouter.ai/keys, "
                "dùng nút Copy trên trang đó và dán thẳng vào đây.")
    elif r.status_code == 402:
        hint = "Key hợp lệ nhưng tài khoản hết credit — nạp thêm tại openrouter.ai/credits."
    elif r.status_code == 429:
        hint = "Key hợp lệ nhưng đang bị giới hạn tốc độ — chờ chút rồi thử lại."
    return {"valid": False, "error": msg, "hint": hint}
