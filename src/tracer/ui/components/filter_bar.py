from __future__ import annotations

import streamlit as st

from tracer.models.filters import FilterState, get_filterable_keys
from tracer.models.trace import TraceSummary
from tracer.ui import state


def render_filter_bar(summaries: list[TraceSummary]):
    """Render the filter bar in the main content area."""
    fs = state.get_filter_state()
    available_keys = get_filterable_keys(summaries)

    # Active filters as inline pills
    if fs.is_active:
        cols = st.columns([6, 1])
        with cols[0]:
            pills_html = ""
            for i, f in enumerate(fs.filters):
                pills_html += (
                    f'<span style="display:inline-block; background:#4fc3f718; border:1px solid #4fc3f733; '
                    f'color:#4fc3f7; padding:4px 12px; border-radius:16px; margin-right:8px; '
                    f'font-size:0.85rem;">'
                    f'<b>{f.key}</b> = {f.value}'
                    f'</span>'
                )
            st.markdown(pills_html, unsafe_allow_html=True)
        with cols[1]:
            if st.button("Clear filters", type="secondary", use_container_width=True):
                fs.clear()
                state.set_filter_state(fs)
                st.rerun()

    # Add filter row
    col_key, col_val, col_btn = st.columns([2, 4, 1])

    with col_key:
        filter_key = st.selectbox(
            "Filter by",
            options=[""] + available_keys,
            key="new_filter_key",
            format_func=lambda x: "Select key..." if x == "" else x,
        )

    with col_val:
        filter_value = ""
        if filter_key:
            unique_values = _get_unique_values(summaries, filter_key)
            filter_value = st.selectbox(
                "Value",
                options=[""] + unique_values,
                key="new_filter_value",
                format_func=lambda x: "Select value..." if x == "" else x,
            )
        else:
            st.selectbox(
                "Value",
                options=[""],
                disabled=True,
                key="new_filter_value_disabled",
                format_func=lambda _: "Select a key first",
            )

    with col_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button(
            "Apply",
            type="primary",
            disabled=not (filter_key and filter_value),
            use_container_width=True,
        ):
            fs.add(filter_key, filter_value)
            state.set_filter_state(fs)
            st.rerun()


def _get_unique_values(summaries: list[TraceSummary], key: str) -> list[str]:
    """Get unique values for a given key across all trace summaries."""
    values: set[str] = set()
    for s in summaries:
        if key == "trace_id":
            values.add(s.trace_id)
        elif key == "status":
            values.add(s.status)
        else:
            val = s.tags.get(key)
            if val is not None:
                values.add(str(val))
    return sorted(values)
