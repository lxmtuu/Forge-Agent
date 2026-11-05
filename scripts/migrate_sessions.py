"""Gán session legacy owner_id rỗng cho một user đã tồn tại (dry-run mặc định).

  python scripts/migrate_sessions.py --email admin@example.com
  python scripts/migrate_sessions.py --email admin@example.com --apply

Chỉ đổi metadata owner_id; không đọc/in nội dung hội thoại hay workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import config
from engine.auth import AuthStore, normalize_email


def migrate(email: str, apply: bool = False) -> tuple[int, list[str]]:
    """Trả (số legacy, các session ID); chỉ ghi khi apply=True."""
    users = AuthStore()
    target = users.get_by_email(normalize_email(email))
    if target is None:
        raise ValueError("User không tồn tại — tạo/mời user trước")
    if not target.enabled:
        raise ValueError("User đang bị disable")
    rows: list[tuple[Path, dict]] = []
    for path in sorted(config.SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Không đọc được session {path.name}: {exc}") from exc
        if isinstance(data, dict) and data.get("id") and not data.get("owner_id"):
            rows.append((path, data))
    ids = [str(data["id"]) for _, data in rows]
    print(f"Target: {target.email} ({target.id}) · legacy sessions: {len(rows)}")
    for _, data in rows:
        print(f"  - {data['id']} · {str(data.get('title') or 'New session')[:80]}")
    if not apply:
        print("DRY-RUN: không file nào bị đổi. Thêm --apply để gán owner.")
        return len(rows), ids
    backup = config.DATA_DIR / "session-migration-backup" / str(int(time.time()))
    for path, data in rows:
        if rows:
            backup.mkdir(parents=True, exist_ok=True)
        backup_file = backup / path.name
        backup_file.write_bytes(path.read_bytes())
        try:
            backup_file.chmod(0o600)
        except OSError:
            pass
        data["owner_id"] = target.id
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
    if rows:
        print(f"✓ Đã gán {len(rows)} session. Backup metadata/hội thoại: {backup}")
    return len(rows), ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        migrate(args.email, args.apply)
        return 0
    except (ValueError, OSError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
