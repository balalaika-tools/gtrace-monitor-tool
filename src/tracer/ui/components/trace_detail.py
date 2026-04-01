from __future__ import annotations

import html
import json
import re
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from tracer.analysis.tokens import TokenSummary, summarize_span_tokens, summarize_trace_tokens
from tracer.core.settings import get_settings
from tracer.models.trace import Span, Trace
from tracer.ui import state
from tracer.ui.styles.theme import (
    COLORS,
    get_span_color,
    metric_card,
    span_badge,
    status_badge,
    tag_pill,
)


def _fmt_dur(ms: int | None) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f}s"


_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*")


def _render_download_button(trace_id: str):
    store_dir = state.get_trace_store_dir()
    if not store_dir:
        return
    trace_file = Path(store_dir) / f"{trace_id}.json"
    if not trace_file.exists():
        return
    raw = trace_file.read_text(encoding="utf-8")
    cleaned = "\n".join(
        _TS_PREFIX.sub("", line) for line in raw.splitlines() if line.strip()
    )
    st.download_button(
        label="⬇ log",
        data=cleaned,
        file_name=f"{trace_id}.jsonl",
        mime="application/x-ndjson",
        use_container_width=True,
    )


def render_trace_detail(trace: Trace):
    """Render the full detail view for a single trace."""
    # Back button
    if st.button("← Back to trace list", type="secondary"):
        state.set_selected_trace_id(None)
        if "trace_id" in st.query_params:
            del st.query_params["trace_id"]
        st.rerun()

    # Header + download button
    hcol, dlcol = st.columns([8, 1])
    with hcol:
        st.markdown(f"### Trace `{trace.trace_id}`")
    with dlcol:
        _render_download_button(trace.trace_id)

    # Tags
    if trace.tags:
        tag_html = " ".join(tag_pill(k, str(v)) for k, v in trace.tags.items() if v)
        st.markdown(tag_html, unsafe_allow_html=True)

    # Summary metrics
    tokens = summarize_trace_tokens(trace)
    _render_token_summary(tokens, trace)

    st.markdown("---")

    # Tabs for different views
    tab_spans, tab_llm, tab_tools, tab_waterfall = st.tabs(
        ["Span List", "LLM Calls", "Tool Calls", "Waterfall"]
    )

    with tab_spans:
        _render_span_list(trace)

    with tab_llm:
        _render_llm_calls(trace)

    with tab_tools:
        _render_tool_calls(trace)

    with tab_waterfall:
        _render_waterfall(trace)


def _render_token_summary(tokens: TokenSummary, trace: Trace):
    """Render token usage summary cards."""
    # Row 1: STATUS, DURATION, LLM CALLS, TOOL CALLS
    cols = st.columns(4)
    with cols[0]:
        st.markdown(metric_card("Status", status_badge(trace.status)), unsafe_allow_html=True)
    with cols[1]:
        st.markdown(metric_card("Duration", _fmt_dur(trace.duration_ms)), unsafe_allow_html=True)
    with cols[2]:
        st.markdown(metric_card("LLM Calls", str(tokens.llm_call_count)), unsafe_allow_html=True)
    with cols[3]:
        tool_count = len(trace.tool_call_spans)
        st.markdown(metric_card("Tool Calls", str(tool_count)), unsafe_allow_html=True)

    # Row 2: TOTAL TOKENS, INPUT TOKENS, CACHE READ, CACHE CREATION, OUTPUT TOKENS
    cols2 = st.columns(5)
    with cols2[0]:
        st.markdown(
            metric_card("Total Tokens", f"{tokens.total_tokens:,}"),
            unsafe_allow_html=True,
        )
    with cols2[1]:
        st.markdown(
            metric_card("Input Tokens", f"{tokens.input_tokens:,}"),
            unsafe_allow_html=True,
        )
    with cols2[2]:
        st.markdown(
            metric_card("Cache Read", f"{tokens.cache_read_tokens:,}"),
            unsafe_allow_html=True,
        )
    with cols2[3]:
        st.markdown(
            metric_card("Cache Creation", f"{tokens.cache_creation_tokens:,}"),
            unsafe_allow_html=True,
        )
    with cols2[4]:
        st.markdown(
            metric_card("Output Tokens", f"{tokens.output_tokens:,}"),
            unsafe_allow_html=True,
        )


def _render_waterfall(trace: Trace):
    """Render a Gantt-style waterfall chart of all spans."""
    spans = trace.spans
    if not spans:
        st.info("No spans in this trace.")
        return

    t0 = min(s.started_at for s in spans)

    fig = go.Figure()

    # Sort by depth then start time for visual ordering
    sorted_spans = sorted(spans, key=lambda s: (s.depth, s.started_at), reverse=True)

    for span in sorted_spans:
        x0_s = (span.started_at - t0).total_seconds()
        dur_s = (span.duration_ms or 0) / 1000
        colour = get_span_color(span.span_name, span.status)
        indent = "  " * span.depth
        label_text = f"{indent}{span.span_name}"

        # Add tool/agent name if available
        if span.span_name == "tool_call" and "tool" in span.attrs:
            label_text += f" ({span.attrs['tool']})"
        elif span.span_name == "agent" and "agent" in span.attrs:
            label_text += f" ({span.attrs['agent']})"
        elif span.span_name == "llm_call":
            seq = span.attrs.get("seq", "")
            model = span.attrs.get("model", "")
            if model:
                model_short = model.split(".")[-1].split("-v")[0] if "." in model else model
                label_text += f" #{seq} ({model_short})"
            elif seq:
                label_text += f" #{seq}"

        label_text += f" — {dur_s:.2f}s"

        hover = (
            f"<b>{span.span_name}</b><br>"
            f"span_id: {span.span_id}<br>"
            f"status: {span.status or '—'}<br>"
            f"duration: {dur_s:.2f}s<br>"
        )

        fig.add_trace(
            go.Bar(
                x=[dur_s],
                y=[label_text],
                orientation="h",
                base=x0_s,
                marker_color=colour,
                marker_line_width=0,
                hovertemplate=hover + "<extra></extra>",
                showlegend=False,
            )
        )

    fig.update_layout(
        barmode="overlay",
        xaxis_title="seconds from trace start",
        yaxis=dict(autorange="reversed"),
        height=max(300, 36 * len(sorted_spans)),
        margin=dict(l=20, r=20, t=10, b=40),
        plot_bgcolor=COLORS["bg_secondary"],
        paper_bgcolor=COLORS["bg_primary"],
        font=dict(color=COLORS["text_primary"], size=12, family="JetBrains Mono, Fira Code, monospace"),
        xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
        yaxis_tickfont=dict(size=11),
    )

    st.plotly_chart(fig)


def _render_span_list(trace: Trace):
    """Render all spans as an indented, expandable list, walking the parent→children tree."""
    rendered: set[str] = set()

    def _render_subtree(span: Span) -> None:
        rendered.add(span.span_id)
        indent_px = span.depth * 24
        detail_indent_px = indent_px + 24
        badge = span_badge(span.span_name)
        status = status_badge(span.status)
        dur = _fmt_dur(span.duration_ms)
        tag_html = " ".join(tag_pill(k, str(v)) for k, v in span.tags.items() if v)
        attrs_view = _format_span_attrs(span)
        attrs_html = _pretty_json_html(attrs_view) if attrs_view else ""

        sections: list[str] = []
        if tag_html:
            sections.append(
                f"""
                <div class="span-detail-section">
                    <div class="span-detail-label">Tags</div>
                    <div class="span-detail-tags">{tag_html}</div>
                </div>
                """
            )
        if attrs_html:
            sections.append(
                f"""
                <div class="span-detail-section">
                    <div class="span-detail-label">Attributes</div>
                    {attrs_html}
                </div>
                """
            )
        detail_body = "".join(sections) or '<div class="span-detail-note">No additional span details.</div>'

        details_html = f"""
        <details class="span-details">
            <summary class="span-summary" style="padding-left:{indent_px}px;">
                <span class="span-summary-text">
                    {badge} &nbsp; {status} &nbsp; <code>{dur}</code> &nbsp; <code style="color:#666">{html.escape(span.span_id)}</code>
                </span>
                <span class="span-summary-arrow" aria-hidden="true"></span>
            </summary>
            <div class="span-detail-panel" style="margin-left:{detail_indent_px}px; width:calc(100% - {detail_indent_px}px);">
                {detail_body}
            </div>
        </details>
        """
        st.html(details_html)
        for child in sorted(span.children, key=lambda s: s.started_at):
            _render_subtree(child)

    # DFS from root spans — this correctly places each child under its actual parent
    for root in sorted(trace.root_spans, key=lambda s: s.started_at):
        _render_subtree(root)

    # Render any orphan spans not reachable from root (parent_span_id points outside the trace)
    for span in trace.spans:
        if span.span_id not in rendered:
            _render_subtree(span)


def _format_span_attrs(span: Span) -> dict:
    if not span.attrs:
        return {}

    if span.span_name == "llm_call":
        return _format_llm_span_attrs(span.attrs)

    if span.span_name == "tool_call":
        return _format_tool_span_attrs(span.attrs)

    return _normalize_for_display(span.attrs)


def _format_llm_span_attrs(attrs: dict) -> dict:
    result: dict = {}

    model = attrs.get("model")
    if model:
        result["model"] = model

    _max = get_settings().span_content_max_chars
    input_messages = _simplify_messages(attrs.get("delta"), max_chars=_max)
    if input_messages:
        result["input"] = input_messages

    response_messages = _simplify_messages(attrs.get("response"), max_chars=_max)
    if response_messages:
        result["response"] = response_messages

    return _normalize_for_display(result)


def _format_tool_span_attrs(attrs: dict) -> dict:
    ordered: dict = {}

    if "tool" in attrs:
        ordered["tool"] = attrs.get("tool")
    if "input" in attrs:
        ordered["input"] = attrs.get("input")
    if "result" in attrs:
        ordered["result"] = attrs.get("result")

    for key, value in attrs.items():
        if key in {"tool", "input", "result"}:
            continue
        ordered[key] = value

    return _normalize_for_display(ordered)


def _simplify_messages(messages, max_chars: int = 900) -> list[dict]:
    if not isinstance(messages, list):
        return []

    simplified: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("type", "unknown"))
        entry: dict = {"role": role}

        text_parts: list[str] = []
        parsed_data: list[dict | list] = []
        tool_uses: list[dict] = []
        content = msg.get("content")

        if isinstance(content, str):
            parsed = _coerce_json_string(content)
            if isinstance(parsed, (dict, list)):
                parsed_data.append(parsed)
            else:
                text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "text":
                        block_text = str(block.get("text", ""))
                        parsed = _coerce_json_string(block_text)
                        if isinstance(parsed, (dict, list)):
                            parsed_data.append(parsed)
                        else:
                            text_parts.append(block_text)
                    elif block_type == "tool_use":
                        tool_item: dict = {"name": str(block.get("name", "unknown"))}
                        tool_input = _normalize_for_display(block.get("input"), key="input")
                        if tool_input not in (None, "", [], {}):
                            tool_item["input"] = tool_input
                        tool_uses.append(tool_item)
                    elif block_type in {"cachePoint", "cache_point"}:
                        cache_payload = {k: v for k, v in block.items() if k != "type"}
                        if cache_payload:
                            entry["cache_point"] = _normalize_for_display(cache_payload)
                else:
                    text_parts.append(str(block))
        elif content is not None:
            text_parts.append(str(content))

        text = "\n\n".join(_normalize_text(part).strip() for part in text_parts if str(part).strip())
        if text:
            max_len = 320 if role == "system" else max_chars
            entry["text"] = _truncate(text, max_len)

        if parsed_data:
            entry["data"] = _normalize_for_display(parsed_data[0] if len(parsed_data) == 1 else parsed_data)

        if tool_uses:
            entry["tool_use"] = tool_uses[0] if len(tool_uses) == 1 else tool_uses

        if len(entry) > 1:
            simplified.append(entry)

    return simplified


def _coerce_json_string(value):
    if isinstance(value, str):
        candidate = _extract_json_candidate(value)
        if candidate is None:
            return value
        parsed = _try_load_json(candidate)
        if parsed is not None:
            return parsed
    return value


def _extract_json_candidate(value: str) -> str | None:
    stripped = value.strip()
    if not stripped or len(stripped) > 200_000:
        return None

    direct = _maybe_json_text(stripped)
    if direct is not None:
        return direct

    for match in re.finditer(r"```(?:json|javascript|js|python|text|txt)?\s*(.*?)\s*```", stripped, re.S | re.I):
        block = match.group(1).strip()
        candidate = _maybe_json_text(block)
        if candidate is not None:
            return candidate

    return _first_balanced_json_substring(stripped)


def _maybe_json_text(text: str) -> str | None:
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        return text
    return None


def _first_balanced_json_substring(text: str) -> str | None:
    start = -1
    opening = ""
    closing = ""
    for idx, char in enumerate(text):
        if char in "[{":
            start = idx
            opening = char
            closing = "}" if char == "{" else "]"
            break
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def _try_load_json(text: str):
    escaped_control_chars = _escape_control_chars_in_json_strings(text)
    escaped_hex = re.sub(r"(?<!\\)\\x([0-9a-fA-F]{2})", r"\\\\x\1", text)
    escaped_hex_and_controls = _escape_control_chars_in_json_strings(escaped_hex)
    attempts = [
        text,
        escaped_hex,
        escaped_control_chars,
        escaped_hex_and_controls,
    ]
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except Exception:
            continue
    return None


def _escape_control_chars_in_json_strings(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False

    for char in text:
        if in_string:
            if escape:
                result.append(char)
                escape = False
                continue

            if char == "\\":
                result.append(char)
                escape = True
                continue

            if char == '"':
                result.append(char)
                in_string = False
                continue

            if char == "\n":
                result.append("\\n")
                continue
            if char == "\r":
                result.append("\\r")
                continue
            if char == "\t":
                result.append("\\t")
                continue

            result.append(char)
            continue

        result.append(char)
        if char == '"':
            in_string = True

    return "".join(result)


def _normalize_for_display(value, *, key: str | None = None, depth: int = 0):
    if depth > 8:
        return str(value)

    if isinstance(value, dict):
        return {
            str(k): _normalize_for_display(v, key=str(k), depth=depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, list):
        max_items = 100
        items = [_normalize_for_display(v, key=key, depth=depth + 1) for v in value[:max_items]]
        if len(value) > max_items:
            items.append({"_truncated_items": len(value) - max_items})
        return items

    if isinstance(value, str):
        parsed = _coerce_json_string(value)
        if parsed is not value:
            return _normalize_for_display(parsed, key=key, depth=depth + 1)
        return _normalize_text(value, key=key)

    return value


def _normalize_text(text: str, *, key: str | None = None, max_chars: int | None = 8_000) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return cleaned

    if _looks_like_sql(cleaned, key):
        return _format_sql(cleaned)

    if max_chars is not None and len(cleaned) > max_chars:
        return _truncate(cleaned, max_chars)

    return cleaned


def _looks_like_sql(text: str, key: str | None = None) -> bool:
    if key and key.lower() in {"query", "sql", "statement"}:
        return True
    return bool(re.match(r"^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP)\b", text, re.I))


def _format_sql(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _pretty_json_html(value) -> str:
    dumped = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    lines: list[str] = []

    for line in dumped.splitlines():
        match = re.match(r'^(\s*)"((?:\\.|[^"\\])*)":(.*)$', line)
        if match:
            indent, key, rest = match.groups()
            continuation = " " * (len(indent) + len(key) + 5)
            rest = rest.replace("\\n", "\n" + continuation)
            lines.append(
                f'{html.escape(indent)}<span class="json-key">"{html.escape(key)}"</span>:{html.escape(rest)}'
            )
        else:
            lines.append(html.escape(line))

    joined = "\n".join(lines)
    return f'<pre class="span-attrs-json">{joined}</pre>'


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _render_llm_calls(trace: Trace):
    """Render detailed view of each LLM call in the trace."""
    llm_spans = trace.llm_call_spans
    if not llm_spans:
        st.info("No LLM calls in this trace.")
        return

    for i, span in enumerate(llm_spans):
        seq = span.attrs.get("seq", i + 1)
        model = span.attrs.get("model", "unknown")
        model_short = model.split(".")[-1].split("-v")[0] if "." in model else model
        dur = _fmt_dur(span.duration_ms)
        status_icon = ":green[✓]" if span.status == "ok" else ":red[✗]"
        stop_reason = span.attrs.get("stop_reason", "")
        tok = summarize_span_tokens(span)
        span_short = span.span_id[:12] if span.span_id else "—"

        header = f"*LLM Call \#{seq}* · {model_short} · {dur} · `{span_short}` · {status_icon}"

        with st.expander(header, expanded=False):
            st.caption(f"Model: `{model}` · Duration: {dur} · Span: `{span.span_id}`")

            # Token breakdown
            if tok.total_tokens > 0:
                cols = st.columns(5)
                with cols[0]:
                    st.metric("Total", f"{tok.total_tokens:,}")
                with cols[1]:
                    st.metric("Input", f"{tok.input_tokens:,}")
                with cols[2]:
                    st.metric("Cache Read", f"{tok.cache_read_tokens:,}")
                with cols[3]:
                    st.metric("Cache Creation", f"{tok.cache_creation_tokens:,}")
                with cols[4]:
                    st.metric("Output", f"{tok.output_tokens:,}")

            if stop_reason:
                st.markdown(f"**Stop reason:** `{stop_reason}`")

            # Delta messages (input to this call)
            delta = span.attrs.get("delta", [])
            if delta:
                st.markdown("**Delta Messages** (new since last call):")
                _render_messages(delta)

            # Response
            response = span.attrs.get("response", [])
            if response:
                st.markdown("**Response:**")
                _render_messages(response)


def _render_messages(messages: list):
    """Render a list of message dicts as styled bubbles."""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type", "unknown")
        content = msg.get("content", "")
        label = msg_type.upper()
        tool_id = msg.get("tool_call_id", "")
        if tool_id:
            label += f" (tool_call_id: {tool_id})"
        css_class = {
            "human": "msg-human",
            "ai": "msg-ai",
            "system": "msg-system",
            "tool": "msg-tool",
        }.get(msg_type, "msg-tool")

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        text = _normalize_text(str(block.get("text", "")), max_chars=None)
                        parsed = _coerce_json_string(text)
                        if isinstance(parsed, (dict, list)):
                            _render_message_bubble(css_class, f"{label} [text]", "")
                            st.json(_normalize_for_display(parsed))
                        else:
                            _render_message_bubble(css_class, f"{label} [text]", _html_text(text))
                    elif block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = _normalize_for_display(block.get("input"), key="input")
                        st.markdown(
                            f'<div class="msg-tool msg-bubble">'
                            f'<span style="font-size:0.7rem;color:#9e9e9e;font-weight:600">{label} [tool_use]</span>'
                            f'&nbsp;&nbsp;<code style="color:#ffa726;background:#33291a;padding:2px 6px;border-radius:4px;font-size:0.8rem">'
                            f"{html.escape(tool_name)}</code></div>",
                            unsafe_allow_html=True,
                        )
                        if tool_input not in (None, "", [], {}):
                            if isinstance(tool_input, (dict, list)):
                                st.json(tool_input)
                            else:
                                _render_value(tool_input)
                    else:
                        parsed = _normalize_for_display({k: v for k, v in block.items() if k != "type"})
                        _render_message_bubble(
                            css_class,
                            f"{label} [{block_type}]",
                            _html_code_block(parsed),
                        )
                else:
                    _render_message_bubble(
                        css_class, label,
                        _html_text(_normalize_text(str(block), max_chars=None)),
                    )
        elif isinstance(content, str):
            parsed = _coerce_json_string(content)
            if isinstance(parsed, (dict, list)):
                _render_message_bubble(css_class, label, "")
                st.json(_normalize_for_display(parsed))
            else:
                _render_message_bubble(css_class, label, _html_text(_normalize_text(content, max_chars=None)))
        else:
            parsed = _normalize_for_display(content)
            if isinstance(parsed, (dict, list)):
                _render_message_bubble(css_class, label, "")
                st.json(parsed)
            else:
                _render_message_bubble(css_class, label, _html_text(str(parsed)))


def _html_code_block(obj) -> str:
    """Render a dict/list as a styled HTML pre/code block."""
    code = html.escape(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    return (
        '<pre style="background:#0e1117;border-radius:6px;padding:10px 12px;'
        'overflow-x:auto;font-size:0.78rem;margin:4px 0 0 0;line-height:1.5">'
        f"<code>{code}</code></pre>"
    )




def _html_text(text: str) -> str:
    """Render plain text safely inside an HTML bubble."""
    return f'<p style="white-space:pre-wrap;margin:0;line-height:1.6">{html.escape(text)}</p>'


def _render_message_bubble(css_class: str, label: str, content: str):
    """Render a single message bubble."""
    st.markdown(
        f'<div class="{css_class} msg-bubble">'
        f'<div style="font-size:0.7rem; color:#9e9e9e; margin-bottom:4px; font-weight:600">{label}</div>'
        f"{content}</div>",
        unsafe_allow_html=True,
    )


def _render_value(value, *, label: str | None = None):
    if label:
        st.markdown(f"**{label}:**")

    normalized = _normalize_for_display(value, key=label.lower() if label else None)
    if isinstance(normalized, (dict, list)):
        st.json(normalized, expanded=False)
        return

    if isinstance(normalized, str):
        parsed = _coerce_json_string(normalized)
        if isinstance(parsed, (dict, list)):
            st.json(_normalize_for_display(parsed), expanded=False)
            return

        text = normalized.strip()
        if not text:
            st.caption("Empty")
            return

        if _looks_like_sql(text, label.lower() if label else None):
            st.code(_format_sql(text), language="sql")
            return

        if "\n" in text or len(text) > 220:
            st.code(_truncate(text, 10_000), language="text")
            return

        st.write(text)
        return

    st.write(str(normalized))


def _render_tool_calls(trace: Trace):
    """Render detailed view of each tool call in the trace."""
    tool_spans = trace.tool_call_spans
    if not tool_spans:
        st.info("No tool calls in this trace.")
        return

    for span in tool_spans:
        tool_name = span.attrs.get("tool", "unknown")
        dur = _fmt_dur(span.duration_ms)
        status_icon = ":green[✓]" if span.status == "ok" else ":red[✗]"
        span_short = span.span_id[:12] if span.span_id else "—"

        header = f":orange[**{tool_name}**] · {dur} · `{span_short}` · {status_icon}"

        with st.expander(header, expanded=False):
            # Input
            tool_input = _normalize_for_display(span.attrs.get("input"), key="input")
            if tool_input not in (None, "", [], {}):
                with st.expander("Input", expanded=False):
                    if isinstance(tool_input, (dict, list)):
                        st.json(tool_input)
                    else:
                        _render_value(tool_input)

            # Result
            result = _normalize_for_display(span.attrs.get("result"), key="result")
            result_size = span.attrs.get("result_size")
            if result_size is not None:
                st.markdown(f"**Result size:** {result_size}")

            if result is not None:
                with st.expander("Result", expanded=False):
                    if isinstance(result, (dict, list)):
                        st.json(result)
                    else:
                        _render_value(result)

            # Error info
            error = span.attrs.get("error")
            if error:
                error_type = span.attrs.get("error_type", "")
                st.error(f"**{error_type}:** {error}" if error_type else str(error))
