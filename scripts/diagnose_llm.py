"""Read-only provider streaming diagnostic; never prints API keys or writes session data.

Run from the Forge project root (Windows venv):
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_llm.py --provider google
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_llm.py --provider openrouter

The prompt is synthetic. Output contains HTTP metadata and a redacted, truncated
response body so streaming/empty-response failures can be diagnosed without DevTools.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from engine import llm

MAX_BODY_CHARS = 6000


def redacted_body(raw: str, headers: dict[str, str]) -> str:
    # Redact exact configured credentials even if a provider echoes them. Also
    # cover common bearer/key spellings that might occur in an error payload.
    text = llm._redact_error(raw, headers)
    for value in headers.values():
        secret = str(value).removeprefix("Bearer ")
        if len(secret) >= 4:
            text = text.replace(secret, "<redacted>")
    return text[:MAX_BODY_CHARS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("openrouter", "google"))
    parser.add_argument("--model", help="Optional bare model ID; defaults to a small diagnostic model")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    provider = args.provider
    model = args.model or ("openrouter/free" if provider == "openrouter" else "gemini-3.8-flash")
    if ":" in model.partition("/")[0]:
        requested_provider, model = llm.split_model_id(model)
        if requested_provider != provider:
            parser.error("--model prefix must match --provider")
    try:
        url, headers = llm._endpoint(None, provider)
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary must redact every failure
        print(f"SETUP ERROR: {exc}")
        return 1

    payload = {
        "model": model.removeprefix("google/") if provider == "google" else model,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "stream": True,
        "temperature": 0,
        "max_tokens": 64,
    }
    print("READ-ONLY LLM DIAGNOSTIC — no tools, no session writes")
    print(f"Provider: {provider}")
    print(f"Model: {payload['model']}")
    print(f"Endpoint: {url}")
    print("Streaming: true · max_tokens: 64")
    started = time.monotonic()
    try:
        timeout = httpx.Timeout(max(args.timeout, 5.0), connect=15.0)
        with (
            httpx.Client(timeout=timeout) as client,
            client.stream("POST", url, headers=headers, json=payload) as response,
        ):
            print(f"HTTP: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type', '(missing)')}")
            chunks: list[str] = []
            size = 0
            for text in response.iter_text():
                chunks.append(text)
                size += len(text)
                if size >= MAX_BODY_CHARS * 2:
                    break
            raw = "".join(chunks)
            print(f"Elapsed: {time.monotonic() - started:.1f}s · received chars: {len(raw)}")
            print("----- REDACTED RESPONSE BEGIN -----")
            print(redacted_body(raw, headers) or "(EMPTY RESPONSE BODY)")
            print("------ REDACTED RESPONSE END ------")
            if response.status_code != 200:
                return 2
            # A successful OpenAI-compatible stream normally has at least one
            # data frame and finishes with [DONE]. Do not hide deviations.
            has_data = any(line.lstrip().startswith("data:") for line in raw.splitlines())
            has_done = "data: [DONE]" in raw
            print(f"SSE data frame: {'YES' if has_data else 'NO'} · [DONE]: {'YES' if has_done else 'NO'}")
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get("error"):
                print("Provider returned a JSON error object.")
                return 3
            return 0 if has_data else 4
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary must redact every failure
        safe = llm._redact_error(f"{type(exc).__name__}: {exc}", headers)
        print(f"NETWORK/CLIENT ERROR: {safe}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
