"""v0.38.0: persisted Vietnamese/English Web UI and localized scripted demos.

No real provider credentials or network calls. Run: python scripts/test_v038.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v038-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
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


async def demo_output(language: str | None = None):
    from engine.agent import Agent, send_demo
    from engine.models import router
    from engine.session import SessionStore

    store = SessionStore()
    session = store.create(model="openrouter:openrouter/free")
    agent = Agent(store, session.id, model=session.model, router=router)
    kwargs = {} if language is None else {"language": language}
    events = [event async for event in send_demo(agent, "Create a hello script", **kwargs)]
    text = "\n".join(str(event.get("text") or event.get("content") or "") for event in events)
    return events, text, agent


@check("T1 Version 0.38.0 nhất quán + LanguageProvider được mount")
async def t1():
    for name in ("pyproject.toml", "engine/__init__.py", "engine/mcp.py", "engine/lsp.py", "server/main.py"):
        assert "0.38.0" in (ROOT / name).read_text(encoding="utf-8"), name
    i18n = (ROOT / "web/src/i18n.tsx").read_text(encoding="utf-8")
    main = (ROOT / "web/src/main.tsx").read_text(encoding="utf-8")
    settings = (ROOT / "web/src/components/SettingsModal.tsx").read_text(encoding="utf-8")
    login = (ROOT / "web/src/components/LoginScreen.tsx").read_text(encoding="utf-8")
    assert "forge-language" in i18n and "document.documentElement.lang" in i18n
    assert "<LanguageProvider>" in main
    assert "setLanguage('en')" in settings and "setLanguage('vi')" in settings
    assert "setLanguage('en')" in login and "setLanguage('vi')" in login


@check("T2 English demo: reasoning/final English · tools vẫn chạy thật")
async def t2():
    events, text, agent = await demo_output("en")
    assert "Demo mode: no API key" in text
    assert "Open the **Workspace** panel" in text
    assert "chế độ Demo" not in text and "Xong! ✅" not in text
    assert not any(event.get("type") == "error" for event in events), events
    assert any(event.get("type") == "tool_start" for event in events)
    assert (agent.workspace / "hello_forge.py").is_file()


@check("T3 Không truyền language → demo tiếng Việt như client cũ")
async def t3():
    events, text, agent = await demo_output()
    assert "chế độ Demo" in text and "Xong! ✅" in text
    assert "Open the **Workspace** panel" not in text
    assert not any(event.get("type") == "error" for event in events), events
    assert (agent.workspace / "hello_forge.py").is_file()


@check("T4 Chat/Batch/Battle nhận language · mặc định vi · Web truyền lựa chọn")
async def t4():
    from engine.agent import run_batch, run_battle, send_demo
    from server.main import BatchBody, BattleBody, ChatBody

    assert ChatBody(text="hello").language == "vi"
    assert BatchBody(prompts=["hello"]).language == "vi"
    assert BattleBody(prompt="hello").language == "vi"
    for fn in (run_batch, run_battle, send_demo):
        assert inspect.signature(fn).parameters["language"].default == "vi", fn
    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    api = (ROOT / "web/src/api.ts").read_text(encoding="utf-8")
    assert "activeModel || undefined, language" in app
    assert "onBatch, ac.signal, language" in app
    assert "onBatch, ac.signal, activeModel || undefined, language" in app
    assert "{ text, mode, model, images: images ?? [], rerun: rerun ?? false, language }" in api
    assert "{ prompts, model, language }" in api and "{ prompt, models, language }" in api


async def main():
    print(f"=== SUITE v0.38.0 Bilingual Web UI + localized demo — data tạm: {TMP} ===")
    for test in (t1, t2, t3, t4):
        await test()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
