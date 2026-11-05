"""v0.38.0 hotfix: visible provider errors + empty-completion fail-closed.

No real provider credentials or network calls. Run: python scripts/test_v0371.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v0371-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-FAKE-V0371-not-real"
os.environ.pop("FORGE_RELEASE_MODE", None)
PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as exc:  # noqa: BLE001 — test harness gom đủ lỗi
                FAIL.append((name, str(exc)))
                print(f"  ✗ {name}: {exc}", flush=True)
                traceback.print_exc(limit=4)
        return run
    return deco


async def run_with_events(events):
    from engine.agent import Agent
    from engine.models import router
    from engine.session import SessionStore

    store = SessionStore()
    session = store.create(model="openrouter:openrouter/free")
    original = Agent._stream_chat

    async def fake_stream(self, messages, tools=None, model=None, temperature=0.3):
        for event in events:
            yield event

    Agent._stream_chat = fake_stream
    try:
        agent = Agent(store, session.id, model=session.model, router=router)
        output = [event async for event in agent.send("chào", chat_mode="direct")]
    finally:
        Agent._stream_chat = original
    return output, store.get(session.id).messages


@check("T1 Version 0.38.0 nhất quán + diagnostic script có sẵn")
async def t1():
    for name in ("pyproject.toml", "engine/__init__.py", "engine/mcp.py", "engine/lsp.py", "server/main.py"):
        assert "0.38.0" in (ROOT / name).read_text(encoding="utf-8"), name
    diagnostic = (ROOT / "scripts/diagnose_llm.py").read_text(encoding="utf-8")
    assert "REDACTED RESPONSE" in diagnostic and "no session writes" in diagnostic
    assert "sk-or-v1-FAKE" not in diagnostic


@check("T2 Empty completion → SSE error actionable · không lưu assistant null")
async def t2():
    events, messages = await run_with_events([{"type": "finish", "reason": "stop"}])
    errors = [str(event.get("message", "")) for event in events if event.get("type") == "error"]
    assert errors and "rỗng" in errors[0].lower() and "finish=stop" in errors[0], events
    assert not any(event.get("type") == "assistant_message" for event in events), events
    assert [(message["role"], message.get("content")) for message in messages] == [("user", "chào")], messages


@check("T3 Completion bình thường vẫn stream + lưu assistant · không báo lỗi giả")
async def t3():
    events, messages = await run_with_events([
        {"type": "delta", "text": "OK"},
        {"type": "finish", "reason": "stop"},
    ])
    assert any(event.get("type") == "assistant_delta" and event.get("text") == "OK" for event in events)
    assert any(event.get("type") == "assistant_message" and event.get("content") == "OK" for event in events)
    assert not any(event.get("type") == "error" for event in events), events
    assert [(message["role"], message.get("content")) for message in messages] == [
        ("user", "chào"), ("assistant", "OK")], messages


@check("T4 Web giữ SSE error sau chat · chỉ reload timeline khi không có lỗi")
async def t4():
    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    assert "let streamHadError = false" in app
    assert "if (ev.type === 'error') streamHadError = true" in app
    assert "if (!streamHadError) await loadSession(sid)" in app
    diagnostic = (ROOT / "scripts/diagnose_llm.py").read_text(encoding="utf-8")
    assert "headers=headers" in diagnostic and "llm._redact_error" in diagnostic
    browser = (ROOT / "scripts/browser_v0371.cjs").read_text(encoding="utf-8")
    assert "mocked auth failure" in browser and "SSE error disappeared after reload" in browser
    assert "FORGE_BASE_URL" in browser


async def main():
    print(f"=== SUITE v0.38.0 Visible provider errors + empty completion — data tạm: {TMP} ===")
    for test in (t1, t2, t3, t4):
        await test()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
