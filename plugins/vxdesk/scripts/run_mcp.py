"""VxDesk plugin launcher: point the MCP server at the installed app's data.

When the VxDesk desktop app is installed, its workflows/templates live in
%LOCALAPPDATA%\\VxDesk. This shim sets VXDESK_DATA_DIR accordingly (unless the
user already set it) BEFORE importing the vxdesk package, then hands over to
the real MCP stdio server. Falls back to the repo data dir in dev setups.
"""

import os
import runpy
import sys
from pathlib import Path

BACKEND = r"D:/OneDrive/Documents/GitHub/vxdesk/VxDesk/backend"

if "VXDESK_DATA_DIR" not in os.environ:
    _localapp = os.environ.get("LOCALAPPDATA")
    if _localapp and (Path(_localapp) / "VxDesk").is_dir():
        os.environ["VXDESK_DATA_DIR"] = str(Path(_localapp) / "VxDesk")

sys.path.insert(0, BACKEND)
sys.argv = ["vxdesk-mcp"]
runpy.run_module("vxdesk.mcp_server", run_name="__main__")
