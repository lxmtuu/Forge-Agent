"""Headless smoke test cho Forge TUI dùng Textual pilot."""
import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> None:
    from tui.app import ForgeTUI

    app = ForgeTUI()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # 1) sessions đã nạp
        assert app.sid is not None, "session không được tạo/chọn"
        # 2) gõ lệnh /help
        app.query_one("#prompt").value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        # 3) gửi nhiệm vụ (demo mode — không cần key)
        app.query_one("#prompt").value = "xin chào TUI"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if not app.busy:
                break
            await asyncio.sleep(0.1)
        assert not app.busy, "turn chưa xong"
        # 4) files tree + status tồn tại
        app.query_one("#files")
        app.query_one("#status")
        chat = app.query_one("#chat")
        assert len(chat.children) > 0, "chat trống"
    print("TUI SMOKE TEST: OK ✅ (session, /help, demo turn, widgets)")


asyncio.run(main())
