# -*- coding: utf-8 -*-
"""Suite v0.24 "Worktree isolation" (B2):
fork từ snapshot (archive, trạng thái nhất quán) · worktree make/diff/merge/discard
(git thật) · spawn_subagent isolation=worktree (stub LLM) · REST list.

Chạy:  python scripts/test_v025.py
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v025-"))
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


async def _setup_ckpt(sid: str, ws: Path, files: dict[str, str]) -> None:
    """Ghi file + snapshot checkpoint cho phiên."""
    from engine import checkpoints as fckpt
    ws.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (ws / name).write_text(content, encoding="utf-8")
    ck = await fckpt.snapshot(sid, ws, "setup")
    assert ck, "snapshot phải thành công (git có sẵn)"


def make_store():
    from engine.session import SessionStore
    return SessionStore()


@check("T1 fork từ snapshot: file đổi SAU snapshot không lọt vào bản fork (trạng thái nhất quán)")
async def t1():
    from engine import checkpoints as fckpt
    store = make_store()
    sid = store.create().id
    ws = store.workspace(sid)
    await _setup_ckpt(sid, ws, {"a.py": "V1\n"})
    (ws / "a.py").write_text("V2-đang-ghi-dở\n", encoding="utf-8")  # đổi sau snapshot
    ns = store.fork(sid)
    assert ns is not None
    fork_ws = store.workspace(ns.id)
    assert (fork_ws / "a.py").read_text(encoding="utf-8").startswith("V1"), \
        "fork phải lấy từ SNAPSHOT (V1), không phải file đang ghi dở (V2)"
    assert not (fork_ws / ".git").exists()
    # phiên KHÔNG có checkpoint → fallback copytree nguyên trạng thái
    sid2 = store.create().id
    ws2 = store.workspace(sid2)
    ws2.mkdir(parents=True, exist_ok=True)
    (ws2 / "b.txt").write_text("live\n", encoding="utf-8")
    ns2 = store.fork(sid2)
    assert (store.workspace(ns2.id) / "b.txt").exists(), "fallback copytree phải hoạt động"
    _ = fckpt  # noqa: F841


@check("T2 worktree vòng đời: make (bản sao từ snapshot) → sửa trong wt → diff_stat → merge về cha → discard sạch")
async def t2():
    from engine import checkpoints as fckpt
    from engine import worktree as fwt
    store = make_store()
    sid = store.create().id
    ws = store.workspace(sid)
    await _setup_ckpt(sid, ws, {"app.py": "print('cha')\n", "keep.txt": "giữ\n"})
    sub_sid = "sub-t2"
    wt_s = await fwt.make(sid, sub_sid)
    assert wt_s, "make phải tạo được worktree"
    wt = Path(wt_s)
    assert (wt / "app.py").read_text(encoding="utf-8") == "print('cha')\n", "wt phải là bản sao"
    # sửa + XOÁ trong wt — cha không đổi
    (wt / "app.py").write_text("print('sub đã sửa')\n", encoding="utf-8")
    (wt / "new.txt").write_text("mới từ sub\n", encoding="utf-8")
    (wt / "keep.txt").unlink()
    assert (ws / "app.py").read_text(encoding="utf-8") == "print('cha')\n", "cha phải bất động!"
    # diff theo branch iso/ của repo cha — không phụ thuộc snapshot của sub
    stat = await fwt.diff_stat(sub_sid, sid, wt)
    assert "app.py" in stat and "new.txt" in stat and "keep.txt" in stat, stat
    # merge về cha
    res = await fwt.merge(sub_sid, sid, sid, ws)
    assert res["ok"], res
    assert res["files"] >= 2
    assert (ws / "app.py").read_text(encoding="utf-8") == "print('sub đã sửa')\n"
    assert (ws / "new.txt").read_text(encoding="utf-8") == "mới từ sub\n"
    assert not (ws / "keep.txt").exists(), "phép xoá trong wt cũng phải được gộp"
    await fckpt.snapshot(sid, ws, "merge wt")  # cha snapshot lại (undo được)
    # discard
    res = await fwt.discard(sub_sid, sid)
    assert res["ok"] and res["removed"], res
    assert not wt.exists() and not Path(str(fwt._repo(sub_sid))).exists()
    rows = await fwt.list_all()
    assert all(r["session"] != sub_sid for r in rows)


@check("T3 spawn_subagent isolation=worktree: sub chạy trong wt (không phải ws cha) · summary có hướng gộp/bỏ · shared giữ nguyên")
async def t3():
    import engine.agent as fagent
    store = make_store()
    sid = store.create().id
    ws = store.workspace(sid)
    await _setup_ckpt(sid, ws, {"x.py": "1\n"})

    seen: list[str] = []

    async def fake_send(self, task, *a, **kw):
        seen.append(str(self.workspace))
        yield {"type": "assistant_message", "content": f"done tại {self.workspace}"}
        yield {"type": "turn_end", "usage": None}

    orig_send = fagent.Agent.send
    fagent.Agent.send = fake_send
    try:
        ag = fagent.Agent(store, sid)
        evs = [e async for e in ag._run_subagent("tc1", "việc cô lập", None, "worktree")]
        sub_sid = next(e["session_id"] for e in evs if e["type"] == "subagent_started")
        assert seen and seen[0] != str(ws) and "wt-" in seen[0], seen
        done = next(e for e in evs if e["type"] == "subagent_done")
        assert "Cô lập worktree" in done["summary"] and "/worktree merge" in done["summary"], done["summary"][:400]
        # pointer phiên sub phải trỏ vào wt (web mở phiên sub thấy đúng thư mục)
        ptr = (os.environ["FORGE_DATA_DIR"] + "/workspaces/" + sub_sid + ".path")
        assert "wt-" in Path(ptr).read_text(encoding="utf-8")
        # dọn wt vừa tạo
        from engine import worktree as fwt
        await fwt.discard(sub_sid, sid)
        # shared → workspace == cha
        seen.clear()
        _ = [e async for e in ag._run_subagent("tc2", "việc chung", None, "shared")]
        assert seen == [str(ws)], seen
    finally:
        fagent.Agent.send = orig_send


@check("T4 REST worktree: GET /api/worktrees shape · merge với phiên cha lạ → 404")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.get("/api/worktrees")
        assert r.status_code == 200 and "worktrees" in r.json()
        assert c.post("/api/worktrees/zzz/merge", params={"sid": "khong-co"}).status_code == 404
        assert c.delete("/api/worktrees/zzz", params={"sid": "khong-co"}).status_code == 404


async def main():
    print(f"=== SUITE v0.24 Worktree isolation — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
