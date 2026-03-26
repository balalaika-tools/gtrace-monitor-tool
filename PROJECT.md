# Agentic Trace Monitor

A Streamlit application for monitoring, filtering, and inspecting agentic traces from AWS CloudWatch logs.

---

## Overview

This app provides a visual interface for tracing agent executions end-to-end. It ingests structured TRACE-level logs from CloudWatch, presents them as a filterable list, and lets users drill into individual traces to inspect every span, LLM call, tool invocation, and token usage.

Read the `docs/` directory for the full trace format specification before implementing.

---

## Data Source

Traces are ingested by parsing AWS CloudWatch logs using `aws logs tail` or the equivalent SDK call.

**Log stream:**

```
/aws/bedrock-agentcore/runtimes/ai_exception_prod_ExceptionAgent-eEqZuQ3GF1-DEFAULT
```

**Filter pattern:**

```
{ $.level = "TRACE" }
```

Store the log stream name and all AWS-related configuration as environment variables. A settings module already exists at `src/tracer/core/settings.py` for this purpose.

---

## Core Workflow

### 1. Date-Range Selection

The user picks a start and end date (with optional time granularity). The app fetches and parses all matching CloudWatch logs for that period.

### 2. Trace Listing

Display every trace found within the selected date range. Each row should show enough context to identify the trace at a glance (trace ID, timestamp, status, duration, etc.).

### 3. Dynamic Filtering

- The user can add **one or more filter keys** via free-text input (e.g. `exception_id`, `session_id`, or any top-level log field).
- Filters are stacked — all active filters are applied together (AND logic).
- Once a filter is applied, **display the matching filter value inline** next to each entry so the user can scan results without opening the trace.

### 4. Trace Detail View

Clicking on a trace opens a detailed view rendered according to the format described in `docs/`. This view should include:

- Full span hierarchy (nested spans with timing)
- LLM call details (model, messages, responses)
- Tool calls and results
- Errors and status
- **Token count summary** for the entire trace (input tokens, output tokens, total)

---

## Architecture

### Project Structure

```
src/
├── tracer/
│   ├── core/
│   │   ├── settings.py          # Environment variables and config
│   │   ├── logging.py           # Logger setup
│   │   └── constants.py         # Shared constants
│   ├── ingestion/
│   │   ├── cloudwatch.py        # AWS CloudWatch log fetching
│   │   └── parser.py            # Raw log line → structured trace parsing
│   ├── models/
│   │   ├── trace.py             # Trace, Span, LLMCall data classes
│   │   └── filters.py           # Filter logic and state
│   ├── analysis/
│   │   └── tokens.py            # Token counting and aggregation
│   └── ui/
│       ├── app.py               # Streamlit entry point
│       ├── components/          # Reusable UI components
│       │   ├── date_picker.py
│       │   ├── filter_bar.py
│       │   ├── trace_list.py
│       │   └── trace_detail.py
│       ├── styles/              # Custom CSS and theming
│       │   └── theme.py
│       └── state.py             # Streamlit session state management
```

### Principles

- **Modular code** — Use subfolders, separate files, well-scoped functions, and classes where appropriate. No large monolithic `.py` files.
- **Logging** — Add a structured logger throughout the codebase. Log ingestion errors, parsing failures, and performance metrics.
- **Error handling** — Handle failures gracefully at every layer (AWS connectivity issues, malformed log entries, missing fields, unexpected data shapes). Surface errors to the user without crashing the app.

---

## UX Requirements

### Performance

- **Responsive** — The app should not block the UI on long-running CloudWatch fetches. Use spinners or progress indicators for async operations.
- **Caching** — Cache log fetches, parsed trace data, and computed token counts using `@st.cache_data` or `@st.cache_resource` where appropriate. Avoid re-fetching data that hasn't changed.

### Stability

- **Stable layout** — Prevent pages from flickering or disappearing on Streamlit re-render events. Use `st.session_state` to preserve UI state (selected filters, open traces, scroll position) across interactions.

### Design

- **Visual polish** — Invest in the design. This is a tool meant for daily use. Make it visually distinctive, well-organized, and genuinely pleasant to work with.
- **Usability** — Prioritize information density without clutter. Make the trace detail view scannable. Use color, typography, and spacing intentionally.

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `AWS_REGION` | AWS region for CloudWatch | `us-east-1` |
| `LOG_GROUP_NAME` | CloudWatch log group to query | `/aws/bedrock-agentcore/runtimes/ai_exception_prod_ExceptionAgent-eEqZuQ3GF1-DEFAULT` |
| `LOG_FILTER_PATTERN` | CloudWatch filter pattern | `{ $.level = "TRACE" }` |
| `LOG_LEVEL` | Application log level | `INFO` |

---

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (or use .env)
export AWS_REGION=us-east-1
export LOG_GROUP_NAME="/aws/bedrock-agentcore/runtimes/..."
export LOG_FILTER_PATTERN='{ $.level = "TRACE" }'

# Run the app
streamlit run src/tracer/ui/app.py
```
