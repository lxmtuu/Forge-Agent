"""Reproduce Windows charmap crash: locale-dependent file writes with Vietnamese text."""
import sys
sys.path.insert(0, ".")

from engine.session import SessionStore
from engine import config, mcp

store = SessionStore()
try:
    s = store.create()
    s.messages.append({"role": "user", "content": "Viết game snake bằng HTML/JS rồi mở thử"})
    store.save(s)
    print("SESSION SAVE: OK")
except UnicodeEncodeError as e:
    print("SESSION SAVE: ❌ CRASH —", e)
    sys.exit(1)

try:
    cfg_path = config.CONFIG_FILE
    config.save_config({"model": "x"})
    print("CONFIG SAVE: OK")
except UnicodeEncodeError as e:
    print("CONFIG SAVE: ❌", e)

try:
    mcp.save_servers([{"name": "s", "command": "x", "args": [], "enabled": True}])
    print("MCP SAVE: OK")
except UnicodeEncodeError as e:
    print("MCP SAVE: ❌", e)
