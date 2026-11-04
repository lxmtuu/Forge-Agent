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
from engine.agent import Agent, send_demo, run_batch  # noqa: E402
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
  /mcp [refresh]      xem MCP servers        /mode [g|a]      guarded / auto (YOLO)
  /usage              tokens đã dùng         /keytest         kiểm tra API key
  /quit               thoát

[bold]Mẹo[/bold]: gõ nhiệm vụ tự nhiên, ví dụ:
  "viết script python đếm số từ trong file txt rồi test luôn"
Chạy song song nhiều tác vụ:  python cli/main.py --parallel "task A" "task B" """


def fmt_args(args: dict, limit: int = 90) -> str:
    try:
        s = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in list(args.items())[:3])
        return (s[:limit] + "…") if len(s) > limit else s
    except Exception:
        return str(args)[:limit]


async def run_turn(session_id: str, user_text: str, model: str | None = None,
                   chat_mode: str = "agent") -> int:
    """Run one user turn, stream to terminal. Returns 0 on success."""
    agent = Agent(store, session_id, model=model)
    demo = config.get_api_key() is None
    if demo and not user_text.startswith("/"):
        console.print("[dim yellow]⚡ DEMO MODE — chưa có API key. Lưu key bằng /key <api>[/dim yellow]")
    source = send_demo(agent, user_text) if demo else agent.send(user_text, chat_mode=chat_mode)

    stream = Text()
    live = Live(console=console, refresh_per_second=12, vertical_overflow="ellipsis")
    live.start()
    reasoning_open = False
    try:
        async for ev in source:
            t = ev["type"]
            if t == "reasoning_delta":
                if not reasoning_open:
                    live.stop()
                    console.print("[dim]💭 ", end="")
                    reasoning_open = True
                console.print(ev["text"], end="", style="dim", markup=False, highlight=False)
            elif t == "assistant_delta":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                stream.append(ev["text"])
                live.update(Markdown(stream.plain))
                if not live.is_started:
                    live.start()
            elif t == "tool_start":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                live.stop()
                console.print(f"  [cyan]⚙ {ev['name']}[/cyan] [dim]{fmt_args(ev['args'])}[/dim]")
            elif t == "tool_result":
                mark = "[green]✓[/green]" if ev["ok"] else "[red]✗[/red]"
                out = ev["output"]
                preview = out if len(out) <= 500 else out[:500] + " …"
                console.print(f"    {mark} [dim]{preview}[/dim]")
            elif t == "assistant_message":
                stream = Text()
                live.update(Text())
            elif t == "error":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                live.stop()
                console.print(Panel(str(ev["message"]), title="Lỗi", border_style="red"))
            elif t == "approval_request":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                live.stop()
                console.print(Panel(
                    f"[bold]{ev['command']}[/bold]\n\n"
                    f"Lý do: {', '.join(ev['reasons']) or '—'}  ·  mức: [bold]{ev['level']}[/bold]",
                    title="🔔 Cần phê duyệt lệnh shell", border_style="yellow"))
                from engine import approvals as _appr
                choice = (await asyncio.to_thread(
                    console.input, "  [Y] Chấp nhận / [A] Luôn cho phép / [n] Từ chối: "
                )).strip().lower()
                decision = ("approve_always" if choice in ("a", "always")
                            else "deny" if choice in ("n", "no")
                            else "approve")
                _appr.resolve(ev["id"], decision)
                console.print(f"  [dim]→ {decision}[/dim]")
                live.start()
            elif t == "approval_decision":
                pass
            elif t == "turn_end":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                live.stop()
                console.print()
                su = ev.get("session_usage") or {}
                if su.get("total_tokens"):
                    console.print(
                        f"[dim]🔢 tokens phiên: {su.get('total_tokens', 0)} "
                        f"(prompt {su.get('prompt_tokens', 0)} · completion {su.get('completion_tokens', 0)}"
                        + (f" · ${su.get('cost', 0)}" if su.get("cost") else "") + ")[/dim]"
                    )
    finally:
        try:
            live.stop()
        except Exception:
            pass
    return 0


async def run_batch_cli(tasks: list[dict], label: str = "⚡ tác vụ song song") -> None:
    """Parallel sub-agents in terminal, output tagged [T#]."""
    demo = config.get_api_key() is None
    console.print(Panel(
        f"[bold]{len(tasks)} {label}[/bold] — mỗi tác vụ 1 session + workspace riêng",
        border_style="cyan"))
    async for ev in run_batch(store, tasks, demo=demo):
        if ev["type"] == "task_created":
            console.print(f"  [green]▶ T{ev['index'] + 1}[/green] [dim]{ev['title']}[/dim]")
        elif ev["type"] == "task_event":
            i, inner = ev["index"], ev["event"]
            tag = f"[bold cyan]T{i + 1}[/bold cyan]"
            it = inner["type"]
            if it == "tool_start":
                console.print(f"  {tag} ⚙ {inner['name']} [dim]{fmt_args(inner['args'])}[/dim]")
            elif it == "tool_result":
                mark = "[green]✓[/green]" if inner["ok"] else "[red]✗[/red]"
                console.print(f"  {tag}   {mark} [dim]{inner['output'][:200]}[/dim]")
            elif it == "error":
                console.print(f"  {tag} [red]{inner['message']}[/red]")
        elif ev["type"] == "batch_done":
            for tsk in ev["tasks"]:
                console.print(f"  [green]✔ T{tsk['index'] + 1} hoàn thành[/green] → session [bold]{tsk['session_id']}[/bold]")


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
        if text == "/mcp" or text.startswith("/mcp "):
            from engine.mcp import manager as mm
            if text[4:].strip() == "refresh":
                await mm.refresh()
                console.print("[green]Đã refresh MCP servers[/green]")
            for s in mm.status():
                style = {"ready": "green", "error": "red"}.get(s["status"], "yellow")
                console.print(f"  [{style}]●[/{style}] [bold]{s['name']}[/bold] "
                              f"[dim]{s['command']} {' '.join(s['args'])}[/dim] [{style}]{s['status']}[/{style}]")
                if s["tools"]:
                    console.print(f"      tools: {', '.join(s['tools'])}")
                if s["error"]:
                    console.print(f"      [red]{s['error']}[/red]")
            continue
        if text.startswith("/mode"):
            arg = text[5:].strip().lower()
            if arg in ("auto", "yolo"):
                config.save_config({"approval_mode": "auto"})
                console.print("[red]⚡ AUTO (YOLO)[/red] — mọi lệnh được chạy, cẩn thận!")
            elif arg in ("ask", "hoi"):
                config.save_config({"approval_mode": "ask"})
                console.print("[yellow]🔔 ASK[/yellow] — sẽ hỏi bạn trước khi chạy lệnh warn/danger")
            elif arg in ("guarded", "g", "guard"):
                config.save_config({"approval_mode": "guarded"})
                console.print("[green]🛡 GUARDED[/green] — lệnh nguy hiểm sẽ bị chặn")
            else:
                cur = config.load_config().get("approval_mode", "guarded")
                console.print(f"Hiện tại: [bold]{cur}[/bold] — dùng /mode guarded|ask|auto")
            continue
        if text == "/keytest":
            from engine.llm import check_key
            console.print("  [dim]Đang kiểm tra key với OpenRouter…[/dim]")
            r = await check_key()
            if r.get("valid"):
                lim = f" / hạn mức ${r['limit']}" if r.get("limit") is not None else " · không giới hạn"
                free = " · free tier" if r.get("is_free_tier") else ""
                console.print(f"  [green]✅ Key hợp lệ[/green] — «{r.get('label')}» · "
                              f"đã dùng ${r.get('usage') or 0}{lim}{free}")
            else:
                console.print(f"  [red]❌ {r.get('error')}[/red]")
                if r.get("hint"):
                    console.print(f"  [yellow]💡 {r['hint']}[/yellow]")
            continue
        if text == "/usage":
            s = store.get(session_id)
            u = (s.usage if s else {}) or {}
            tot = u.get("total_tokens", 0)
            console.print(f"  Phiên này: [bold]{tot}[/bold] tokens "
                          f"(prompt {u.get('prompt_tokens', 0)} · completion {u.get('completion_tokens', 0)}"
                          + (f" · ~${u.get('cost', 0)}" if u.get("cost") else "") + ")")
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
    ap.add_argument("--mode", default="agent", choices=["direct", "agent", "plan"],
                    help="chế độ làm việc cho --once")
    ap.add_argument("--battle", metavar="PROMPT", help="⚔ cùng 1 prompt chạy nhiều model song song")
    ap.add_argument("--models", nargs="+", metavar="MODEL", help="danh sách model cho --battle (tối đa 4)")
    ap.add_argument("--parallel", nargs="+", metavar="TASK", help="chạy song song nhiều tác vụ (sub-agent)")
    ap.add_argument("--session", metavar="ID", help="dùng phiên có sẵn")
    ap.add_argument("--model", metavar="MODEL", help="model OpenRouter")
    ap.add_argument("--list-sessions", action="store_true")
    ap.add_argument("--demo", action="store_true", help="ép chạy demo (bỏ qua API key)")
    args = ap.parse_args()

    if args.list_sessions:
        print_sessions()
        return 0

    if args.parallel:
        await run_batch_cli([{"prompt": p, "model": args.model or ""} for p in args.parallel[:5]])
        return 0

    if args.battle:
        await run_batch_cli(
            [{"prompt": args.battle, "model": m,
              "title": f"⚔ {m.split('/')[-1]}"} for m in (args.models or [config.get_model()])][:4],
            label="⚔ model thi đấu — cùng 1 prompt")
        return 0

    model = args.model
    if args.session:
        session_id = args.session
    else:
        session_id = store.create(model=model or "").id

    if args.once:
        await run_turn(session_id, args.once, model=model, chat_mode=args.mode)
        console.print(f"[dim]Phiên: {session_id}[/dim]")
        return 0

    await interactive(session_id, model)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        sys.exit(130)
