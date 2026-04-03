from __future__ import annotations

from pathlib import Path

import streamlit as st

from tracer.ingestion.cloudwatch import (
    copy_local_file_to_store,
    fetch_cloudwatch_logs,
    write_upload_to_store,
)
from tracer.ingestion.parser import parse_and_store_traces
from tracer.ui import state
from tracer.ui.components.date_picker import render_date_picker
from tracer.ui.components.folder_picker import make_folder_picker
from tracer.ui.utils import clear_trace_query_param, label_with_help, new_store_dir

_SAMPLES_PATH = Path(__file__).resolve().parents[2] / "samples" / "logs.jsonl"


# ── Logo ─────────────────────────────────────────────────────────────

def _render_logo() -> None:
    st.markdown(
        '<div style="padding:4px 0 12px 0;line-height:1.1">'
        '<span style="font-size:1.5rem;font-weight:900;letter-spacing:-0.03em;color:#4fc3f7">g</span>'
        '<span style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em;color:#e0e0e0">Trace</span>'
        '<span style="font-size:1.5rem;font-weight:300;color:#9e9e9e;margin-left:6px">Monitor</span>'
        "</div>",
        unsafe_allow_html=True,
    )


# ── CloudWatch source ─────────────────────────────────────────────────

def _handle_cloudwatch_fetch(date_range: tuple) -> None:
    start_dt, end_dt = date_range
    with st.spinner("Fetching from CloudWatch..."):
        try:
            state.clear_data()
            clear_trace_query_param()
            store_dir = new_store_dir()
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


def _render_cloudwatch_source() -> None:
    date_range = render_date_picker()
    fetch = st.button("Fetch logs", type="primary", use_container_width=True)
    if fetch and date_range:
        _handle_cloudwatch_fetch(date_range)


# ── Local file source ─────────────────────────────────────────────────

def _render_file_upload() -> None:
    st.markdown(
        label_with_help(
            "Upload log file(s)",
            "Accepted: .jsonl  .log  .txt  .json\n"
            "Select multiple files at once (Ctrl/⌘+click)\n"
            "Multiple traces per file are supported",
        ),
        unsafe_allow_html=True,
    )
    _upload_key = st.session_state.get("_upload_key", 0)
    uploaded_files = st.file_uploader(
        "Upload Log file(s)",
        type=["jsonl", "log", "txt", "json"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"file_upload_{_upload_key}",
    )
    if st.session_state.get("_upload_flash"):
        st.success(st.session_state.pop("_upload_flash"))
    if uploaded_files:
        state.clear_data()
        clear_trace_query_param()
        store_dir = new_store_dir()
        combined = "\n".join(f.read().decode("utf-8") for f in uploaded_files)
        bulk_file = write_upload_to_store(combined, store_dir)
        summaries = parse_and_store_traces(bulk_file, store_dir)
        state.set_traces(summaries, store_dir)
        state.set_data_source("upload")
        label = f"{len(uploaded_files)} file(s)" if len(uploaded_files) > 1 else uploaded_files[0].name
        st.session_state["_upload_flash"] = f"Loaded {len(summaries)} traces from {label}"
        st.session_state["_upload_key"] = _upload_key + 1
        st.rerun()

    st.markdown("")
    st.markdown("")  # equalise bottom gap with Folder mode


def _render_folder_upload() -> None:
    st.markdown(
        label_with_help(
            "Browse folder",
            "Picks a folder from your filesystem\n"
            "Scans for: .jsonl  .log  .txt  .json\n"
            "All matching files are merged before parsing",
        ),
        unsafe_allow_html=True,
    )
    folder_picker = make_folder_picker()
    folder_result = folder_picker(key="folder_picker_widget", height=37)
    if folder_result is not None:
        result_id = f"{folder_result.get('file_count')}_{len(folder_result.get('content', ''))}"
        if st.session_state.get("_last_folder_id") != result_id:
            try:
                state.clear_data()
                clear_trace_query_param()
                store_dir = new_store_dir()
                bulk_file = write_upload_to_store(folder_result["content"], store_dir)
                summaries = parse_and_store_traces(bulk_file, store_dir)
                state.set_traces(summaries, store_dir)
                state.set_data_source("upload")
                st.session_state["_last_folder_id"] = result_id
                n = folder_result["file_count"]
                st.success(f"Loaded {len(summaries)} traces from {n} file(s)")
            except Exception as e:
                st.error(f"Failed to parse folder: {e}")


def _render_local_file_source() -> None:
    local_mode = st.segmented_control(
        "mode",
        options=["📄 File(s)", "📁 Folder"],
        default="📄 File(s)",
        label_visibility="collapsed",
        key="local_mode",
    ) or "📄 File(s)"

    st.markdown("")  # breathing room

    if local_mode == "📄 File(s)":
        _render_file_upload()
    else:
        _render_folder_upload()


# ── Sample button ─────────────────────────────────────────────────────

def _render_sample_button() -> None:
    if st.button("🧪", key="sample_btn", help="Load sample logs", type="secondary"):
        if _SAMPLES_PATH.exists():
            state.clear_data()
            clear_trace_query_param()
            store_dir = new_store_dir()
            bulk_file = copy_local_file_to_store(str(_SAMPLES_PATH), store_dir)
            summaries = parse_and_store_traces(bulk_file, store_dir)
            state.set_traces(summaries, store_dir)
            state.set_data_source("sample")
            st.success(f"Loaded {len(summaries)} traces from sample file")
        else:
            st.error(f"Sample file not found: {_SAMPLES_PATH}")


# ── Public entry point ────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        _render_logo()
        st.markdown("---")

        source = st.radio(
            "Data source",
            options=["CloudWatch", "Local file"],
            index=1,
            key="source_radio",
            horizontal=True,
        )

        if source == "CloudWatch":
            _render_cloudwatch_source()
        else:
            _render_local_file_source()
            _render_sample_button()
