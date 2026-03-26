import streamlit as st

# Color palette
COLORS = {
    "bg_primary": "#0e1117",
    "bg_secondary": "#1a1d23",
    "bg_card": "#21252b",
    "accent": "#4fc3f7",
    "accent_hover": "#29b6f6",
    "success": "#66bb6a",
    "error": "#ef5350",
    "warning": "#ffa726",
    "text_primary": "#e0e0e0",
    "text_secondary": "#9e9e9e",
    "border": "#333842",
    "run": "#42a5f5",
    "agent": "#ab47bc",
    "llm_call": "#26a69a",
    "tool_call": "#ffa726",
}


def get_span_color(span_name: str, status: str | None = None) -> str:
    if status == "error":
        return COLORS["error"]
    return COLORS.get(span_name, COLORS["accent"])


def apply_theme():
    st.markdown(
        """
        <style>
        /* Global overrides */
        .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        /* Metric cards */
        .metric-card {
            background: %(bg_card)s;
            border: 1px solid %(border)s;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 8px;
        }
        .metric-card .label {
            color: %(text_secondary)s;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .metric-card .value {
            color: %(text_primary)s;
            font-size: 1.5rem;
            font-weight: 600;
        }

        /* Span badges */
        .span-badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.03em;
        }
        .span-badge.run       { background: %(run)s22; color: %(run)s; border: 1px solid %(run)s44; }
        .span-badge.agent     { background: %(agent)s22; color: %(agent)s; border: 1px solid %(agent)s44; }
        .span-badge.llm_call  { background: %(llm_call)s22; color: %(llm_call)s; border: 1px solid %(llm_call)s44; }
        .span-badge.tool_call { background: %(tool_call)s22; color: %(tool_call)s; border: 1px solid %(tool_call)s44; }

        /* Status badges */
        .status-ok    { color: %(success)s; font-weight: 600; }
        .status-error { color: %(error)s; font-weight: 600; }

        /* Trace list items */
        .trace-row {
            background: %(bg_card)s;
            border: 1px solid %(border)s;
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 0;
            height: 92px;
            overflow: hidden;
            box-sizing: border-box;
        }
        div[class*="st-key-trace_overlay_"] {
            margin-top: -92px;
            margin-bottom: 6px;
            position: relative;
            z-index: 2;
        }
        div[class*="st-key-trace_overlay_"] button {
            width: 100%%;
            height: 92px;
            background: transparent;
            color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            box-shadow: none;
            cursor: pointer;
        }
        div[class*="st-key-trace_overlay_"] button:hover,
        div[class*="st-key-trace_overlay_"] button:focus,
        div[class*="st-key-trace_overlay_"] button:focus-visible {
            border-color: %(accent)s;
            box-shadow: 0 0 0 1px %(accent)s22;
            outline: none;
        }
        div[class*="st-key-trace_overlay_"] button p {
            font-size: 0;
            line-height: 0;
            margin: 0;
        }
        .trace-row-tags {
            display: flex;
            flex-wrap: nowrap;
            gap: 4px;
            overflow: hidden;
            white-space: nowrap;
        }
        .span-details {
            margin: 0 0 6px 0;
            width: 100%%;
        }
        .span-details summary {
            list-style: none;
        }
        .span-details summary::-webkit-details-marker {
            display: none;
        }
        .span-summary {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            max-width: 100%%;
        }
        .span-summary-text {
            display: inline-flex;
            align-items: center;
            flex-wrap: wrap;
        }
        .span-summary-arrow {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            color: %(text_secondary)s;
            font-size: 0.9rem;
            line-height: 1;
        }
        .span-summary-arrow::before {
            content: "▸";
        }
        .span-details[open] .span-summary-arrow::before {
            content: "▾";
            color: %(accent)s;
        }
        .span-detail-panel {
            margin: 8px 0 0 24px;
            max-width: 100%%;
            box-sizing: border-box;
            background: %(bg_secondary)s;
            border: 1px solid %(border)s;
            border-radius: 10px;
            padding: 12px 14px;
        }
        .span-detail-section + .span-detail-section {
            margin-top: 12px;
        }
        .span-detail-label {
            color: %(text_secondary)s;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            margin-bottom: 6px;
            text-transform: uppercase;
        }
        .span-detail-tags {
            margin: 0;
        }
        .span-attrs-json {
            background: %(bg_primary)s;
            border: 1px solid %(border)s;
            border-radius: 8px;
            color: %(text_primary)s;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.8rem;
            line-height: 1.45;
            margin: 0;
            padding: 10px 12px;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .span-attrs-json .json-key {
            color: #ffb86c;
            font-weight: 600;
        }
        .span-detail-note {
            color: %(text_secondary)s;
            font-size: 0.8rem;
            line-height: 1.4;
        }

        /* Tag pills */
        .tag-pill {
            display: inline-block;
            background: %(accent)s18;
            color: %(accent)s;
            border: 1px solid %(accent)s33;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.7rem;
            margin-right: 4px;
            margin-bottom: 2px;
            line-height: 1.2;
        }

        /* Waterfall bars */
        .waterfall-label {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.8rem;
        }

        /* Detail panel sections */
        .detail-section {
            background: %(bg_card)s;
            border: 1px solid %(border)s;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
        }

        /* Message bubbles for LLM calls */
        .msg-bubble {
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 8px;
            font-size: 0.85rem;
            line-height: 1.5;
            overflow-x: auto;
        }
        .msg-human   { background: #1e3a5f; border-left: 3px solid #42a5f5; }
        .msg-ai      { background: #1a3530; border-left: 3px solid #26a69a; }
        .msg-system  { background: #2d2335; border-left: 3px solid #ab47bc; }
        .msg-tool    { background: #33291a; border-left: 3px solid #ffa726; }

        /* Hide Streamlit's default footer */
        footer { visibility: hidden; }

        /* Smaller font for filter area */
        .filter-area { font-size: 0.85rem; }

        /* LLM Call expander styling */
        div[data-testid="stExpander"] {
            border: 1px solid %(border)s;
            border-radius: 10px;
            margin-bottom: 8px;
            overflow: hidden;
        }
        div[data-testid="stExpander"] details summary {
            background: %(bg_card)s;
            padding: 10px 16px;
            border-radius: 10px;
            transition: background 0.15s ease;
        }
        div[data-testid="stExpander"] details[open] summary {
            background: #272b34;
            border-bottom: 1px solid %(border)s;
            border-radius: 10px 10px 0 0;
        }
        div[data-testid="stExpander"] details summary:hover {
            background: #2c313b;
        }
        div[data-testid="stExpander"] details summary p {
            font-size: 0.88rem;
            font-weight: 500;
            letter-spacing: 0.01em;
        }
        div[data-testid="stExpander"] details summary p code {
            background: #1a1d23;
            border: 1px solid %(border)s;
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 0.78rem;
            color: %(accent)s;
        }
        div[data-testid="stExpander"] details summary p em {
            color: %(llm_call)s;
            font-style: normal;
            font-weight: 600;
        }
        div[data-testid="stJson"],
        div[data-testid="stJson"] > div {
            background: #33291a !important;
            border-radius: 6px;
            padding: 4px 8px;
        }
        </style>
        """
        % COLORS,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str) -> str:
    return f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
    </div>
    """


def span_badge(span_name: str) -> str:
    return f'<span class="span-badge {span_name}">{span_name}</span>'


def status_badge(status: str | None) -> str:
    if status is None:
        return '<span class="status-ok">—</span>'
    css_class = "status-ok" if status == "ok" else "status-error"
    icon = "✓" if status == "ok" else "✗"
    return f'<span class="{css_class}">{icon}</span>'


def tag_pill(key: str, value: str) -> str:
    return f'<span class="tag-pill">{key}: {value}</span>'
