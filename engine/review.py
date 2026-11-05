# -*- coding: utf-8 -*-
"""Review & diff — lệnh /review (code review theo diff) và /diff (xem diff), v0.12.

Nguồn diff (theo thứ tự):
1. Workspace là git repo  → ``git diff HEAD`` (mặc định), ``-- <file>``, hoặc ``A...B``.
2. Không repo nhưng có checkpoint của phiên (repo .ckpt-<sid>.git, branch ``forge``)
   → diff giữa commit ĐẦU phiên và hiện tại = toàn bộ thay đổi trong phiên.
3. Không có gì → ValueError với lời giải thích thân thiện.

Prompt /review: chuẩn Codex (6 tiêu chí bug, P0–P3, "prefer no finding over a weak
finding", loại bug pre-existing) + verdict template.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

DIFF_CAP = 40_000


async def _git(ws: Path, *args: str, git_dir: str | None = None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") or k in ("GIT_CONFIG_GLOBAL",)}
    if git_dir:
        env["GIT_DIR"] = git_dir
        env["GIT_WORK_TREE"] = str(ws)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(ws), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        return proc.returncode or 0, out.decode("utf-8", errors="replace")
    except (OSError, asyncio.TimeoutError):
        return 1, ""


async def is_repo(ws: Path) -> bool:
    rc, out = await _git(ws, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


async def _ckpt_first_commit(ws: Path, sid: str) -> str | None:
    from . import config
    repo = str(config.WORKSPACES_DIR / f".ckpt-{sid}.git")
    if not await asyncio.to_thread(Path(repo).exists):
        return None
    rc, out = await _git(ws, "rev-list", "--max-parents=0", "forge", git_dir=repo)
    first = out.strip().splitlines()[-1] if out.strip() else ""
    return first or None


_NO_FORGE = (".", ":(exclude).forge", ":(exclude).forge/**")


async def _ckpt_diff(ws: Path, sid: str) -> tuple[int, str]:
    from . import config
    repo = str(config.WORKSPACES_DIR / f".ckpt-{sid}.git")
    first = await _ckpt_first_commit(ws, sid)
    if not first:
        return 1, ""
    await _git(ws, "add", "-A", "--", ".", git_dir=repo)  # file mới (untracked) vào diff
    return await _git(ws, "diff", first, "--", *_NO_FORGE, git_dir=repo)


async def collect_diff(workspace: Path, sid: str | None = None,
                       arg: str = "") -> tuple[str, str]:
    """Trả về (diff_text, nguồn). raise ValueError nếu không có gì để xem."""
    arg = (arg or "").strip()
    repo = await is_repo(workspace)

    if arg and ".." in arg:  # ref range: main...feature
        if not repo:
            raise ValueError("Ref range cần workspace là git repo — hiện tại không phải.")
        rc, out = await _git(workspace, "diff", arg)
        if rc != 0 or not out.strip():
            raise ValueError(f"Không lấy được diff cho «{arg}» (repo sạch hoặc sai ref).")
        return _cap(out), f"git diff {arg}"

    if arg and " " not in arg and not arg.startswith("-"):  # 1 file
        rel = arg
        if repo:
            await _git(workspace, "add", "--intent-to-add", "-A")  # file mới vào diff
            rc, out = await _git(workspace, "diff", "HEAD", "--", rel)
            if rc == 0 and out.strip():
                return _cap(out), f"git diff HEAD -- {rel}"
        if sid:
            rc, out = await _ckpt_diff(workspace, sid)
            if rc == 0 and rel in out:
                return _cap(out), f"checkpoint phiên (lọc «{rel}» trong prompt)"
        raise ValueError(f"Không tìm thấy thay đổi nào cho «{rel}» "
                         "(chưa sửa file này, hoặc chưa có git repo/checkpoint).")

    # mặc định: mọi thay đổi chưa commit (repo) hoặc cả phiên (checkpoint)
    if repo:
        await _git(workspace, "add", "--intent-to-add", "-A")  # file mới vào diff
        rc, out = await _git(workspace, "diff", "HEAD", "--", *_NO_FORGE)
        if rc == 0 and out.strip():
            return _cap(out), "git diff HEAD (chưa commit)"
    if sid:
        rc, out = await _ckpt_diff(workspace, sid)
        if rc == 0 and out.strip():
            return _cap(out), "checkpoint phiên (toàn bộ thay đổi từ đầu phiên)"
    raise ValueError("Không có thay đổi nào để xem — working tree sạch "
                     "(hoặc workspace chưa có git repo/checkpoint nào).")


def build_prompt(diff: str, arg: str = "", source: str = "") -> str:
    focus = f"\n\nYÊU CẦU RIÊNG TỪ NGƯỜI DÙNG (ưu tiên): {arg.strip()}" if arg.strip() else ""
    return f"""Bạn là reviewer code senior. Review DIFF dưới đây (nguồn: {source or "working diff"}).
Có thể đọc file trong workspace để kiểm chứng ngữ cảnh quanh diff — KHÔNG sửa gì.
{focus}

CHỈ BÁO KHI THỎA 1 TRONG 6 TIÊU CHÍ BUG:
1) Sai logic / tính toán sai
2) Crash / edge case chưa xử lý (None, index ngoài range, parse fail)
3) Bảo mật (injection, path traversal, lộ secret, quyền)
4) Race condition / async sai thứ tự / quên await
5) Hiệu năng vô tình tồi (O(n²), N+1 query, leak tài nguyên)
6) API misuse (tham số sai, tài nguyên không đóng, return sai kiểu)

KHÔNG BÁO: bug có sẵn từ trước khi chưa có diff này (nếu nghiêm trọng, ghi 1 dòng
🟣 Pre-existing) · phong cách / đặt tên biến / comment · điều chưa xảy ra trong code.
Nguyên tắc: ƯA "không finding" HƠN finding yếu — không chắc thì đừng báo.

TRÌNH BÀY ĐÚNG TEMPLATE (markdown):
## Verdict: APPROVE | COMMENT | REQUEST_CHANGES
## Findings
- [P0|P1|P2|P3] <file>:<dòng> — <mô tả ngắn> → <gợi ý sửa 1 dòng>
  (P0 crash/bảo mật · P1 sai logic · P2 edge/hiệu năng · P3 cleanup.
   Không có finding → ghi "Không có finding nào.")
## Kiểm chứng
- 2–4 gạch đầu dòng: bạn đã xác minh thế nào (đọc file nào, trace luồng nào)
## Rủi ro còn lại
- 1–2 dòng, hoặc "không có"

=== DIFF ===
```diff
{diff}
```"""


def _cap(text: str) -> str:
    if len(text) <= DIFF_CAP:
        return text
    return text[:DIFF_CAP] + "\n… (diff cắt ở 40KB —review phần còn lại bằng cách chỉ định file)"
