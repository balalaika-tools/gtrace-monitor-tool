# Tracer v2 — Streamlit Guide

How to load, parse, and query the trace logs produced by `tracer.py`.

---

## Log format

Each log record is a single JSON object serialised to one stdout line by
`_JSONFormatter`. In prod these lines are captured by CloudWatch Logs. Locally
you redirect stdout to a file (`python main.py > run.log`). Span events are
mixed with regular INFO/WARNING/ERROR records in the same stream and must be
filtered out by checking for the `"event"` field.

A span event always has the `"event"` field set to one of:
`"span.start"`, `"span.end"`, `"span.error"`

```json
{"ts":"2026-03-20T12:45:24","level":"TRACE","logger":"exceptionist.tracer",
 "message":"[llm_call] span.end","event":"span.end","span_name":"llm_call",
 "trace_id":"session-abc","span_id":"a3f7b2c1","parent_span_id":"s1b2c4d5",
 "exception_id":"96000000-ytvte","duration_ms":2341,"status":"ok",
 "attrs":{"model":"claude-sonnet-4-6","seq":1,"tokens":{"input":461,"output":197,"cache_read":15541}}}
```

---

## Loading the log file

```python
import json
import pandas as pd

def load_spans(log_path: str) -> pd.DataFrame:
    rows = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Lines are prefixed with a timestamp — strip it
            # Format: "2026-03-20T12:45:24 {...json...}"
            if " " in line:
                _, raw = line.split(" ", 1)
            else:
                raw = line
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # Keep only span events
            if obj.get("event") in ("span.start", "span.end", "span.error"):
                rows.append(obj)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"])
    df["attrs"] = df["attrs"].apply(lambda x: x if isinstance(x, dict) else {})
    return df
```

---

## Core dataframe columns

After loading, these columns are always present on every span row:

| Column | Type | Description |
|---|---|---|
| `ts` | datetime | Timestamp of the event |
| `event` | str | `span.start`, `span.end`, `span.error` |
| `name` | str | `run`, `agent`, `llm_call`, `tool_call` |
| `trace_id` | str | Session ID — groups one conversation |
| `span_id` | str | Unique 8-char hex per span event |
| `parent_span_id` | str / NaN | Links child to parent |
| `status` | str | `ok` or `error` — only on end/error events |
| `duration_ms` | int / NaN | Only on end/error events |
| `attrs` | dict | Span-specific payload |

App-specific tags (`exception_id`, etc.) appear as their own columns at the
top level — they are directly filterable without touching `attrs`.

---

## Reconstructing spans (pairing start + end)

Each span produces two rows: `span.start` and `span.end` (or `span.error`).
To get one row per span with duration and status:

```python
def reconstruct_spans(df: pd.DataFrame) -> pd.DataFrame:
    starts = df[df["event"] == "span.start"].set_index("span_id")
    ends   = df[df["event"].isin(("span.end", "span.error"))].set_index("span_id")

    combined = starts[["ts", "span_name", "trace_id", "parent_span_id", "attrs"]].copy()
    combined.columns = ["started_at", "span_name", "trace_id", "parent_span_id", "start_attrs"]

    combined["ended_at"]    = ends["ts"]
    combined["duration_ms"] = ends["duration_ms"]
    combined["status"]      = ends["status"]
    combined["end_attrs"]   = ends["attrs"]
    combined["event"]       = ends["event"]   # span.end or span.error

    # Merge start and end attrs into one dict
    combined["attrs"] = combined.apply(
        lambda r: {**r["start_attrs"], **r["end_attrs"]}, axis=1
    )
    combined = combined.drop(columns=["start_attrs", "end_attrs"])
    combined.index.name = "span_id"
    return combined.reset_index()
```

---

## Filtering

### All spans for a session

```python
session = df[df["trace_id"] == "session-abc123"]
```

### All sessions that touched a specific exception

```python
# exception_id is a top-level column (tag), not inside attrs
sessions = df[df["exception_id"] == "96000000-ytvte"]["trace_id"].unique()
```

### Only LLM call spans

```python
llm = df[(df["event"] == "span.end") & (df["span_name"] == "llm_call")]
```

### Only failed spans

```python
errors = df[(df["status"] == "error")]
# span.error = Python exception propagated
# span.end status:error = business-level failure (span.fail() was called)
errors_hard = df[df["event"] == "span.error"]
errors_soft = df[(df["event"] == "span.end") & (df["status"] == "error")]
```

### Spans for a date range

```python
day = df[(df["ts"] >= "2026-03-20") & (df["ts"] < "2026-03-21")]
```

### A specific agent within a session

```python
agent_spans = df[
    (df["trace_id"] == "session-abc") &
    (df["span_name"] == "agent") &
    (df["attrs"].apply(lambda a: a.get("agent") == "main"))
]
```

---

## Token aggregation

Token data lives in `attrs.tokens` on every `span.end` for `span_name == "llm_call"`.

```python
llm = df[(df["event"] == "span.end") & (df["span_name"] == "llm_call")].copy()

# Expand token fields to columns
llm["tok_input"]      = llm["attrs"].apply(lambda a: a.get("tokens", {}).get("input", 0))
llm["tok_output"]     = llm["attrs"].apply(lambda a: a.get("tokens", {}).get("output", 0))
llm["tok_cache_read"] = llm["attrs"].apply(lambda a: a.get("tokens", {}).get("input_cache_read", 0))
llm["tok_total"]      = llm["attrs"].apply(lambda a: a.get("tokens", {}).get("total", 0))

# Total tokens per session
llm.groupby("trace_id")[["tok_input", "tok_output", "tok_cache_read"]].sum()

# Total tokens per day
llm.groupby(llm["ts"].dt.date)[["tok_input", "tok_output"]].sum()

# Cache hit rate per session (fraction of input tokens served from cache)
llm["cache_hit_rate"] = llm["tok_cache_read"] / (llm["tok_input"] + 1)
llm.groupby("trace_id")["cache_hit_rate"].mean()

# Approx cost (example rates — adjust to current Bedrock pricing)
PRICE_INPUT        = 3.00  / 1_000_000   # $ per token
PRICE_OUTPUT       = 15.00 / 1_000_000
PRICE_CACHE_READ   = 0.30  / 1_000_000

llm["cost_usd"] = (
    (llm["tok_input"] - llm["tok_cache_read"]) * PRICE_INPUT +
    llm["tok_output"] * PRICE_OUTPUT +
    llm["tok_cache_read"] * PRICE_CACHE_READ
)
llm.groupby("trace_id")["cost_usd"].sum()
```

---

## Building the span tree (waterfall view)

To render a Gantt/waterfall for one session, you need each span's depth in
the tree (for indentation) and its absolute start/end time.

```python
def build_tree(spans: pd.DataFrame) -> pd.DataFrame:
    """Add a 'depth' column by walking parent_span_id links."""
    id_to_depth = {}

    def get_depth(span_id):
        if span_id not in id_to_depth:
            row = spans[spans["span_id"] == span_id]
            if row.empty:
                return 0
            parent = row.iloc[0]["parent_span_id"]
            id_to_depth[span_id] = 0 if pd.isna(parent) else get_depth(parent) + 1
        return id_to_depth[span_id]

    spans = spans.copy()
    spans["depth"] = spans["span_id"].apply(get_depth)
    return spans.sort_values("started_at")


def waterfall_chart(session_spans: pd.DataFrame):
    """Render a Plotly Gantt chart for one session."""
    import plotly.graph_objects as go

    t0 = session_spans["started_at"].min()

    fig = go.Figure()
    for _, row in session_spans.iterrows():
        x0  = (row["started_at"] - t0).total_seconds() * 1000
        dur = row["duration_ms"] if pd.notna(row["duration_ms"]) else 0
        colour = "#e74c3c" if row["status"] == "error" else "#3498db"
        label  = f"{'  ' * row['depth']}{row['name']} ({int(dur)}ms)"

        fig.add_trace(go.Bar(
            x=[dur], y=[label], orientation="h",
            base=x0, marker_color=colour,
            hovertemplate=(
                f"span_id: {row['span_id']}<br>"
                f"status: {row['status']}<br>"
                f"duration: {int(dur)}ms<extra></extra>"
            ),
        ))

    fig.update_layout(barmode="overlay", xaxis_title="ms from start", height=50 + 30 * len(session_spans))
    return fig
```

---

## Detecting retries

A retry appears as two consecutive `llm_call` spans under the same parent
`agent` span, both with the same `seq` value.

```python
llm = df[(df["event"] == "span.end") & (df["span_name"] == "llm_call")].copy()
llm["seq"] = llm["attrs"].apply(lambda a: a.get("seq"))

retried = (
    llm.groupby(["trace_id", "parent_span_id", "seq"])
       .filter(lambda g: len(g) > 1)
)
```

---

## Detecting the SQL fixer being invoked

The fixer appears as an `agent` span whose `parent_span_id` points to a
`tool_call` span (rather than a `run` span as normal).

```python
reconstructed = reconstruct_spans(df)

tool_spans  = reconstructed[reconstructed["span_name"] == "tool_call"][["span_id"]].rename(columns={"span_id": "tool_span_id"})
fixer_spans = reconstructed[reconstructed["span_name"] == "agent"].copy()
fixer_spans = fixer_spans[fixer_spans["parent_span_id"].isin(tool_spans["tool_span_id"])]
fixer_spans["agent_name"] = fixer_spans["attrs"].apply(lambda a: a.get("agent", ""))
```

---

## Useful Streamlit page patterns

### Run Explorer — list all sessions

```python
runs = df[(df["event"] == "span.end") & (df["span_name"] == "run")].copy()
runs["total_tokens"] = runs["trace_id"].map(
    llm.groupby("trace_id")["tok_total"].sum()
)
runs["cost_usd"] = runs["trace_id"].map(
    llm.groupby("trace_id")["cost_usd"].sum()
)
st.dataframe(
    runs[["ts", "trace_id", "exception_id", "duration_ms", "total_tokens", "cost_usd", "status"]]
      .sort_values("ts", ascending=False)
)
```

### Drill into a session — waterfall

```python
selected_trace = st.selectbox("Select session", runs["trace_id"].tolist())
session_df = reconstruct_spans(df[df["trace_id"] == selected_trace])
tree = build_tree(session_df)
st.plotly_chart(waterfall_chart(tree))
```

### LLM call detail — messages and response

```python
selected_span = st.selectbox("Select LLM call", llm_spans["span_id"].tolist())
row = df[(df["span_id"] == selected_span) & (df["event"] == "span.start")].iloc[0]
attrs = row["attrs"]

st.subheader("Delta messages (new since last call)")
for msg in attrs.get("delta", []):
    st.markdown(f"**{msg['type']}**: {msg['content']}")

end_row = df[(df["span_id"] == selected_span) & (df["event"] == "span.end")].iloc[0]
end_attrs = end_row["attrs"]

st.subheader("Response")
for msg in end_attrs.get("response", []):
    st.markdown(f"**{msg['type']}**: {msg['content']}")

st.subheader("Tokens")
st.json(end_attrs.get("tokens", {}))
```

### Analytics — daily cost and cache hit rate

```python
daily = llm.groupby(llm["ts"].dt.date).agg(
    total_cost   = ("cost_usd",      "sum"),
    cache_hit    = ("cache_hit_rate","mean"),
    total_tokens = ("tok_total",     "sum"),
    runs         = ("trace_id",      "nunique"),
).reset_index()

st.bar_chart(daily.set_index("ts")["total_cost"])
st.line_chart(daily.set_index("ts")["cache_hit"])
```

---

## What you can and cannot do

### You can

- List all sessions for a date range, sorted by cost / duration / status
- Drill into any session and see the full span waterfall
- Read the exact messages sent to the LLM on each call (delta only, not full history)
- Read the LLM's response for each call
- See all tool call inputs and results
- Calculate token cost per session, per day, per model
- Calculate cache hit rate over time
- Detect retries (duplicate `seq` under same agent span)
- Detect fixer agent invocations (agent span parented to a tool_call span)
- Filter any view by `exception_id`, `trace_id`, date range, status, span name

### You cannot (without changes)

- Recover the full accumulated message history at call N (only the delta is logged)
- Get sub-millisecond timing (timestamps are second-resolution; duration is ms)
- See spans from runs where `LOG_LEVEL` was not set to `TRACE`
- Distinguish two independent runs that shared the same `session_id` (they merge
  into one trace — avoid session ID reuse across unrelated jobs)
