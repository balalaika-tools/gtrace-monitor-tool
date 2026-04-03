from __future__ import annotations

import streamlit as st

from tracer.ui import state
from tracer.ui.components.filter_bar import render_filter_bar
from tracer.ui.components.trace_detail import render_trace_detail
from tracer.ui.components.trace_list import render_trace_list, render_trace_metrics
from tracer.ui.utils import sync_selected_trace_from_query


def _render_empty_state() -> None:
    st.markdown(
        '<div style="padding:4px 0 24px 0;line-height:1.1">'
        '<span style="font-size:2rem;font-weight:900;letter-spacing:-0.03em;color:#4fc3f7">g</span>'
        '<span style="font-size:2rem;font-weight:700;letter-spacing:-0.02em;color:#e0e0e0">Trace</span>'
        '<span style="font-size:2rem;font-weight:300;color:#9e9e9e;margin-left:7px">Monitor</span>'
        "</div>",
        unsafe_allow_html=True,
    )
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


def _render_trace_list_view() -> None:
    st.markdown("## Traces")
    render_trace_metrics(state.get_filtered_traces())
    st.markdown("---")
    render_filter_bar(state.get_traces())
    st.caption(f"{len(state.get_filtered_traces())} of {len(state.get_traces())} traces shown")
    st.markdown("---")
    render_trace_list(state.get_filtered_traces())


def render_main_content() -> None:
    sync_selected_trace_from_query()

    selected_trace = None
    if state.get_selected_trace_id():
        with st.spinner("Loading trace..."):
            selected_trace = state.load_selected_trace()

    if selected_trace:
        render_trace_detail(selected_trace)
    elif state.get_traces():
        _render_trace_list_view()
    else:
        _render_empty_state()
