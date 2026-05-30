"""Sidebar entry point for the local Builder supervisor panel."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from tools.keep_awake import get_keep_awake_status

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_PANEL_SCRIPT = PROJECT_ROOT / "tools" / "supervisor_control_panel.py"


def _format_awake_status(status: dict[str, Any]) -> str:
    if status.get("running"):
        pid = int(status.get("pid", 0) or 0)
        return f"Anti-veille actif · PID {pid}" if pid > 0 else "Anti-veille actif"
    return "Anti-veille inactif · géré par le panel"


def _creationflags_kwargs() -> dict[str, int]:
    if sys.platform != "win32":
        return {}
    return {
        "creationflags": int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        ),
    }


def _panel_python_executable() -> str:
    bundled = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if bundled.exists():
        return str(bundled)
    return sys.executable


def launch_supervisor_panel() -> int:
    process = subprocess.Popen(
        [_panel_python_executable(), str(SUPERVISOR_PANEL_SCRIPT)],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **_creationflags_kwargs(),
    )
    return int(process.pid or 0)


def render_keeper_mode_control() -> dict[str, Any]:
    status = get_keep_awake_status()

    st.sidebar.markdown('<div class="bc-sidebar-section">Keeper Mode</div>', unsafe_allow_html=True)
    st.sidebar.caption(_format_awake_status(status))
    if st.sidebar.button(
        "Ouvrir Keeper Panel",
        key="keeper_mode_open_panel",
        type="primary",
        width="stretch",
    ):
        try:
            pid = launch_supervisor_panel()
            if pid > 0:
                st.sidebar.success(f"Keeper Panel ouvert · PID {pid}")
            else:
                st.sidebar.success("Keeper Panel demandé.")
        except Exception as exc:
            logger.exception("Failed to open Keeper Panel")
            st.sidebar.error(f"Keeper Panel non ouvert: {exc}")

    return status
