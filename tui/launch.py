"""`forge` command entry point.

  forge                     → TUI toàn màn hình (mặc định, kiểu opencode/Claude Code)
  forge --web [--port 8000] → web UI + API server
  forge --repl              → REPL terminal đơn giản
  forge --once "prompt"     → chạy 1 lượt rồi thoát
  forge --parallel "a" "b"  → sub-agent song song
  forge --list-sessions     → liệt kê phiên
"""
import argparse
import asyncio
import sys


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="forge",
        description="⚡ Forge Agent — AI coding agent (TUI / Web / CLI)",
    )
    ap.add_argument("--web", action="store_true", help="chạy web UI + API server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--repl", action="store_true", help="REPL terminal đơn giản")
    ap.add_argument("--once", metavar="PROMPT", help="chạy 1 lượt rồi thoát")
    ap.add_argument("--parallel", nargs="+", metavar="TASK", help="sub-agent song song (tối đa 5)")
    ap.add_argument("--session", metavar="ID", help="dùng phiên có sẵn")
    ap.add_argument("--model", metavar="MODEL")
    ap.add_argument("--list-sessions", action="store_true")
    args = ap.parse_args()

    if args.list_sessions:
        from engine.session import SessionStore
        from rich.console import Console
        console = Console()
        rows = SessionStore().list()
        if not rows:
            console.print("[dim](chưa có phiên nào)[/dim]")
        for r in rows[:20]:
            console.print(f"  [bold]{r['id']}[/bold]  [dim]{r['title'][:48]} · {r['message_count']} msgs[/dim]")
        return 0

    if args.web:
        import uvicorn
        from server.main import app
        print(f"==> Forge Web: http://localhost:{args.port}")
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
        return 0

    if args.once or args.parallel:
        from cli.main import run_batch_cli, run_turn
        from engine.session import SessionStore

        async def _go() -> None:
            store = SessionStore()
            if args.parallel:
                await run_batch_cli(args.parallel[:5], model=args.model)
            else:
                sid = args.session or store.create(model=args.model or "").id
                await run_turn(sid, args.once, model=args.model)
                print(f"Phiên: {sid}")
        asyncio.run(_go())
        return 0

    if args.repl:
        from cli.main import interactive
        from engine.session import SessionStore
        sid = args.session or SessionStore().create(model=args.model or "").id
        asyncio.run(interactive(sid, args.model))
        return 0

    # mặc định: TUI
    try:
        from tui.app import run
    except ImportError as e:
        print(f"Thiếu thư viện TUI: {e}\nCài:  pip install textual")
        return 1
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
