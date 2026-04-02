from __future__ import annotations

import streamlit as st

from tracer.core.settings import get_settings
from tracer.models.trace import TraceSummary
from tracer.ui import state
from tracer.ui.styles.theme import metric_card, status_badge, tag_pill


def render_trace_metrics(summaries: list[TraceSummary]):
    """Render summary metric cards."""
    total = len(summaries)
    errors = sum(1 for s in summaries if s.status == "error")
    ok = total - errors

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(metric_card("Total Traces", str(total)), unsafe_allow_html=True)
    with col2:
        st.markdown(metric_card("Successful", f'<span style="color:#66bb6a">{ok}</span>'), unsafe_allow_html=True)
    with col3:
        st.markdown(metric_card("Errors", f'<span style="color:#ef5350">{errors}</span>'), unsafe_allow_html=True)


def render_trace_list(summaries: list[TraceSummary]):
    """Render the trace card list."""
    if not summaries:
        st.info("No traces found. Adjust date range or filters.")
        return

    # Active filter keys — show their values inline
    fs = state.get_filter_state()
    active_keys = fs.active_keys

    # Trace cards
    for summary in summaries:
        _render_trace_row(summary, active_keys)


def _on_select_trace(trace_id: str):
    state.set_selected_trace_id(trace_id)
    st.query_params["trace_id"] = trace_id


def _render_trace_row(summary: TraceSummary, active_keys: list[str]):
    """Render a single clickable trace card."""
    tag_html = ""
    for key in active_keys:
        val = summary.tags.get(key)
        if val:
            tag_html += tag_pill(key, _shorten(str(val), 36))

    for key, val in summary.tags.items():
        if key not in active_keys and val:
            tag_html += tag_pill(key, _shorten(str(val), 36))

    s = get_settings()
    cost = (
        summary.input_tokens * s.price_input
        + summary.output_tokens * s.price_output
        + summary.cache_creation_tokens * s.price_cache_creation
        + summary.cache_read_tokens * s.price_cache_read
    ) / 1_000_000
    cost_str = f"${cost:.4f}" if summary.total_tokens else "—"

    started = summary.started_at.strftime("%Y-%m-%d %H:%M:%S") if summary.started_at else "—"
    duration = _fmt_duration(summary.duration_ms)
    status_html = status_badge(summary.status)
    llm_calls = str(summary.llm_call_count)
    total_tok = f"{summary.total_tokens:,}" if summary.total_tokens else "—"
    trace_id_short = summary.trace_id[:12] + "..." if len(summary.trace_id) > 12 else summary.trace_id

    html = f"""
    <div class="trace-row">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <div>
                <code style="color:#4fc3f7; font-size:0.85rem;">{trace_id_short}</code>
                &nbsp; {status_html}
            </div>
            <div style="color:#9e9e9e; font-size:0.8rem;">
                {started}
            </div>
        </div>
        <div style="display:flex; gap:14px; font-size:0.8rem; color:#9e9e9e; margin-bottom:4px; flex-wrap:wrap;">
            <span>Duration: <b style="color:#e0e0e0">{duration}</b></span>
            <span>LLM calls: <b style="color:#e0e0e0">{llm_calls}</b></span>
            <span>Tokens: <b style="color:#e0e0e0">{total_tok}</b></span>
            <span>Cost: <b style="color:#e0e0e0">{cost_str}</b></span>
        </div>
        <div class="trace-row-tags">{tag_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    button_key = f"trace_overlay_{summary.trace_id.replace('-', '_')}"
    st.button(
        "Open trace",
        key=button_key,
        type="tertiary",
        width="stretch",
        help=f"Open trace {summary.trace_id}",
        on_click=_on_select_trace,
        args=(summary.trace_id,),
    )


def _fmt_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f}s"


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
