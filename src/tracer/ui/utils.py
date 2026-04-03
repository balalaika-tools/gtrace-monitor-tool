from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import streamlit as st

from tracer.core.settings import get_settings

_TRACE_QUERY_PARAM = "trace_id"


def label_with_help(label: str, tooltip: str) -> str:
    safe = tooltip.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return (
        f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px;">'
        f'<span style="font-size:0.82rem;color:#e0e0e0;font-weight:500;">{label}</span>'
        f'<span class="help-icon">?'
        f'<span class="help-tooltip">{safe}</span>'
        f'</span></div>'
    )


def new_store_dir() -> str:
    """Create and return a fresh timestamped store directory under CACHE_DIR.

    Wipes all existing subdirectories first to prevent orphans from previous sessions.
    """
    cache_dir = get_settings().cache_dir
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    store = cache_dir / ts
    store.mkdir(parents=True, exist_ok=True)
    return str(store)


def clear_trace_query_param() -> None:
    if _TRACE_QUERY_PARAM in st.query_params:
        del st.query_params[_TRACE_QUERY_PARAM]


def sync_selected_trace_from_query() -> None:
    trace_id = st.query_params.get(_TRACE_QUERY_PARAM)
    if isinstance(trace_id, list):
        trace_id = trace_id[0] if trace_id else None
    if trace_id:
        from tracer.ui import state
        state.set_selected_trace_id(trace_id)
