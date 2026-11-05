"""forge-agent launcher — 1 lệnh từ đầu đến cuối: venv (lần đầu) → cài deps → server → mở browser.

run_forge.bat (Windows) / run_forge.sh (macOS/Linux) chỉ là wrapper mỏng pure-ASCII
(theo research: codepage lúc cmd PARSE file mới quyết định — chữ có dấu để Python in).
Logic sống ở đây để in tiếng Việt UTF-8 an toàn mọi máy.

Cách dùng:
    python scripts/launch.py               # setup (nếu cần) + chạy server + mở browser
    python scripts/launch.py --no-browser  # không tự mở tab trình duyệt
    python scripts/launch.py --check       # chỉ khám phá môi trường, không khởi động
    python scripts/launch.py --setup       # nhập key ẩn trong terminal
    python scripts/launch.py --release     # chạy server dùng chung (bắt buộc auth)
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.secrets import sanitized_env  # child setup không được thừa kế provider key

VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"
VPY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
PORT = int(os.environ.get("FORGE_PORT", "8000"))
HOST = os.environ.get("FORGE_HOST", "127.0.0.1")
URL = f"http://localhost:{PORT}"


def say(*a) -> None:
    print(*a, flush=True)


def ensure_utf8() -> None:
    """Windows console mặc định không phải UTF-8 — tự reconfigure, không cần chcp."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: S110, BLE001 — console lạ vẫn phải chạy tiếp
            pass


def venv_ready() -> bool:
    return VPY.exists()


def deps_installed() -> bool:
    if not venv_ready():
        return False
    r = subprocess.run([str(VPY), "-c", "import fastapi, uvicorn, httpx, rich, authlib"],
                       check=False, capture_output=True, env=sanitized_env())
    return r.returncode == 0


def setup_venv() -> None:
    if deps_installed():
        say("✓ Môi trường .venv sẵn sàng (bỏ qua setup)")
        return
    if not venv_ready():
        say(f"① Tạo môi trường ảo .venv bằng Python {sys.version.split()[0]} …")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True,
                          env=sanitized_env())
    if not deps_installed():
        say("② Cài dependencies (pip install -e .) — lần đầu khoảng 1 phút…")
        r = subprocess.run([str(VPY), "-m", "pip", "install", "-e", str(ROOT),
                            "--quiet", "--disable-pip-version-check"], check=False, env=sanitized_env())
        if r.returncode != 0:
            say("❌ Cài dependencies THẤT BẠI — xem lỗi phía trên.")
            say("   Kiểm tra mạng rồi chạy lại; vẫn hỏng thì xoá thư mục .venv và chạy lại từ đầu.")
            sys.exit(1)


def port_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def wait_port(timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_busy():
            return True
        time.sleep(0.4)
    return False


def open_browser() -> None:
    try:
        if IS_WIN:
            os.startfile(URL)  # mở tab trình duyệt cục bộ
        else:
            webbrowser.open(URL)
    except Exception as e:  # noqa: BLE001 — không mở được browser không phải lỗi chết
        say(f"(không tự mở được trình duyệt: {e} — mở tay {URL})")


def check_env() -> None:
    say("── forge-agent --check ──")
    say("Python   :", sys.version.split()[0], "·", sys.executable)
    say(".venv    :", "có" if venv_ready() else "chưa có (tự tạo lần chạy đầu)")
    say("Deps     :", "OK" if deps_installed() else "sẽ cài lần chạy đầu (pip install -e .)")
    say("node/npx :", shutil.which("npx") or "không có (chỉ cần cho MCP stdio như Playwright/memory)")
    say("git      :", shutil.which("git") or "không có (checkpoint git + autocommit cần git)")
    say(f"Cổng {PORT}  :", "ĐANG BẬN — có thể server đang chạy sẵn" if port_busy() else "rảnh")
    try:
        sys.path.insert(0, str(ROOT))
        from engine import config
        say("Provider :", config.get_provider(), "·", config.get_model())
        say("LLM      :", "đã có credentials" if config.has_llm_credentials() else "demo (chưa có key)")
        say("Release  :", "BẬT" if config.is_release_mode() else "tắt")
    except Exception as e:  # noqa: BLE001 — check không được chết vì file config lỗi
        say("Config   : lỗi đọc —", e)
    say("Secure setup: python scripts/setup_keys.py")
    say("Listen   :", HOST, "(đặt FORGE_HOST=0.0.0.0 chỉ khi đã cấu hình release/proxy)")
    say("Hướng dẫn chi tiết: USER_GUIDE.md")


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--provider", choices=["openrouter", "google", "custom"])
    args, _ = ap.parse_known_args()
    ensure_utf8()
    if args.setup:
        sys.path.insert(0, str(ROOT))
        from scripts.setup_keys import main as secure_setup
        setup_args = (["--provider", args.provider] if args.provider else [])
        if args.release:
            setup_args.append("--release")
        return secure_setup(setup_args)
    if args.release:
        os.environ["FORGE_RELEASE_MODE"] = "1"
    if args.check:
        check_env()
        return 0

    say("╭──────────────────────────────────────────────────╮")
    say("│  ⚡ forge-agent — đang khởi động…                 │")
    say("╰──────────────────────────────────────────────────╯")
    setup_venv()
    sys.path.insert(0, str(ROOT))
    from engine import config
    from engine.auth import AuthStore
    users = AuthStore()
    if not users.has_users():
        if not sys.stdin.isatty():
            say("❌ Chưa có user. Chạy python scripts/setup_auth.py trong terminal tương tác.")
            return 1
        say("👤 Lần đầu cần tạo admin (email + password ≥16 ký tự; không có public registration).")
        from scripts.setup_auth import main as auth_setup
        rc = auth_setup([])
        if rc != 0:
            return rc
    if config.is_release_mode():
        if not config.has_any_llm_credentials() or not users.has_users():
            say("❌ RELEASE MODE chưa sẵn sàng: cần ít nhất một provider key + một user.")
            say("   Chạy: python scripts/setup_keys.py --release (hoặc scripts/setup_auth.py)")
            return 1
        say("🔒 Release mode: đăng nhập bắt buộc · Settings khóa · CORS same-origin.")
    if port_busy():
        say(f"⚠ Cổng {PORT} đã có server chạy — mở {URL} luôn (không khởi động bản thứ hai).")
        if not args.no_browser:
            open_browser()
        return 0
    say(f"③ Khởi động server {URL} · listen {HOST} … (Ctrl+C để dừng)")
    proc = subprocess.Popen(
        [str(VPY), "-m", "uvicorn", "server.main:app",
         "--host", HOST, "--port", str(PORT)],
        cwd=str(ROOT),
    )
    if not wait_port():
        say("❌ Server không lên sau 40s — chạy lại bằng PowerShell để xem lỗi chi tiết:")
        say(f"   {VPY} -m uvicorn server.main:app --port {PORT}")
        proc.terminate()
        return 1
    say("✓ Server đã lên · provider:", config.get_provider(), "· model:", config.get_model())
    if config.is_release_mode():
        say("  Đăng nhập bằng tài khoản email/Google đã được mời; bắt buộc HTTPS reverse-proxy.")
    else:
        say("  Chưa có key? DEMO MODE vẫn chạy. Cấu hình an toàn: python scripts/setup_keys.py")
    say("  Hướng dẫn đầy đủ từng bước: USER_GUIDE.md")
    if not args.no_browser:
        open_browser()
    try:
        return proc.wait()
    except KeyboardInterrupt:
        say("\nĐang dừng server… (dữ liệu phiên nằm ở data/ — không mất)")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
