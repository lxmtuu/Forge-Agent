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
    ap.add_argument("--mode", default="agent", choices=["direct", "agent", "plan"],
                    help="chế độ làm việc cho --once")
    ap.add_argument("--battle", metavar="PROMPT", help="⚔ cùng 1 prompt chạy nhiều model song song")
    ap.add_argument("--parallel", nargs="+", metavar="TASK",
                    help="🧩 chạy nhiều task song song (mỗi task 1 phiên)")
    ap.add_argument("--models", nargs="+", metavar="MODEL", help="danh sách model cho --battle")
    ap.add_argument("--session", metavar="ID", help="dùng phiên có sẵn")
    ap.add_argument("--model", metavar="MODEL")
    ap.add_argument("--profile", metavar="NAME", help="dùng profile trong data/config.json (vd: safe)")
    ap.add_argument("--json", action="store_true",
                    help="(--once) đầu ra JSON structured cho script/CI")
    ap.add_argument("--list-sessions", action="store_true")
    args = ap.parse_args()

    if getattr(args, "profile", None):
        from engine import config as _cfg
        if _cfg.set_profile(args.profile):
            print(f"==> Profile: {args.profile}")
        else:
            profs = ", ".join(sorted(_cfg.list_profiles().keys())) or "(không có)"
            print(f"⚠ Không có profile «{args.profile}» — các profile: {profs}")
            return 1

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

    if args.once or args.parallel or args.battle:
        from cli.main import run_batch_cli, run_turn
        from engine.session import SessionStore

        async def _go() -> None:
            store = SessionStore()
            if args.battle:
                models = args.models or [args.model or __import__("engine.config", fromlist=["get_model"]).get_model()]
                await run_batch_cli(
                    [{"prompt": args.battle, "model": m, "title": f"⚔ {m.split('/')[-1]}"}
                     for m in models[:4]],
                    label="⚔ model thi đấu — cùng 1 prompt")
            elif args.parallel:
                await run_batch_cli([{"prompt": p, "model": args.model or ""} for p in args.parallel[:5]])
            else:
                sid = args.session or store.create(model=args.model or "").id
                await run_turn(sid, args.once, model=args.model, chat_mode=args.mode,
                               json_out=args.json)
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
