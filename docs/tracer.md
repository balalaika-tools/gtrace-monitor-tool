# Tracer — Generic LLM Agent Observability Framework

A lightweight, generic tracing framework for LLM-based agentic applications.
Designed to produce structured logs that a Streamlit monitoring app can parse into
per-session traces, span waterfalls, and cost analytics.

**Runtime assumption:** always used with LangChain / LangGraph. LLM messages are
LangChain `BaseMessage` instances (`HumanMessage`, `AIMessage`, `ToolMessage`,
`SystemMessage`). The tracer serialises them via their `.type` and `.content`
attributes, never raw dicts.

---

## Goals

- Produce structured JSONL logs that can be parsed into traces without any post-processing
- Be **generic** — no domain knowledge (no "SQL", no "exceptions"), reusable across any agentic app
- Allow per-session drill-down: LLM call delta, tool call args/results
- Allow cross-session aggregation: token cost, latency, error rate
- Piggyback on the existing `logger.trace()` + `_JSONFormatter` — no new dependencies

---

## Log Schema

Every trace line is a single JSON object. Fields are split into two tiers:

### Mandatory top-level fields (always present)

| Field | Type | Description |
|---|---|---|
| `ts` | ISO8601 string | Timestamp |
| `level` | `"TRACE"` | Always TRACE |
| `trace_id` | string | One per top-level run / session |
| `span_id` | string | Unique per operation (8-char hex) |
| `parent_span_id` | string \| null | Links child → parent. Null on root span |
| `event` | enum | `span.start`, `span.end`, `span.error` |
| `name` | enum | Span type — see taxonomy below |
| `duration_ms` | int | Only on `span.end` / `span.error` |
| `status` | `"ok"` \| `"error"` | Only on `span.end` / `span.error` |

### Tags (top-level, app-specific, filterable)

Promoted to top-level so a Streamlit dataframe can filter on them directly
without touching `attrs`. Example: `exception_id`, `user_id`, `job_id`.

```json
{"exception_id": "96000000-ytvte"}
```

**`trace_id` vs tags:**

| Field | Value | Meaning |
|---|---|---|
| `trace_id` | `session_id` | Groups all spans for one session/conversation |
| `exception_id` (tag) | business key | Lets you filter spans by what was processed |

`trace_id = session_id` means: if a session spans multiple turns (multi-turn
conversation with the same session ID), all their spans appear under one trace —
which is correct. Individual runs within the session are distinguished by finding
all root `run` spans (`parent_span_id == null`) ordered by `ts`.

If two unrelated runs share the same `session_id` (a bug / ID collision), their
spans would be merged in the Streamlit view. Ensure session IDs are unique per
independent invocation.

### `attrs` (detail payload, span-type specific)

Open dict. Content lives here — LLM call delta, tool inputs/outputs, etc.
The Streamlit parser uses top-level fields for the tree/timeline and `attrs`
for the drill-down detail panel.

**Size constraint:** CloudWatch has a 256KB per-event hard limit. Keep `attrs`
lean — see the truncation policy below.

---

## Span Taxonomy

Four span types, always nested in this strict hierarchy:

```
run
└── agent
    ├── llm_call
    │   ├── tool_call
    │   └── tool_call
    └── llm_call
        └── tool_call
```

### Enforcement

Valid parent → child relationships:

| Parent | Allowed children |
|---|---|
| `null` | `run` |
| `run` | `agent` |
| `agent` | `llm_call` |
| `llm_call` | `tool_call` |
| `tool_call` | _(none)_ |

At `span()` entry, the tracer checks `current_span.name → requested name` against
this table. On violation it logs a `WARNING` with the illegal pair and the
call site, then proceeds (never raises — tracing must not break the app).

---

## Span Reference

### `run` — top-level boundary, one per session

```jsonl
{"event":"span.start","name":"run","trace_id":"t1","span_id":"s1","parent_span_id":null,"exception_id":"96000000-ytvte","attrs":{}}
{"event":"span.end",  "name":"run","trace_id":"t1","span_id":"s1","duration_ms":58200,"status":"ok","attrs":{}}
```

### `agent` — one per agent invoked

```jsonl
{"event":"span.start","name":"agent","trace_id":"t1","span_id":"s2","parent_span_id":"s1","exception_id":"96000000-ytvte","attrs":{"agent":"main"}}
{"event":"span.end",  "name":"agent","trace_id":"t1","span_id":"s2","duration_ms":57100,"status":"ok","attrs":{}}
```

### `llm_call` — one per model invocation

Log only the **delta** — the new messages added since the previous LLM call,
not the full accumulated history. For LangChain this means the messages passed
to the current invocation minus the messages passed to the previous one.
The token counts tell you the full context size without duplicating it.

```jsonl
{"event":"span.start","name":"llm_call","trace_id":"t1","span_id":"s3","parent_span_id":"s2",
 "attrs":{
   "model":"claude-sonnet-4-6",
   "seq":1,
   "delta":[
     {"type":"human","content":"Investigate exception 96000000-ytvte"},
     {"type":"tool","tool_call_id":"tc_abc","content":"[{...1 row...}]"}
   ],
   "message_count":12
 }}

{"event":"span.end","name":"llm_call","trace_id":"t1","span_id":"s3","duration_ms":2341,"status":"ok",
 "attrs":{
   "stop_reason":"tool_use",
   "tokens":{"input":461,"output":197,"cache_read":15541,"cache_write":0},
   "response":[{"type":"ai","content":[{"type":"tool_use","name":"run_sql_query","input":{}}]}]
 }}
```

`message_count` = total messages in context at this call (for context growth tracking).
`delta` = only the new messages. `response` = the AIMessage content only.

### `tool_call` — one per tool invocation

```jsonl
{"event":"span.start","name":"tool_call","trace_id":"t1","span_id":"s4","parent_span_id":"s3",
 "attrs":{"tool":"run_sql_query","input":{"query":"SELECT ...","intent":"Fetch exception"}}}

{"event":"span.end","name":"tool_call","trace_id":"t1","span_id":"s4","duration_ms":120,"status":"ok",
 "attrs":{"tool":"run_sql_query","result_size":1,"result":[{...}]}}

// on failure (Python exception raised inside the tool):
{"event":"span.error","name":"tool_call","trace_id":"t1","span_id":"s4","duration_ms":80,"status":"error",
 "attrs":{"tool":"run_sql_query","error":"invalid hexadecimal digit","error_type":"DatabaseError"}}
```

---

## Error Boundary

Two distinct error signals — **do not conflate them**:

| Signal | When to use | Example |
|---|---|---|
| `span.error` | A Python exception was raised and propagated out of the span | DB timeout, network error, unhandled crash |
| `span.end` + `status:"error"` | The operation completed but the result is a business-level failure | LLM refusal, unexpected `stop_reason`, fixer agent returned no fix |

Rule: `span.error` means the span did not complete normally. `span.end status:error`
means it completed but the outcome was bad. The Streamlit waterfall colours them
differently.

---

## Retry Semantics

Retries are **sibling spans** — no special field needed.

If an LLM call fails and the framework retries it, you get two consecutive
`llm_call` spans under the same parent `agent` span, both with the same `seq`
value, the first with `status:"error"` and the second with `status:"ok"`.
The Streamlit can detect this by finding duplicate `seq` values under one agent span.

```
agent (s2)
├── llm_call seq=3  span.error  ← first attempt failed
└── llm_call seq=3  span.end ok ← retry succeeded
```

No explicit `retry_attempt` field. The pattern is self-describing from the span tree.

---

## attrs Truncation Policy

CloudWatch hard limit: **256KB per log event**.
Limits below are generous enough to fit 2–3 pages of readable content per field.
They exist only to guard against runaway payloads, not to restrict normal use.

Rules (applied before emit):

| Field | Limit | Note |
|---|---|---|
| `delta` message `content` | **15 000 chars** each | Covers a full multi-paragraph tool result or user message |
| `response` content (text blocks) | **15 000 chars** | Keep `tool_use` blocks intact — they are always small |
| `tool_call.result` | **20 000 chars** total | Enough for dozens of DB rows |
| Any other string in attrs | **5 000 chars** | Fallback guard |

If a value is cut, append `" …[truncated]"` at the cut point so it's obvious in the UI.
No `_truncated` flag needed — the suffix is self-evident.

Future option: for payloads over a configurable threshold, write the full
content to S3 with key `traces/{trace_id}/{span_id}.json` and store only the
S3 key in `attrs._ref`.

---

## Thread / Async Safety

`SpanContext` is created fresh per `with tracer.span()` call and is **never
shared** between spans. Each concurrent tool call gets its own `SpanContext`
instance — there is no shared mutable state between parallel spans.

`ContextVar` is both thread-safe and async-safe: each OS thread and each
asyncio Task gets its own copy of `_current_span_id` / `_current_trace_id` /
`_current_tags`. In LangGraph's parallel tool execution (multiple Tasks), each
Task correctly tracks its own active span without interference.

The only scenario that would be unsafe is manually passing a `SpanContext`
instance to another thread/task and calling `.set()` on it concurrently — don't do that.

---

## Implementation

### File location

```
src/exceptionist/core/tracer.py
```

### Class design

```python
VALID_CHILDREN: dict[str | None, set[str]] = {
    None:        {"run"},
    "run":       {"agent"},
    "agent":     {"llm_call"},
    "llm_call":  {"tool_call"},
    "tool_call": set(),
}

class Tracer:
    def __init__(self, logger: logging.Logger) -> None

    def start_trace(self, trace_id: str) -> None
    # Sets _current_trace_id ContextVar.

    def span(self, name: str, attrs: dict | None = None, tags: dict | None = None) -> Generator[SpanContext, None, None]
    # Context manager.
    # - Validates name against VALID_CHILDREN[current_span_name]; warns on violation.
    # - Emits span.start on enter.
    # - Emits span.end on clean exit.
    # - Emits span.error on exception (then re-raises).
    # - tags: merged with inherited tags → stamped top-level on every emit.
    # - yields SpanContext: caller calls span.set(key, value) for end-time attrs.

    def _truncate_attrs(self, attrs: dict) -> dict
    # Applies truncation policy before emit.

    def _emit(self, event, name, span_id, parent_span_id, trace_id,
              duration_ms, status, attrs, tags) -> None
    # Calls logger.trace(msg, extra=payload).
    # _JSONFormatter serialises extra fields into the JSON line automatically.


class SpanContext:
    span_id: str
    name: str
    attrs: dict        # end-time attrs, flushed on span.end / span.error

    def set(self, key: str, value: Any) -> None
```

### ContextVars

```python
_current_span_id:   ContextVar[str | None]    # active span_id
_current_span_name: ContextVar[str | None]    # active span name (for hierarchy validation)
_current_trace_id:  ContextVar[str | None]    # active trace_id
_current_tags:      ContextVar[dict]          # inherited tags (merged down the tree)
```

Tags are **inherited**: child spans automatically receive all tags set by any ancestor.
Set `exception_id` once on the root `run` span — every descendant carries it.

### How it writes to the log

```
tracer._emit()
    └─ self._log.trace(msg, extra=payload)
            └─ Python logging: extra{} flattened onto LogRecord as attributes
                    └─ _JSONFormatter iterates record.__dict__
                            └─ json.dumps() → one JSONL line to stdout / CloudWatch
```

No new handlers, formatters, or dependencies needed.

---

## Usage Pattern

```python
tracer.start_trace(exception_id)

with tracer.span("run", tags={"exception_id": exception_id}):
    with tracer.span("agent", attrs={"agent": "main"}):

        # In LangChain callbacks — on_llm_start
        with tracer.span("llm_call", attrs={
            "model": model_name,
            "seq": seq,
            "delta": serialise_lc_messages(new_messages),  # delta only, truncated
            "message_count": len(all_messages),
        }) as span:
            response = llm.invoke(all_messages)
            span.set("stop_reason", response.response_metadata.get("stop_reason"))
            span.set("tokens", response.usage_metadata)
            span.set("response", serialise_lc_messages([response]))

        # In each tool
        with tracer.span("tool_call", attrs={"tool": tool_name, "input": tool_input}) as span:
            result = tool.run(tool_input)
            span.set("result_size", len(result) if hasattr(result, "__len__") else 1)
            span.set("result", result)
```

`serialise_lc_messages()` — helper that converts LangChain `BaseMessage` instances
to `{"type": msg.type, "content": msg.content}` dicts and applies truncation.
Lives in `tracer.py` as a private function.

---

## Instrumentation Points in This Codebase

| Where | Span | Notes |
|---|---|---|
| `main.py` — per invocation | — | `tracer.start_trace(session_id)` called in `_run_in_background` |
| `agent.py` — per exception | `run` | tag `exception_id` |
| `agent.py` — agent invoked | `agent` | attrs: `agent` name |
| `callbacks.py` — `on_llm_start` / `on_llm_end` | `llm_call` | delta messages on start; tokens + stop_reason + response on end |
| `sql_tool.py` — tool invoked | `tool_call` | input on start; result_size + result on end |
| Any other tool | `tool_call` | Same pattern |

---

## What the Streamlit App Does with These Logs

```python
# 1. Load daily JSONL — filter to span events
spans = [json.loads(line) for line in open("2026-03-20.log") if '"event":"span' in line]

# 2. Group into sessions
traces = groupby(spans, key=lambda s: s["trace_id"])

# 3. Pair span.start + span.end by span_id → compute duration
# 4. Build tree via parent_span_id → waterfall / Gantt
# 5. Filter by tag → df[df.exception_id == "96000000-ytvte"]
# 6. Sum tokens across llm_call spans → cost per run
# 7. Find span.error / status:error → error rate, which tool/agent failed
# 8. Detect retries → duplicate seq values under same agent span
```

### Token Aggregation

Every `span.end` for `name == "llm_call"` carries:

```json
"attrs": {
  "tokens": {"input": 461, "output": 197, "cache_read": 15541, "cache_write": 0}
}
```

Because this is a consistent, top-level-accessible field on every LLM call span,
Streamlit can compute any aggregation with a simple pandas operation after loading
the JSONL into a dataframe:

```python
llm_spans = df[(df.event == "span.end") & (df.name == "llm_call")].copy()
llm_spans["tokens_input"]      = llm_spans.attrs.apply(lambda a: a.get("tokens", {}).get("input", 0))
llm_spans["tokens_output"]     = llm_spans.attrs.apply(lambda a: a.get("tokens", {}).get("output", 0))
llm_spans["tokens_cache_read"] = llm_spans.attrs.apply(lambda a: a.get("tokens", {}).get("cache_read", 0))

# Total tokens per run
llm_spans.groupby("trace_id")[["tokens_input","tokens_output","tokens_cache_read"]].sum()

# Daily spend (assuming a cost-per-token constant)
llm_spans.groupby(llm_spans.ts.dt.date)["tokens_input"].sum()

# Cache hit rate per run
llm_spans["cache_hit_rate"] = llm_spans.tokens_cache_read / (llm_spans.tokens_input + 1)
```

Yes — trivially easy. The schema is designed so token data never needs to be
extracted from free-text or nested structures.

### Planned Pages

| Page | What it shows |
|---|---|
| **Run Explorer** | Table of all runs: trace_id, date, duration, total tokens, cost, status |
| **Span Waterfall** | Gantt view of one run — each span as a row, width = duration, indented by parent. `span.error` in red, `status:error` in orange |
| **LLM Call Detail** | Selected llm_call: delta messages, response, token breakdown, cache hit % |
| **Analytics** | Token spend over time, cache hit %, avg cost per run, error rate, slowest tools |

---

## What Does NOT Belong in Trace Logs

These go at `DEBUG` level if needed — never in the TRACE schema:

- Full accumulated message history (only delta goes in `llm_call.attrs.delta`)
- Full system prompt (captured once at agent start if needed, at DEBUG)
- Raw SQL outside a `tool_call` span (already in `attrs.input`)
- Duplicate fields (`response_content` + `tool_call_args` for the same call)
- Free-form `trace_type` strings (replaced by `event` + `name` enum pair)
