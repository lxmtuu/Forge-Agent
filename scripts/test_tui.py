# -*- coding: utf-8 -*-
"""Audit suite v0.17.2 — A2 TUI SMOKE (Textual Pilot, headless):
boot app · gửi lệnh /help · /skills · /audit qua ô nhập thật · không crash.

Chạy:  python scripts/test_tui.py
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-tui-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("FORGE_PROFILE", None)

PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}")
            except Exception as e:
                FAIL.append((name, f"{e}"))
                print(f"  ✗ {name}: {e}")
                traceback.print_exc(limit=3)
        return run
    return deco


def _chat_text(app) -> str:
    """Gom text trong khung chat — Static qua render(), Markdown qua .source (headless
    không chạy compositor nên render() trả Blank, source luôn có text thật)."""
    parts = []
    for w in app.screen.query("Static, Markdown"):
        parts.append(str(getattr(w, "source", "") or ""))
        try:
            parts.append(str(w.render()))
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(parts)


async def _type_command(app, pilot, cmd: str) -> None:
    inp = app.query_one("#prompt")
    inp.value = cmd
    pilot.app.query_one("#prompt", type(inp)).focus()
    await pilot.press("enter")
    await pilot.pause()


@check("T1 TUI boot: app khởi động headless, tự tạo phiên, không crash")
async def t1():
    from tui.app import ForgeTUI
    app = ForgeTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.sid, "không tự tạo phiên khi boot"
        assert app.query_one("#prompt") is not None
        assert app.query_one("#chat") is not None


@check("T2 TUI /help: lệnh chạy qua ô nhập THẬT (Enter), nội dung help xuất hiện")
async def t2():
    from tui.app import ForgeTUI
    app = ForgeTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await _type_command(app, pilot, "/help")
        txt = _chat_text(app)
        assert "Lệnh" in txt, "không thấy nội dung /help trong chat"
        # ô nhập phải rỗng sau khi gửi
        assert app.query_one("#prompt").value == ""


@check("T3 TUI /skills: listing (kèm built-in skill-creator) hiện đúng")
async def t3():
    from tui.app import ForgeTUI
    app = ForgeTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await _type_command(app, pilot, "/skills")
        txt = _chat_text(app)
        assert "Skills" in txt and "skill-creator" in txt, txt[-400:]


@check("T4 TUI /audit: listing hiện (kể cả trạng thái trống) — không crash")
async def t4():
    from tui.app import ForgeTUI
    app = ForgeTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await _type_command(app, pilot, "/audit")
        txt = _chat_text(app)
        assert "Audit log" in txt or "chưa có tool call" in txt, txt[-400:]


@check("T5 TUI /connectors: presets hiện đúng qua ô nhập")
async def t5():
    from tui.app import ForgeTUI
    app = ForgeTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await _type_command(app, pilot, "/connectors")
        txt = _chat_text(app)
        assert "github" in txt and "composio-hub" in txt, txt[-400:]


@check("T7 TUI gửi tin THẬT (chế độ thật: key giả + LLM stub): delta hiện trong chat, busy thoát sạch")
async def t7():
    from tui.app import ForgeTUI
    import engine.llm as llm
    # ép chế độ THẬT (demo mode sẽ bỏ qua LLM — dùng send_demo riêng)
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-fake-for-tui-test"

    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        yield {"type": "delta", "text": "XIN-CHÀO-TỪ-LLM-GIẢ"}
        yield {"type": "finish", "reason": "stop"}

    orig = llm.stream_chat
    llm.stream_chat = fake
    app = ForgeTUI()
    try:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _type_command(app, pilot, "gửi thật đi")
            for _ in range(40):  # chờ turn XONG (tối đa 10s — demo có sleep + headless chậm)
                await pilot.pause(0.25)
                if not app.busy:
                    break
            assert not app.busy, "turn chưa kết thúc sau 10s"
            md = getattr(app, "_md_text", "") or ""
            assert "XIN-CHÀO-TỪ-LLM-GIẢ" in md, (
                f"delta không vào buffer markdown của TUI: {md[-200:]!r}")
    finally:
        llm.stream_chat = orig
        os.environ.pop("OPENROUTER_API_KEY", None)


async def main():
    print(f"=== TUI SMOKE (Textual Pilot) — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5, t7]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
