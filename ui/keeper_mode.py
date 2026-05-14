"""Sidebar controls for the local Windows keep-awake guard."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from tools.keep_awake import get_keep_awake_status, start_background, stop_background

logger = logging.getLogger(__name__)

KEEPER_INTERVAL_SECONDS = 600


def _format_keeper_status(status: dict[str, Any]) -> str:
    if status.get("running"):
        pid = int(status.get("pid", 0) or 0)
        return f"Actif · PID {pid}" if pid > 0 else "Actif"
    return "Inactif"


def render_keeper_mode_control() -> dict[str, Any]:
    status = get_keep_awake_status()
    running = bool(status.get("running"))

    st.sidebar.markdown('<div class="bc-sidebar-section">Keeper Mode</div>', unsafe_allow_html=True)
    st.sidebar.caption(_format_keeper_status(status))
    col_start, col_stop = st.sidebar.columns(2)

    with col_start:
        if st.button(
            "Start Keeper Mode",
            disabled=running,
            key="keeper_mode_start",
            type="primary" if not running else "secondary",
            use_container_width=True,
        ):
            try:
                status = start_background(interval_seconds=KEEPER_INTERVAL_SECONDS)
                if status.get("running"):
                    st.sidebar.success("Keeper Mode actif.")
                else:
                    st.sidebar.warning("Keeper Mode demandé, statut non confirmé.")
                st.rerun()
            except Exception as exc:
                logger.exception("Failed to start Keeper Mode")
                st.sidebar.error(f"Keeper Mode non démarré: {exc}")

    with col_stop:
        if st.button(
            "Stop",
            disabled=not running,
            key="keeper_mode_stop",
            type="secondary",
            use_container_width=True,
        ):
            try:
                status = stop_background()
                st.sidebar.success("Keeper Mode arrêté.")
                st.rerun()
            except Exception as exc:
                logger.exception("Failed to stop Keeper Mode")
                st.sidebar.error(f"Keeper Mode non arrêté: {exc}")

    return status
