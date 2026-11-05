"""Suite v0.37 — responsive app shell, role-aware Settings and async UI guards.

Behavioral browser coverage lives in scripts/browser_v037.cjs (37 checks).
This Python gate keeps the corresponding source/production artifacts verifiable.
Chạy: python scripts/test_v037.py
"""
from __future__ import annotations

import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name):
    def deco(fn):
        def run():
            try:
                fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as exc:  # noqa: BLE001 — test harness gom đủ lỗi
                FAIL.append((name, str(exc)))
                print(f"  ✗ {name}: {exc}", flush=True)
                traceback.print_exc(limit=4)
        return run
    return deco


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@check("T1 Version 0.38.0 nhất quán package/server/engine/MCP/LSP")
def t1():
    for name in ("pyproject.toml", "server/main.py", "engine/__init__.py", "engine/mcp.py", "engine/lsp.py"):
        assert "0.38.0" in read(name), name


@check("T2 App shell có topbar, Workspace drawer và keyboard/touch controls")
def t2():
    app = read("web/src/App.tsx")
    sidebar = read("web/src/components/Sidebar.tsx")
    files = read("web/src/components/FilesPane.tsx")
    for marker in ("chat-topbar", "showWorkspace", "workspace-scrim", "Mở Workspace", "Đóng vùng Workspace"):
        assert marker in app, marker
    for marker in ("session-main", "Đóng sidebar", "Close sidebar", "Tìm phiên", "Search sessions"):
        assert marker in sidebar, marker
    for marker in ("Đóng panel Workspace", "Close Workspace panel", "aria-expanded={open}",
                   "Lệnh terminal", "Terminal command"):
        assert marker in files, marker


@check("T3 Late session responses bị chặn cho timeline/tree/context và state user được dọn")
def t3():
    app = read("web/src/App.tsx")
    for marker in ("if (sidRef.current !== id) return", "if (sidRef.current === id) setTree(next)",
                   "if (sidRef.current === id) setCtx(stats)", "userRef.current?.id === owner",
                   "savedModelsRef.current = {}"):
        assert marker in app, marker


@check("T4 Model selector bỏ PATCH no-op nhưng giữ trạng thái saving/saved/error")
def t4():
    app = read("web/src/App.tsx")
    for marker in ("savedModelsRef.current[sessionId] === selected", "setModelSaveState('saving')",
                   "setModelSaveState('saved')", "setModelSaveState('error')"):
        assert marker in app, marker
    assert "Model của phiên đã lưu:" not in app


@check("T5 Settings có fixed footer, focus trap, reset scroll và Max tokens fail-closed")
def t5():
    settings = read("web/src/components/SettingsModal.tsx")
    for marker in ("settings-layout", "settings-footer", "tryCloseRef", "previous?.focus()",
                   "document.getElementById('settings-panel')?.scrollTo", "Number.isInteger(mt)",
                   "Max tokens phải là số nguyên từ 256 đến 65536."):
        assert marker in settings, marker


@check("T6 Member chỉ thấy Appearance/Skills/Audit; theme local không nới ACL")
def t6():
    settings = read("web/src/components/SettingsModal.tsx")
    for marker in ("props.isAdmin ? 'conn' : 'ui'", "['ui', 'skl', 'audit'].includes(t.id)",
                   "theme-options", "props.isAdmin && <button"):
        assert marker in settings, marker
    assert "require_admin" in read("server/main.py")


@check("T7 Production JS/CSS chứa shell mới và không chứa smoke credential")
def t7():
    assets = ROOT / "server" / "static" / "assets"
    js = "\n".join(p.read_text(encoding="utf-8") for p in assets.glob("*.js"))
    css = "\n".join(p.read_text(encoding="utf-8") for p in assets.glob("*.css"))
    for marker in ("Bạn muốn xây dựng điều gì?", "Đóng panel Workspace",
                   "Max tokens phải là số nguyên từ 256 đến 65536.", "Tuỳ chọn theo quyền member"):
        assert marker in js, marker
    for marker in (".settings-layout", ".workspace-scrim", ".session-main", ".composer-toolbar"):
        assert marker in css, marker
    for secret in ("smoke-fake-password-036-not-real", "smoke-member-fake-036-not-real",
                   "sk-or-v1-FAKE", "AIza-FAKE"):
        assert secret not in js, secret


@check("T8 Browser regression thật được lưu: responsive/a11y/race/validation/member")
def t8():
    browser = read("scripts/browser_v037.cjs")
    for marker in ("Settings footer remains fixed", "Invalid max tokens keeps dialog open",
                   "Blur with unchanged model sends no PATCH", "Member sees exactly Appearance",
                   "Workspace scrim closes drawer", "Late GET cannot replace current session model",
                   "Race-test session cleanup preserves CSRF boundary", "process.exit(1)"):
        assert marker in browser, marker


def main():
    print("=== SUITE v0.37 Responsive UX + role-aware Settings + async guards ===")
    for test in (t1, t2, t3, t4, t5, t6, t7, t8):
        test()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
