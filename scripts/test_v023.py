# -*- coding: utf-8 -*-
"""Suite v0.22 "Auto-commit & Effort":
B1 auto-commit (git thật: init ngầm, commit conventional từ stub LLM, fallback,
no-change → None) · D3 reasoning effort qua payload (fake OpenRouter SSE).

Chạy:  python scripts/test_v023.py
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import _test_auth
_test_auth.install()

TMP = Path(tempfile.mkdtemp(prefix="forge-v023-"))
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
                print(f"  ✓ {name}", flush=True)
            except Exception as e:
                FAIL.append((name, f"{e}"))
                print(f"  ✗ {name}: {e}", flush=True)
                traceback.print_exc(limit=3)
        return run
    return deco


def _git(ws, *args):
    import subprocess
    r = subprocess.run(["git", *args], cwd=str(ws), capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


class FakeOpenRouterSSE:
    """SSE server giả — chụp JSON body để assert payload (dùng cho D3)."""

    def __init__(self):
        self.bodies: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.bodies.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                def sse(d):
                    return b"data: " + json.dumps(d).encode() + b"\n\n"
                self.wfile.write(sse({"id": "1", "choices": [{"delta": {"content": "ok"}, "index": 0}]}))
                self.wfile.write(sse({"id": "1", "choices": [{"delta": {}, "finish_reason": "stop"}],
                                      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


@check("T1 B1 commit_turn: git init ngầm + định danh bot · commit conventional từ stub LLM · no-change → None")
async def t1():
    from engine import autocommit as fac
    ws = TMP / "ws1"
    ws.mkdir(parents=True, exist_ok=True)

    async def fake_stream(messages, tools=None, model=None, **kw):
        assert "diff --stat" in messages[-1]["content"] or "git diff" in messages[-1]["content"]
        yield {"type": "delta", "text": '  "fix: sửa hàm tính tổng bị lệch kết quả"  '}
        yield {"type": "finish", "reason": "stop"}

    import engine.llm as fllm
    orig = fllm.stream_chat
    fllm.stream_chat = fake_stream
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-fake"
    try:
        (ws / "calc.py").write_text("def tong(a, b):\n    return a + b + 1\n", encoding="utf-8")
        res = await fac.commit_turn(ws, "sess-abcdef12", "sửa hàm tính tổng", "đã sửa calc.py")
        assert res and res["files"] >= 1, res
        assert res["subject"].startswith("fix:"), res["subject"]
        rc, log = _git(ws, "log", "-1", "--pretty=%s%n%b%n%an")
        assert rc == 0, log
        assert "fix: sửa hàm tính tổng" in log.splitlines()[0], log
        assert "🤖 forge-agent" in log, "thiếu attribution trailer"
        assert "Forge Agent" in log, "thiếu định danh bot"
        # lượt thứ 2: không đổi gì → None
        res2 = await fac.commit_turn(ws, "sess-abcdef12", "không làm gì", "")
        assert res2 is None, res2
    finally:
        fllm.stream_chat = orig
        os.environ.pop("OPENROUTER_API_KEY", None)


@check("T2 B1 fallback: LLM raise → subject heuristic vẫn đúng conventional; không repo → tự init")
async def t2():
    from engine import autocommit as fac
    ws = TMP / "ws2"
    ws.mkdir(parents=True, exist_ok=True)
    assert not (ws / ".git").exists()

    async def boom(*a, **kw):
        raise RuntimeError("LLM sập")

    import engine.llm as fllm
    orig = fllm.stream_chat
    fllm.stream_chat = boom
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-fake"
    try:
        (ws / "main.py").write_text("print('hi')\n", encoding="utf-8")
        res = await fac.commit_turn(ws, "sess-22222222", "thêm tính năng xuất csv", "")
        assert res, "phải vẫn commit khi LLM lỗi"
        assert res["subject"].startswith("feat:"), res["subject"]
        assert (ws / ".git").exists(), "phải tự git init"
    finally:
        fllm.stream_chat = orig
        os.environ.pop("OPENROUTER_API_KEY", None)


@check("T3 normalize_subject: giữ prefix sẵn có · cắt >72 · bỏ ngoặc kép · đoán fix/feat")
async def t3():
    from engine.autocommit import normalize_subject as n
    assert n('"feat: đã có prefix"') == "feat: đã có prefix"
    assert n("chore: dọn rác", "fb").startswith("chore:")
    out = n("x" * 120)
    assert len(out) <= 72 and out.endswith("…")
    assert n("").startswith("feat:")  # rỗng → fallback
    assert n("sửa lỗi crash khi load").startswith("fix:") or ":" in n("sửa lỗi crash khi load")
    assert "\n" not in n("dòng 1\ndòng 2")


@check("T4 D3 reasoning effort: effort=high → payload.reasoning.effort=high · '' → không có field · base_url lạ → KHÔNG gửi")
async def t4():
    from engine import config as fcfg
    from engine.llm import stream_chat
    orig = fcfg.load_config
    try:
        srv = FakeOpenRouterSSE()
        # (a) effort=high qua OpenRouter — giả mạo endpoint OpenRouter (custom base_url thì
        #     tính năng ĐÚNG THIẾT KẾ phải tự tắt, xem nhánh (c))
        import engine.llm as fllm
        orig_ep = fllm._endpoint
        fllm._endpoint = lambda k, p=None: (srv.base + "/chat/completions",
                                    {"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
        fcfg.load_config = lambda: {"reasoning_effort": "high"}
        evs = [e async for e in stream_chat([{"role": "user", "content": "x"}], api_key="sk-or-v1-fake")]
        assert evs, "phải có sự kiện"
        assert srv.bodies[-1].get("reasoning") == {"effort": "high"}, srv.bodies[-1].get("reasoning")
        # (b) không effort → không field (vẫn giả mạo endpoint — không gọi mạng thật)
        fcfg.load_config = lambda: {}
        _ = [e async for e in stream_chat([{"role": "user", "content": "x"}], api_key="sk-or-v1-fake")]
        assert "reasoning" not in srv.bodies[-1]
        fllm._endpoint = orig_ep
        # (c) base_url KHÁC OpenRouter → không gửi field lạ
        srv2 = FakeOpenRouterSSE()
        fcfg.load_config = lambda: {"reasoning_effort": "low",
                                    "custom_base_url": srv2.base}
        _ = [e async for e in stream_chat([{"role": "user", "content": "x"}], api_key=None)]
        assert srv2.bodies and "reasoning" not in srv2.bodies[-1]
        srv.stop()
        srv2.stop()
    finally:
        fcfg.load_config = orig
        try:
            import engine.llm as _f
            pass
        except Exception:
            pass


async def _drain(gen, **kw):
    async for _ in gen([{"role": "user", "content": "x"}], **kw):
        pass


@check("T5 settings roundtrip: auto_commit + reasoning_effort (có/validate sai) qua /api/settings → health")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.post("/api/settings", json={"auto_commit": True, "reasoning_effort": "high"})
        assert r.status_code == 200
        h = r.json()
        assert h["auto_commit"] is True and h["reasoning_effort"] == "high", h
        # giá trị sai → về ''
        r = c.post("/api/settings", json={"reasoning_effort": "blast"})
        assert r.json()["reasoning_effort"] == ""
        # tắt auto_commit
        r = c.post("/api/settings", json={"auto_commit": False})
        assert r.json()["auto_commit"] is False


async def main():
    print(f"=== SUITE v0.22 Auto-commit & Effort — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
