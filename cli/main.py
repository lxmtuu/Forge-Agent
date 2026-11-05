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
from engine.session import SessionStore              # noqa: E402

console = Console()
store = SessionStore()
cli_loops: dict[str, asyncio.Task] = {}  # session → loop task (F1, sống theo tiến trình CLI)

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
  /skills [add|new|remove …]  quản lý skill (chuẩn Agent Skills SKILL.md)
  /connectors [add|auth|oauth|allow…]  GitHub/Linear/Notion… qua MCP · oauth <tên> <client_id> [secret] = đăng nhập browser (PKCE)
  /audit [n]           nhật ký tool call (JSONL data/audit/)
  /rename <tên>        đổi tên phiên        /find <từ-khóa>  tìm phiên (tiêu đề+nội dung)
  /commit              commit thay đổi workspace (message conventional)   /autocommit [on|off]
  /loop <30m|1h> <tác vụ>  chạy định kỳ trong tiến trình · /loop off · /loop xem trạng thái
  /worktree [merge|discard]  quản lý worktree của sub-agent (isolation=worktree)
  /msg <phiên> <nội dung>  gửi tin sang phiên khác (/loop, fork…)   /inbox  đọc tin mới
  /undo               hoàn tác thay đổi gần nhất của agent (checkpoint)
  /compact [gợi ý]    nén hội thoại bằng LLM   /init         sinh AGENTS.md
  /fork               fork phiên hiện tại       /export [f]  xuất hội thoại Markdown
  /review [file|A...B]  code review diff (P0–P3 + verdict, đọc-only)
  /diff [file]        xem diff (git hoặc checkpoint phiên)
  /repomap [budget]   bản đồ file + symbol, budget 500–20000 ký tự
  /memory [clear]     xem bộ nhớ đang nạp / xoá MEMORY.md dự án
  /quit               thoát

[bold]Mẹo[/bold]: gõ nhiệm vụ tự nhiên, ví dụ:
  "viết script python đếm số từ trong file txt rồi test luôn"
Gõ @ten_file.py trong prompt để đính kèm file.
Gõ «# nội dung» để ghi nhớ nhanh vào MEMORY.md (không tốn LLM).
Custom lệnh: tạo .forge/commands/<tên>.md rồi gõ /<tên> [args].
Chạy song song nhiều tác vụ:  python cli/main.py --parallel "task A" "task B" """


def fmt_args(args: dict, limit: int = 90) -> str:
    try:
        s = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in list(args.items())[:3])
        return (s[:limit] + "…") if len(s) > limit else s
    except Exception:
        return str(args)[:limit]


async def run_turn(session_id: str, user_text: str, model: str | None = None,
                   chat_mode: str = "agent", json_out: bool = False) -> int:
    """Run one user turn. json_out=True: không render, in JSON cuối (headless)."""
    agent = Agent(store, session_id, model=model)
    # /run <tên> <task> — custom agent
    from engine import agents as fagents
    ag = fagents.expand(user_text, agent.workspace)
    if ag is not None:
        user_text, ag_model, ag_mode = ag
        model = ag_model or model
        chat_mode = ag_mode or chat_mode
        if not json_out:
            console.print(f"[dim]🤖 Custom agent «{ag[0].split('«')[1].split('»')[0]}»[/dim]")
    from engine import atfiles
    user_text, attached = atfiles.expand_at_refs(user_text, agent.workspace)
    if attached and not json_out:
        console.print(f"[dim]📎 Đã đính kèm: {', '.join('@' + a for a in attached)}[/dim]")
    demo = config.get_api_key() is None
    if json_out:
        # ---- headless JSON mode: thu thập, không render ----
        import json as _json
        src = send_demo(agent, user_text) if demo else agent.send(user_text, chat_mode=chat_mode)
        result: dict = {"session": session_id, "text": "", "tools": [], "usage": None, "error": None}
        try:
            async for ev in src:
                t = ev["type"]
                if t == "assistant_message":
                    result["text"] = ev.get("content") or result["text"]
                elif t == "tool_result":
                    result["tools"].append({"name": ev.get("name"),
                                            "ok": ev.get("ok"),
                                            "output": (ev.get("output") or "")[:1000]})
                elif t == "usage":
                    result["usage"] = ev.get("usage")
                elif t == "turn_end":
                    result["usage"] = ev.get("usage") or result["usage"]
                elif t == "error":
                    result["error"] = ev.get("message")
        finally:
            store.save(store.get(session_id))
        print(_json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["error"] is None else 1
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
            elif t == "todo_update":
                items = ev.get("items") or []
                done = sum(1 for x in items if x.get("status") == "done")
                mk = {"pending": "◻", "doing": "▶", "done": "✅"}
                body = "\n".join(f"      {mk.get(x.get('status'), '·')} {x.get('text')}" for x in items)
                console.print(f"  📋 [bold]TIẾN ĐỘ {done}/{len(items)}[/bold]\n{body}")
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
            elif t == "model_fallback":
                if reasoning_open:
                    console.print()
                    reasoning_open = False
                live.stop()
                console.print(f"  [yellow]🔁 Model lỗi — chuyển từ {ev['from']} → {ev['to']}[/yellow]")
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
                if ev.get("cost_usd") is not None:
                    su_cost = su.get("cost_usd")
                    extra = f" · cộng dồn phiên ~${su_cost:.4f}" if su_cost else ""
                    console.print(f"[dim]💵 Chi phí lượt này: ~${ev['cost_usd']:.4f}{extra}[/dim]")
    finally:
        try:
            live.stop()
        except Exception:
            pass
    return 0


def agent0_ws(store, session_id: str):
    """Workspace của phiên hiện tại — dùng cho các lệnh /skills..."""
    return store.workspace(session_id)


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
        if text == "/undo":
            from engine import checkpoints
            ws = store.workspace(session_id)
            res = await checkpoints.undo(checkpoints.key_for(ws), ws)
            style = "green" if res.get("ok") else "red"
            mark = "↩" if res.get("ok") else "⚠"
            console.print(f"  [{style}]{mark} {res.get('message')}[/{style}]")
            continue
        if text.startswith("/compact"):
            from engine.agent import compact_session
            ins = text[8:].strip()
            agent = Agent(store, session_id, model=model)
            console.print("  [dim]🧹 Đang tóm tắt hội thoại…[/dim]")
            res = await compact_session(agent, ins)
            if res.get("ok"):
                console.print(f"  [green]✅ Đã nén {res['before']} → {res['after']} tin nhắn[/green]")
            else:
                console.print(f"  [red]⚠ {res.get('message')}[/red]")
            continue
        if text == "/init":
            from engine.agent import init_agents_md
            agent = Agent(store, session_id, model=model)
            console.print("  [dim]🚀 Đang phân tích workspace…[/dim]")
            res = await init_agents_md(agent)
            if res.get("ok"):
                console.print(f"  [green]✅ Đã tạo {res.get('path')}[/green]")
            else:
                console.print(f"  [red]⚠ {res.get('message')}[/red]")
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
        if text.startswith("/profile"):
            from engine import config as _cfg
            arg = text[8:].strip()
            if not arg:
                profs = ", ".join(sorted(_cfg.list_profiles().keys())) or "(chưa định nghĩa)"
                cur = _cfg.load_config().get("active_profile") or "(mặc định)"
                console.print(f"  Profile hiện tại: [bold]{cur}[/bold] · có sẵn: {profs}")
            elif _cfg.set_profile(arg):
                eff = _cfg.load_config()
                console.print(f"  [green]✅ Profile → {arg}[/green] "
                              f"(model {eff.get('model', '?')}, duyệt {eff.get('approval_mode', 'guarded')})")
            else:
                console.print(f"  [red]⚠ Không có profile «{arg}»[/red] — xem /profile")
            continue
        if text == "/context":
            agent = Agent(store, session_id, model=model)
            ctx = agent.context_stats()
            pct = f"{ctx['percent']}%" if ctx["percent"] is not None else "∞"
            lim = f"{ctx['limit']:,}" if ctx["limit"] else "không giới hạn"
            console.print(f"  🧠 Context: [bold]{pct}[/bold] ({ctx['chars']:,} ký tự ≈ "
                          f"{ctx['est_tokens']:,} tokens / {lim}) · {ctx['messages']} tin nhắn · "
                          f"memory: {'✓' if ctx['memory'] else '—'}")
            continue
        if text == "/memory" or text.startswith("/memory "):
            from engine import memory as fmem
            m_arg = text[7:].strip()
            agent = Agent(store, session_id, model=model)
            if m_arg == "clear":
                console.print(f"  {fmem.clear_memory(agent.workspace)}")
            else:
                console.print(fmem.memory_overview(agent.workspace))
            continue
        if text.startswith("/review"):
            from engine import review as freview
            r_arg = text[len("/review"):].strip()
            agent = Agent(store, session_id, model=model)
            try:
                diff_text, label = await freview.collect_diff(agent.workspace, session_id, r_arg)
            except ValueError as e:
                console.print(f"  🔍 {e}")
                continue
            console.print(f"  [dim]Review ({label}) — chế độ đọc-only…[/dim]")
            await run_turn(session_id, freview.build_prompt(diff_text, r_arg, label),
                           model=model, chat_mode="plan")
            continue
        if text.startswith("/diff"):
            from engine import review as freview
            d_arg = text[len("/diff"):].strip()
            agent = Agent(store, session_id, model=model)
            try:
                diff_text, label = await freview.collect_diff(agent.workspace, session_id, d_arg)
            except ValueError as e:
                console.print(f"  📄 {e}")
                continue
            console.print(f"  [bold]📄 Diff — {label}[/bold]")
            from rich.syntax import Syntax
            console.print(Syntax(diff_text[:12000], "diff", theme="ansi_dark",
                                 word_wrap=True, background_color="default"))
            continue
        if text == "/repomap" or text.startswith("/repomap "):
            from engine import repomap as frm
            b = text[9:].strip()
            try:
                budget = min(max(int(b), 500), 20000) if b else frm.BUDGET_CHARS
            except ValueError:
                budget = frm.BUDGET_CHARS
            console.print(f"[dim]{frm.build(store.workspace(session_id), budget=budget)['map']}[/dim]")
            continue
        if text == "/doctor":
            from engine.diagnostics import doctor
            rep = await doctor(store)
            for c in rep["checks"]:
                style = "green" if c["ok"] else "red"
                console.print(f"  [{style}]{'✓' if c['ok'] else '✗'}[/{style}] "
                              f"[bold]{c['name']}[/bold] — {c['detail']}")
            console.print(f"  [bold]{rep['summary']}[/bold]")
            continue
        if text == "/agents":
            from engine import agents as fagents
            agent = Agent(store, session_id, model=model)
            rows = fagents.list_agents(agent.workspace)
            if not rows:
                console.print("  (chưa có custom agent — tạo .forge/agents/<tên>.md với "
                              "frontmatter description/model/mode)")
            for r in rows:
                console.print(f"  🤖 [bold]{r['name']}[/bold] — {r['description'] or '(không mô tả)'}"
                              + (f" · {r['model']}" if r["model"] else ""))
            continue
        if text.startswith("/rename "):
            ok = store.rename(session_id, text[8:].strip())
            console.print("[green]✅ Đã đổi tên phiên[/green]" if ok
                          else "[red]❌ Không đổi được (phiên không tồn tại?)[/red]")
            continue
        if text.startswith("/find "):
            q = text[6:].strip()
            rows = store.list(q=q)
            if not rows:
                console.print(f"[dim](không có phiên nào khớp «{q}» — tìm theo tiêu đề + nội dung tin nhắn)[/dim]")
            for r in rows[:20]:
                console.print(f"  [bold]{r['id']}[/bold]  {r['title'][:46]} "
                              f"[dim]· {r['message_count']} tin[/dim]")
            continue
        if text.startswith("/msg "):
            from engine import bus as fbus
            parts = text[5:].strip().split(None, 1)
            to_sid = parts[0].strip() if parts else ""
            body = parts[1].strip() if len(parts) > 1 else ""
            if not to_sid or not body:
                console.print("❌ Cú pháp: /msg <id-phiên> <nội dung>")
            elif store.get(to_sid) is None:
                console.print(f"❌ Không có phiên '{to_sid}' (xem /agents).")
            else:
                fbus.send(to_sid, session_id, body)
                console.print(f"📨 Đã gửi tới {to_sid} — phiên đích sẽ thấy ở lượt kế tiếp.")
            continue
        if text == "/inbox":
            from engine import bus as fbus
            rows = fbus.inbox(session_id)
            if rows:
                for r in rows:
                    console.print(f"📥 [dim]{str(r['ts'])[11:16]}[/dim] [bold]{r['from']}[/bold]: {r['text'][:200]}")
            else:
                console.print("(hộp thư trống)")
            continue
        if text == "/agents":
            for r in store.list()[:8]:
                console.print(f"  [bold]{r['id']}[/bold]  {r['title'][:46]} [dim]· {r['message_count']} tin[/dim]")
            continue
        if text == "/worktree" or text.startswith("/worktree "):
            from engine import worktree as fwt
            w_arg = text[9:].strip()
            if w_arg.startswith("merge "):
                sub = w_arg[6:].strip()
                res = await fwt.merge(sub, session_id, session_id, store.workspace(session_id))
                console.print(("✅ " if res["ok"] else "❌ ") + res["message"])
            elif w_arg.startswith("discard "):
                res = await fwt.discard(w_arg[8:].strip(), session_id)
                console.print(("🗑 " + ", ".join(res["removed"])) if res["ok"] else "(không có gì để bỏ)")
            else:
                rows = await fwt.list_all()
                if not rows:
                    console.print("Không có worktree nào (spawn_subagent isolation=worktree sẽ tạo).")
                for r in rows:
                    console.print(f"📁 {r['session']} — {r['stat']}\n   [dim]{r['path']}[/dim]")
                console.print("[dim]Gộp: /worktree merge <phiên-con> · Bỏ: /worktree discard <phiên-con>[/dim]")
            continue
        if text == "/loop" or text.startswith("/loop "):
            from engine import scheduler as fsched
            l_arg = text[5:].strip()
            if l_arg.lower() in ("off", "stop", "x"):
                t = cli_loops.pop(session_id, None)
                if t:
                    t.cancel()
                console.print("⚪ Đã dừng loop." if t else "(không có loop nào)")
                continue
            if not l_arg:
                t = cli_loops.get(session_id)
                console.print(f"🔁 Đang chạy: mỗi {fsched.fmt_interval(t['every'])} — «{t['text']}» "
                              f"({t['runs']} lượt)" if t else
                              "Không có loop nào. Cú pháp: /loop <30m|1h> <tác vụ> · /loop off")
                continue
            parts = l_arg.split(None, 1)
            every_s = fsched.parse_interval(parts[0])
            task_text = parts[1].strip() if len(parts) > 1 else ""
            if not task_text:
                console.print("❌ Thiếu tác vụ: /loop <30m|1h> <tác vụ>")
                continue
            old_t = cli_loops.pop(session_id, None)
            if old_t:
                old_t.cancel()

            async def _cli_loop(every_s=every_s, task_text=task_text):
                n = 0
                while True:
                    n += 1
                    console.print(f"[dim]🔁 loop #{n}: {task_text[:60]}…[/dim]")
                    try:
                        await run_turn(session_id, task_text, model, "agent")
                    except Exception as e:  # noqa: BLE001 — lượt hỏng không chết loop
                        console.print(f"[red]loop lượt #{n} lỗi (tiếp tục): {e}[/red]")
                    await asyncio.sleep(every_s)

            t = asyncio.create_task(_cli_loop())
            cli_loops[session_id] = t
            console.print(f"🔁 Loop BẬT — mỗi {fsched.fmt_interval(every_s)} chạy «{task_text}» · /loop off để tắt")
            continue
        if text == "/commit":
            from engine import autocommit as fac
            res = await fac.commit_turn(store.workspace(session_id), session_id,
                                        "(thủ công /commit)", "")
            console.print("📦 Không có thay đổi nào để commit." if res is None
                          else f"📦 {res['subject']} ({res['files']} file)")
            continue
        if text.startswith("/autocommit"):
            from engine import config as fcfg
            arg = text[11:].strip().lower()
            if arg in ("on", "off", "true", "false"):
                fcfg.save_config({"auto_commit": arg in ("on", "true")})
            console.print(("🟢 auto-commit BẬT" if fcfg.get_auto_commit()
                           else "⚪ auto-commit TẮT")
                          + " — mỗi lượt agent có thay đổi sẽ git commit (xem `git log` trong workspace)")
            continue
        if text == "/audit" or text.startswith("/audit "):
            from engine import auditlog
            _n = text[6:].strip()
            n = int(_n) if _n.isdigit() else 20
            console.print(Text(auditlog.format_listing(n)))
            continue
        if text == "/connectors" or text.startswith("/connectors "):
            from engine import connectors as fconn
            arg = text[11:].strip()
            if arg.startswith("add "):
                parts = arg[4:].strip().split()
                out = fconn.add(parts[0], parts[1] if len(parts) > 1 else "",
                                "--write" in parts)
            elif arg.startswith("auth "):
                parts = arg[5:].strip().split(None, 1)
                out = fconn.auth(parts[0], parts[1] if len(parts) > 1 else "")
            elif arg.startswith("oauth "):
                from engine import oauth as fo
                parts = arg[6:].strip().split()
                if len(parts) >= 2:
                    fo.save_creds(parts[0], parts[1], parts[2] if len(parts) > 2 else "")
                out = fo.connect(parts[0])
            elif arg.startswith("logout "):
                from engine import oauth as fo
                out = ("🗑 Đã xoá token OAuth." if fo.forget(arg[7:].strip())
                       else f"❌ '{arg[7:].strip()}' chưa có token OAuth.")

            elif arg.startswith("allow "):
                parts = arg[6:].strip().split()
                out = fconn.allow(parts[0], parts[1] if len(parts) > 1 else "*")
            elif arg.startswith("deny "):
                parts = arg[5:].strip().split()
                out = fconn.deny(parts[0], parts[1] if len(parts) > 1 else "*")
            elif arg.startswith("remove "):
                out = fconn.remove(arg[7:].strip())
            else:
                out = fconn.status_listing()
            console.print(Text(out))
            continue
        if text == "/skills" or text.startswith("/skills "):
            from engine import skillmgr
            arg = text[7:].strip()
            if arg.startswith("add "):
                out = skillmgr.add(agent0_ws(store, session_id), arg[4:].strip())
            elif arg.startswith("new "):
                parts = arg[4:].strip().split(None, 1)
                out = skillmgr.new_skill(agent0_ws(store, session_id),
                                         parts[0] if parts else "", parts[1] if len(parts) > 1 else "")
            elif arg.startswith("remove "):
                out = skillmgr.remove(agent0_ws(store, session_id), arg[7:].strip())
            elif arg.startswith("trust"):
                out = skillmgr.trust(agent0_ws(store, session_id), arg[5:].strip())
            else:
                out = skillmgr.format_listing(agent0_ws(store, session_id))
            console.print(Text(out))
            continue
        if text.startswith("/run "):
            await run_turn(session_id, text, model=model)  # expand trong run_turn
            continue
        if text == "/fork":
            ns = store.fork(session_id)
            if ns:
                session_id = ns.id
                console.print(f"[green]🍴 Đã fork → phiên mới:[/green] {session_id}")
            continue
        if text.startswith("/export"):
            from engine.export import to_markdown
            s = store.get(session_id)
            arg = text[7:].strip() or f"forge-{session_id}.md"
            from pathlib import Path as _P
            path = _P(arg)
            if not path.is_absolute():
                path = _P.cwd() / path
            try:
                path.write_text(to_markdown(s), encoding="utf-8")
                console.print(f"[green]⤓ Đã xuất hội thoại → {path}[/green]")
            except OSError as e:
                console.print(f"[red]⚠ Không ghi được file: {e}[/red]")
            continue
        if text.startswith("/"):
            from engine import commands as fcmd
            agent0 = Agent(store, session_id, model=model)
            expanded = fcmd.expand(text, agent0.workspace)
            if expanded is not None:
                await run_turn(session_id, expanded, model=model)
                continue
            reason = fcmd.blocked_reason(agent0_ws(store, session_id), text)
            if reason:
                console.print(f"[yellow]{reason}[/yellow]")
            else:
                console.print(f"[red]Lệnh không rõ:[/red] {text.split()[0]} — /help "
                              f"(custom: .forge/commands/<tên>.md)")
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
    ap.add_argument("--profile", metavar="NAME", help="dùng profile trong data/config.json (vd: safe)")
    ap.add_argument("--list-sessions", action="store_true")
    ap.add_argument("--demo", action="store_true", help="ép chạy demo (bỏ qua API key)")
    ap.add_argument("--json", action="store_true",
                    help="(--once) đầu ra JSON structured cho script/CI thay vì render")
    args = ap.parse_args()

    if args.profile:
        from engine import config as _cfg
        if not _cfg.set_profile(args.profile):
            profs = ", ".join(sorted(_cfg.list_profiles().keys())) or "(không có)"
            console.print(f"[red]⚠ Không có profile «{args.profile}»[/red] — các profile: {profs}")
            return 1
        console.print(f"[green]==> Profile: {args.profile}[/green]")

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
        return await run_turn(session_id, args.once, model=model, chat_mode=args.mode,
                              json_out=args.json)

    await interactive(session_id, model)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        sys.exit(130)
