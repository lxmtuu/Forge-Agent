"""OpenRouter chat-completions client with SSE streaming + OpenAI-style tool calling."""
import json
from typing import AsyncIterator

import httpx

from . import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


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
        "model": model or config.get_model(),
        "messages": messages,
        "stream": True,
        "temperature": temperature,
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
