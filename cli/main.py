#!/usr/bin/env python3
"""Forge CLI — terminal coding agent (Claude Code / Codex style).

Usage:
  python cli/main.py                      # interactive REPL
  python cli/main.py --once "prompt"      # one-shot: run a single task and exit
  python cli/main.py --list-sessions      # list saved sessions
  python cli/main.py --session <id>       # resume a session
  python cli/main.py --model <model>      # pick model for this run
  python cli/main.py --demo               # scripted demo (no API key needed)

Set OPENROUTER_API_KEY env var, or type `/key sk-or-...` inside the REPL.
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console                     # noqa: E402
from rich.live import Live                           # noqa: E402
from rich.markdown import Markdown                   # noqa: E402
from rich.panel import Panel                         # noqa: E402
from rich.text import Text                           # noqa: E402

from engine import config                            # noqa: E402
from engine.agent import Agent, send_demo            # noqa: E402
from engine.llm import LLMError                      # noqa: E402
from engine.session import SessionStore              # noqa: E402

console = Console()
store = SessionStore()

BANNER = r"""
   __             _
  / _|___  ___ __| | ___ _ __
 | |_/ __|/ __/ _` |/ _ \ '__|
 |  _\__ \ (_| (_| |  __/ |
 |_| |___/\___\__,_|\___|_|
   AI coding agent · CLI edition
"""

HELP = """[bold]Lệnh[/bold]
  /new                tạo phiên mới          /sessions        liệt kê phiên
  /use <id>           chuyển phiên           /model <model>   đổi model
  /key <apikey>       lưu API key OpenRouter /files           xem cây file
  /read <path>        đọc file               /clear           xóa màn hình
  /quit               thoát

[bold]Mẹo[/bold]: gõ nhiệm vụ tự nhiên, ví dụ:
  "viết script python đếm số từ trong file txt rồi test luôn" """


def fmt_args(args: dict, limit: int = 90) -> str:
    try:
        s = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in list(args.items())[:3])
        return (s[:limit] + "…") if len(s) > limit else s
    except Exception:
        return str(args)[:limit]


async def run_turn(session_id: str, user_text: str, model: str | None = None) -> int:
    """Run one user turn, stream to terminal. Returns 0 on success."""
    agent = Agent(store, session_id, model=model)
    demo = config.get_api_key() is None
    if demo and not user_text.startswith("/"):
        console.print("[dim yellow]⚡ DEMO MODE — chưa có API key. Lưu key bằng /key <api>[/dim yellow]")
    source = send_demo(agent, user_text) if demo else agent.send(user_text)

    stream = Text()
    live = Live(console=console, refresh_per_second=12, vertical_overflow="ellipsis")
    live.start()
    try:
        async for ev in source:
            t = ev["type"]
            if t == "reasoning_delta":
                pass  # keep CLI output clean; reasoning shown by web UI
            elif t == "assistant_delta":
                stream.append(ev["text"])
                live.update(Markdown(stream.plain))
            elif t == "tool_start":
                live.stop()
                console.print(f"  [cyan]⚙ {ev['name']}[/cyan] [dim]{fmt_args(ev['args'])}[/dim]")
                live.start()
            elif t == "tool_result":
                live.stop()
                mark = "[green]✓[/green]" if ev["ok"] else "[red]✗[/red]"
                out = ev["output"]
                preview = out if len(out) <= 500 else out[:500] + " …"
                console.print(f"    {mark} [dim]{preview}[/dim]")
                live.start()
            elif t == "assistant_message":
                stream = Text()
                live.update(Text())
            elif t == "error":
                live.stop()
                console.print(Panel(str(ev["message"]), title="Lỗi", border_style="red"))
                live.start()
            elif t == "turn_end":
                live.stop()
                console.print()
    finally:
        try:
            live.stop()
        except Exception:
            pass
    return 0


def print_sessions() -> None:
    rows = store.list()
    if not rows:
        console.print("[dim](chưa có phiên nào — gõ nhiệm vụ để bắt đầu)[/dim]")
        return
    for r in rows[:12]:
        console.print(f"  [bold]{r['id']}[/bold]  [dim]{r['title'][:48]} · {r['message_count']} msgs[/dim]")


async def interactive(session_id: str | None, model: str | None) -> None:
    console.print(Text(BANNER, style="bold cyan"))
    key = config.get_api_key()
    if key:
        key_info = f"[green]✓ {config.mask_key(key)}[/green]"
    else:
        key_info = "[yellow]DEMO MODE (chưa có key)[/yellow]"
    console.print(Panel(
        f"Model: [bold]{model or config.get_model()}[/bold]   Key: {key_info}\n"
        f"[dim]{HELP}[/dim]",
        border_style="cyan",
    ))
    if session_id is None:
        s = store.create(model=model or "")
        session_id = s.id
        console.print(f"[dim]Phiên mới: {session_id} · workspace: data/workspaces/{session_id}[/dim]")

    while True:
        try:
            text = console.input("[bold cyan]forge ❯ [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/dim]")
            return
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            console.print("[dim]Bye![/dim]")
            return
        if text == "/help":
            console.print(HELP)
            continue
        if text == "/new":
            s = store.create(model=model or "")
            session_id = s.id
            console.print(f"[green]Phiên mới:[/green] {session_id}")
            continue
        if text == "/sessions":
            print_sessions()
            continue
        if text.startswith("/use "):
            sid = text[5:].strip()
            if store.get(sid):
                session_id = sid
                console.print(f"[green]Đã chuyển sang phiên {sid}[/green]")
            else:
                console.print("[red]Không tìm thấy phiên[/red]")
            continue
        if text.startswith("/model "):
            m = text[7:].strip()
            config.save_config({"model": m})
            model = m
            console.print(f"[green]Model → {m}[/green]")
            continue
        if text.startswith("/key "):
            config.save_config({"api_key": text[5:].strip()})
            console.print(f"[green]Đã lưu key {config.mask_key(text[5:].strip())}[/green]")
            continue
        if text == "/files":
            agent = Agent(store, session_id)
            console.print(agent.workspace.as_posix())
            r = await __import__("engine.tools", fromlist=["execute_tool"]).execute_tool(
                "list_dir", {"path": "."}, agent.workspace)
            console.print(r["output"])
            continue
        if text == "/clear":
            console.clear()
            continue

        await run_turn(session_id, text, model=model)


async def main_async() -> int:
    ap = argparse.ArgumentParser(prog="forge")
    ap.add_argument("--once", metavar="PROMPT", help="chạy 1 lượt rồi thoát")
    ap.add_argument("--session", metavar="ID", help="dùng phiên có sẵn")
    ap.add_argument("--model", metavar="MODEL", help="model OpenRouter")
    ap.add_argument("--list-sessions", action="store_true")
    ap.add_argument("--demo", action="store_true", help="ép chạy demo (bỏ qua API key)")
    args = ap.parse_args()

    if args.list_sessions:
        print_sessions()
        return 0

    model = args.model
    if args.session:
        session_id = args.session
    else:
        session_id = store.create(model=model or "").id

    if args.once:
        await run_turn(session_id, args.once, model=model)
        console.print(f"[dim]Phiên: {session_id}[/dim]")
        return 0

    await interactive(session_id, model)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        sys.exit(130)
