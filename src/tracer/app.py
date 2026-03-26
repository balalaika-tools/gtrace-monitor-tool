from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure src/ is on the path for local dev
_src = str(Path(__file__).resolve().parents[1])
if _src not in sys.path:
    sys.path.insert(0, _src)

from tracer.ingestion.cloudwatch import (
    copy_local_file_to_store,
    fetch_cloudwatch_logs,
    write_upload_to_store,
)
from tracer.ingestion.parser import parse_and_store_traces
from tracer.ui import state
from tracer.ui.components.date_picker import render_date_picker
from tracer.ui.components.filter_bar import render_filter_bar
from tracer.ui.components.trace_detail import render_trace_detail
from tracer.ui.components.trace_list import render_trace_list, render_trace_metrics
from tracer.ui.styles.theme import apply_theme

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _PROJECT_ROOT / ".cache" / "traces"
_TRACE_QUERY_PARAM = "trace_id"


def _new_store_dir() -> str:
    """Create and return a fresh timestamped store directory under .cache/traces/.

    Wipes all existing subdirectories first to prevent orphans from previous sessions.
    """
    import shutil
    from datetime import datetime

    if _CACHE_DIR.exists():
        shutil.rmtree(_CACHE_DIR, ignore_errors=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    store = _CACHE_DIR / ts
    store.mkdir(parents=True, exist_ok=True)
    return str(store)


def _clear_trace_query_param():
    if _TRACE_QUERY_PARAM in st.query_params:
        del st.query_params[_TRACE_QUERY_PARAM]


def _sync_selected_trace_from_query():
    trace_id = st.query_params.get(_TRACE_QUERY_PARAM)
    if isinstance(trace_id, list):
        trace_id = trace_id[0] if trace_id else None
    if trace_id:
        state.set_selected_trace_id(trace_id)


# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agentic Trace Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
state.init_state()


# ── Sidebar: data source ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Agentic Trace Monitor")
    st.markdown("---")

    source = st.radio(
        "Data source",
        options=["CloudWatch", "Local file"],
        index=1,
        key="source_radio",
        horizontal=True,
    )

    if source == "CloudWatch":
        date_range = render_date_picker()
        fetch = st.button("Fetch logs", type="primary", use_container_width=True)

        if fetch and date_range:
            start_dt, end_dt = date_range
            with st.spinner("Fetching from CloudWatch..."):
                try:
                    state.clear_data()
                    _clear_trace_query_param()
                    store_dir = _new_store_dir()
                    result = fetch_cloudwatch_logs(
                        start_dt,
                        end_dt,
                        store_dir,
                        progress_callback=lambda n, p: st.caption(f"Page {p} — {n} events"),
                    )
                    summaries = parse_and_store_traces(result.bulk_file, store_dir)
                    state.set_traces(summaries, store_dir)
                    state.set_data_source("cloudwatch")
                    st.success(f"Loaded {len(summaries)} traces from {result.event_count} events")
                    if result.truncated:
                        st.warning(
                            f"Fetch was capped at {result.limit:,} events. "
                            "Try a narrower date range to see all data. "
                            "You can adjust MAX_LOG_EVENTS in your .env."
                        )
                except Exception as e:
                    st.error(f"Failed to fetch logs: {e}")

    else:  # Local file
        uploaded = st.file_uploader(
            "Upload JSONL log file",
            type=["jsonl", "log", "txt", "json"],
            key="file_upload",
        )
        use_sample = st.button(
            "Use sample logs (logs.jsonl)",
            type="secondary",
            use_container_width=True,
        )

        if uploaded is not None:
            upload_id = f"{uploaded.name}_{uploaded.size}"
            if st.session_state.get("_last_upload_id") != upload_id:
                state.clear_data()
                _clear_trace_query_param()
                store_dir = _new_store_dir()
                content = uploaded.read().decode("utf-8")
                bulk_file = write_upload_to_store(content, store_dir)
                summaries = parse_and_store_traces(bulk_file, store_dir)
                state.set_traces(summaries, store_dir)
                state.set_data_source("upload")
                st.session_state["_last_upload_id"] = upload_id
                st.success(f"Loaded {len(summaries)} traces")

        if use_sample:
            sample_path = Path(__file__).resolve().parent / "samples" / "logs.jsonl"
            if sample_path.exists():
                state.clear_data()
                _clear_trace_query_param()
                store_dir = _new_store_dir()
                bulk_file = copy_local_file_to_store(str(sample_path), store_dir)
                summaries = parse_and_store_traces(bulk_file, store_dir)
                state.set_traces(summaries, store_dir)
                state.set_data_source("sample")
                st.success(f"Loaded {len(summaries)} traces from sample file")
            else:
                st.error(f"Sample file not found: {sample_path}")


# ── Main content ─────────────────────────────────────────────────────
_sync_selected_trace_from_query()

# Load full trace from disk only when viewing detail
_selected_trace = None
if state.get_selected_trace_id():
    with st.spinner("Loading trace..."):
        _selected_trace = state.load_selected_trace()

if _selected_trace:
    render_trace_detail(_selected_trace)
elif state.get_traces():
    st.markdown("## Traces")
    render_trace_metrics(state.get_filtered_traces())
    st.markdown("---")
    render_filter_bar(state.get_traces())
    st.caption(f"{len(state.get_filtered_traces())} of {len(state.get_traces())} traces shown")
    st.markdown("---")
    render_trace_list(state.get_filtered_traces())
else:
    # Empty state
    st.markdown("## Agentic Trace Monitor")
    st.markdown(
        """
        <div style="text-align:center; padding:60px 20px; color:#9e9e9e;">
            <div style="font-size:3rem; margin-bottom:16px;">🔍</div>
            <div style="font-size:1.2rem; margin-bottom:8px;">No traces loaded</div>
            <div style="font-size:0.9rem;">
                Use the sidebar to fetch logs from <b>CloudWatch</b> or upload a local <b>JSONL</b> file.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
