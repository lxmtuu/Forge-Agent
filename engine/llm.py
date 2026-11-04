"""OpenRouter chat-completions client with SSE streaming + OpenAI-style tool calling."""
import json
from typing import AsyncIterator

import httpx

from . import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def resolve_model(model: str | None = None) -> str:
    """Model cuối cùng sẽ gọi: config/env + hậu tố :online khi bật web_search.

    Web search của OpenRouter (~$4/1000 kết quả, mặc định 5 kết quả/lượt):
    suffix ":online" = shorthand của plugins:[{id:"web"}].
    """
    from fnmatch import fnmatch
    m = (model or config.get_model() or "").strip()
    if not m:
        m = config.FALLBACK_MODEL
    cfg = config.load_config()
    if cfg.get("web_search") and not m.endswith(":online"):
        bypass = cfg.get("web_search_skip") or []
        if not any(fnmatch(m.lower(), str(p).lower()) for p in bypass):
            m = m + ":online"
    return m


class LLMError(Exception):
    pass


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter attribution headers (optional but recommended)
        "HTTP-Referer": "https://github.com/forge-agent",
        "X-Title": "Forge Agent",
    }


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
    key = api_key or config.get_api_key()
    if not key:
        raise LLMError(
            "Chưa cấu hình API key OpenRouter. Đặt biến môi trường OPENROUTER_API_KEY "
            "hoặc nhập key trong phần Settings."
        )
    payload: dict = {
        "model": resolve_model(model or config.get_model()),
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": config.get_max_tokens(),
    }
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
                "POST", OPENROUTER_URL, headers=_headers(key), json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:2000]
                    if resp.status_code == 401:
                        raise LLMError(
                            "OpenRouter 401 — API key KHÔNG HỢP LỆ (\"User not found\" = key sai, "
                            "thiếu ký tự hoặc đã bị xóa). Hãy tạo key mới tại https://openrouter.ai/keys, "
                            "copy ĐỦ toàn bộ chuỗi sk-or-v1-... rồi dán lại vào ⚙ Cài đặt. "
                            f"Chi tiết từ OpenRouter: {body[:300]}")
                    if resp.status_code == 402:
                        raise LLMError(
                            "OpenRouter 402 — Key hợp lệ nhưng tài khoản KHÔNG ĐỦ CREDIT cho model trả phí này. "
                            "3 cách xử lý: (1) ⚙ Cài đặt → lọc model 'free' → chọn model miễn phí "
                            "(vd: openrouter/free, cohere/north-mini-code:free); "
                            "(2) nạp credit tại https://openrouter.ai/credits nếu muốn dùng Claude/GPT; "
                            "(3) giảm 'Max tokens' trong ⚙ Cài đặt để giảm số credit cần đặt cọc. "
                            f"Chi tiết: {body[:250]}")
                    raise LLMError(f"OpenRouter HTTP {resp.status_code}: {body}")
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
                        raise LLMError(f"OpenRouter error: {obj['error']}")
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
            raise LLMError(f"Lỗi kết nối OpenRouter: {e}") from e

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


async def check_key(api_key: str | None = None) -> dict:
    """Verify an OpenRouter key via GET /api/v1/auth/key."""
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
        msg = (r.json().get("error") or {}).get("message") or f"HTTP {r.status_code}"
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
