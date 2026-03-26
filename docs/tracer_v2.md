# Tracer v2 — Developer Guide

How to use `src/exceptionist/core/tracer.py` in any LangChain/LangGraph application.

---

## What it does

Emits structured JSON log records via `logger.trace()`. Every record is a single
JSON object serialised to one stdout line by `_JSONFormatter`. The result is a
structured log stream (captured by CloudWatch in prod, redirectable to a file
locally) that can be parsed into a tree of timed operations grouped by session.

Each span covers one logical operation. A span has:
- a **start** event when the operation begins
- an **end** event when it completes (with duration + status)
- an **error** event if a Python exception propagates out of it

---

## Import

Always import the module-level singleton. Never instantiate `Tracer` directly.

```python
from exceptionist.core.tracer import tracer
```

For LangChain callback instrumentation also import:

```python
from exceptionist.core.tracer import tracer, serialise_lc_messages
```

---

## Span taxonomy

The allowed parent → child hierarchy. Violations log a `WARNING` but never raise.

```
null
└── run              one per top-level job / session turn
    └── agent        one per agent invoked
        └── llm_call one per LLM API call
            └── tool_call  one per tool invocation
                └── agent  sub-agent spawned inside a tool (e.g. SQL fixer)
```

---

## API reference

### `tracer.start_trace(trace_id: str)`

Sets the current trace ID on a `ContextVar`. All spans opened after this call
in the same async Task / thread inherit this value as `trace_id`.

**Call once per invocation**, before any spans are opened — typically in the
entrypoint thread/task, not inside the business logic.

```python
tracer.start_trace(session_id)
```

---

### `tracer.span(name, attrs, tags)` — context manager

The primary API. Use whenever the span's scope maps to a lexical block.

```python
with tracer.span("agent", attrs={"agent": "main"}) as span:
    result = await agent.ainvoke(...)
    span.set("reason_code", result.reason_code)   # end-time attr
```

- **`name`** — one of the taxonomy values: `run`, `agent`, `llm_call`, `tool_call`
- **`attrs`** — dict passed at open time (start-time data). Also accumulates
  end-time data via `span.set()`. Flushed into `span.end`.
- **`tags`** — dict promoted to top-level JSON fields (filterable without parsing
  `attrs`). Merged with inherited tags from parent spans.

On clean exit emits `span.end status:ok`.
On exception emits `span.error status:error` then re-raises.

---

### `SpanContext.set(key, value)`

Accumulate end-time data onto the span while it is in flight.
All `.set()` calls are flushed into `attrs` on `span.end`.

```python
with tracer.span("llm_call") as span:
    response = llm.invoke(messages)
    span.set("tokens", response.usage_metadata)
    span.set("stop_reason", response.stop_reason)
```

---

### `SpanContext.fail(reason: str = "")`

Mark the span as a **business-level failure** without raising an exception.
The span still emits `span.end` (not `span.error`) but with `status: "error"`.

Use this when the operation completed but the outcome is bad:

```python
with tracer.span("agent") as span:
    result = await agent.ainvoke(...)
    if result is None:
        span.fail("run_limit_exceeded")
        return error_result
```

Do **not** call `fail()` for Python exceptions — those are handled automatically
by the context manager and emit `span.error`.

---

### `tracer.open_span(name, attrs, tags)` → `SpanContext`
### `tracer.close_span(ctx, end_attrs)`
### `tracer.error_span(ctx, exc)`

The open/close API for use in LangChain callback handlers, where the span's
start and end happen in separate methods (`on_chat_model_start` / `on_llm_end`).

```python
# on_chat_model_start
ctx = tracer.open_span("llm_call", attrs={"model": model, "seq": seq})
self._open_spans[run_id] = ctx

# on_llm_end
ctx = self._open_spans.pop(run_id)
tracer.close_span(ctx, end_attrs={"tokens": tokens, "response": response})

# on_llm_error
ctx = self._open_spans.pop(run_id)
tracer.error_span(ctx, exc)
```

**Gotcha:** `open_span()` does NOT update the ContextVars. The parent span is
captured at call time from whatever ContextVar state is current. If you need
child spans to resolve this span as their parent, use `span()` instead.

---

### `serialise_lc_messages(messages: list) → list[dict]`

Converts LangChain `BaseMessage` instances to JSON-serialisable dicts.
Truncates string content to 15 000 chars. Preserves `tool_call_id` on
`ToolMessage`. Keeps tool_use blocks intact.

```python
delta = serialise_lc_messages(all_messages[prev_count:])
```

---

## Tag inheritance

Tags are inherited automatically by child spans. Set a tag once on the root
span and every descendant carries it — no need to pass it down manually.

```python
# Set exception_id on root — all children inherit it automatically
with tracer.span("run", tags={"exception_id": exception_id}):
    with tracer.span("agent", attrs={"agent": "main"}):
        # this span's log line also has "exception_id": "..." at top level
        with tracer.span("llm_call") as span:
            ...
```

---

## Full instrumentation example

```python
# Entrypoint (called once per invocation, before async work starts)
tracer.start_trace(session_id)

# Top-level run span — tags propagate to all children
with tracer.span("run", tags={"exception_id": exception_id}):

    # One agent span per agent invoked
    with tracer.span("agent", attrs={"agent": "main"}) as agent_span:
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_msg}]},
                config={"callbacks": [tracing_handler]},   # handles llm_call spans
            )
        except Exception as exc:
            agent_span.fail(str(exc))
            return error_result

        agent_span.set("reason_code", result.reason_code)

    # Tool span — inside a @tool decorated async function
    with tracer.span("tool_call", attrs={"tool": "run_sql_query", "input": {"query": sql}}) as span:
        result = await _run_query(sql)
        span.set("result", result)
```

---

## Gotchas

### 1. `start_trace()` must be called before any spans

If `start_trace()` is never called, `trace_id` will be `null` on every span.
The Streamlit parser will still work but cannot group spans into sessions.

Always call it in the **thread/task entrypoint**, not inside a helper function,
because `ContextVar` state is per-task. Calling it inside an `asyncio.Task`
that was spawned later won't affect spans opened in the parent task.

In this codebase it is called in `_run_in_background` in `main.py` — the
background thread that owns the full analysis lifecycle.

---

### 2. `open_span()` does not update ContextVars

If you open a span via `open_span()` and then open child spans inside it using
`span()`, the children will NOT see the `open_span` span as their parent —
because ContextVars were never updated.

```python
# WRONG — child sees the outer agent span as parent, not this llm_call
ctx = tracer.open_span("llm_call")
with tracer.span("tool_call"):   # parent_span_id = agent.span_id, not llm_call
    ...

# CORRECT — use span() when you need children to resolve their parent
with tracer.span("llm_call"):
    with tracer.span("tool_call"):   # parent_span_id = llm_call.span_id ✓
        ...
```

`open_span()` is designed for LangChain callbacks only, where no child spans
are opened between `open_span` and `close_span`.

---

### 3. `span.fail()` vs letting an exception propagate

| Scenario | What to do | Result |
|---|---|---|
| Python exception raised and not caught | Let it propagate through `with tracer.span()` | `span.error` emitted automatically |
| Operation completed, outcome is bad (business error) | Call `span.fail(reason)` before returning | `span.end status:error` |
| Don't call `fail()` AND catch the exception yourself | The span will end with `status:ok` | Misleading — don't do this |

If you catch an exception inside a span and return an error object without
re-raising, you must call `span.fail()` explicitly or the span will be `ok`.

---

### 4. Tags vs attrs

| | `tags` | `attrs` |
|---|---|---|
| Position in JSON | Top-level fields | Nested under `"attrs"` key |
| Filtering | Direct pandas column: `df["exception_id"]` | Requires `df["attrs"].apply(...)` |
| Use for | Business keys, IDs, category labels | Payload, content, metrics |
| Inherited by children | Yes — automatically | No |
| Truncated | No | Yes (per truncation policy) |

Use `tags` for anything you want to filter on in Streamlit without extra work.
Use `attrs` for content you want to inspect in a detail panel.

---

### 5. `tool_call` is causally parented to `llm_call`, not `agent`

Even though the `llm_call` span is already **closed** when a tool runs, the
tracer wires `tool_call` as a child of the `llm_call` that triggered it —
not a sibling under `agent`. This gives a causal waterfall:

```
agent (main)
├── llm_call seq:1        ← decides to call a tool
│   └── tool_call         ← triggered by this call
│       └── agent (sql_fixer)   ← sub-agent inside the tool
│           └── llm_call seq:1
├── llm_call seq:2        ← processes tool result
└── llm_call seq:3        ← final answer
```

**How it works:** LangGraph runs each node (LLM node, Tool node) as a **separate
`asyncio.Task`** created with `copy_context()`. ContextVar mutations made inside
the LLM node's task (e.g. in `on_llm_end`) are invisible to the tool node's task.

Instead, `on_llm_end` stores `agent_span_id → llm_span_id` in the callback
handler's instance-level dict `_last_llm_spans`. Tool code reads it explicitly:

```python
from exceptionist.ai_engine.callbacks import tracing_handler
from exceptionist.core.tracer import tracer, _span_id

llm_parent = tracing_handler.last_llm_span(_span_id.get())
with tracer.span("tool_call", attrs={...}, parent_span_id=llm_parent) as span:
    ...
```

`_span_id.get()` works here because the `agent` span's ContextVar was set
**before** any tasks were created, so it propagates via `copy_context()` into
the tool node's task. It is the stable cross-task bridge.

This works for all nesting patterns (parallel tools, sub-agents, deeply nested
agents) because each `tracer.span("agent")` layer creates a unique `span_id`
as its own lookup key, fully isolated from other agents in the same session.
If `last_llm_span` returns `None` (no prior llm_call found), the span falls
back to normal ContextVar-based parenting — no crash, graceful degradation.

---

### 6. Hierarchy validation is a warning, not an error

If you open a `tool_call` directly under a `run` span (skipping `agent` and
`llm_call`), the tracer logs a `WARNING` and continues. The span is still
emitted with the actual `parent_span_id`. The Streamlit waterfall will render
it at the wrong indentation level but the data is not lost.

Fix violations when you see them — don't rely on the warning being harmless in
all future Streamlit visualisations.

---

### 6. Thread safety with `open_span`

`SpanContext` is created fresh per call and is **never shared** between spans.
Each concurrent tool call gets its own instance. `ContextVar` is both
thread-safe and async-safe (each OS thread and each asyncio `Task` has its
own copy).

The only unsafe pattern: manually passing a `SpanContext` to another thread and
calling `.set()` on it concurrently. The `attrs` dict is not protected by a lock.
Don't do this — each span should be owned by exactly one thread/task.

---

### 7. Log level must be TRACE

Spans are emitted via `logger.trace()` which is level 25 (between INFO=20 and
WARNING=30). If `LOG_LEVEL` is set to `INFO` or higher, no span events are
written and the log file will have nothing for the Streamlit parser to read.

Set `LOG_LEVEL=TRACE` in your environment when observability is needed.

---

### 8. LangGraph overwrites LangChain `tags` — never use them for agent name

When you create a LangGraph agent and pass `tags=["my_agent"]` to the LLM,
LangGraph replaces that list with internal step tags like `["seq:step:1"]` at
runtime. The LangChain `on_chat_model_start` callback receives those internal
tags — not your values.

**Do not read `tags` inside the callback to identify the agent.**

Instead, the tracer uses a dedicated `_agent_name` ContextVar. When you open an
`agent` span via `tracer.span("agent", attrs={"agent": "my_agent"})`, the
`span()` context manager sets `_agent_name` to `"my_agent"`. The callback reads
`_agent_name.get()` so every `llm_call` span inside that agent correctly shows
`"agent": "my_agent"`.

This means the `attrs={"agent": "..."}` key on your `agent` span is load-bearing
— it must match the logical name you want to see in the traces.

---

### 9. Retries appear as sibling spans

If an LLM call fails and the framework retries it, there will be two consecutive
`llm_call` spans under the same parent `agent` span, both with the same `seq`
value. The first has `status:error`, the second `status:ok`. This is intentional
— retries are not a special concept in the schema.

The Streamlit app detects retries by finding duplicate `seq` values under one
`agent` span.

---

## Adding a new tool

Wrap the tool body with a `tool_call` span. Put start-time data in `attrs`,
accumulate end-time data with `span.set()`.

```python
from exceptionist.ai_engine.callbacks import tracing_handler
from exceptionist.core.tracer import tracer, _span_id

@tool
async def my_tool(param: str) -> str:
    llm_parent = tracing_handler.last_llm_span(_span_id.get())
    with tracer.span("tool_call", attrs={"tool": "my_tool", "input": {"param": param}}, parent_span_id=llm_parent) as span:
        result = await do_work(param)
        span.set("result", result)
        return result
```

If the tool can fail in a business sense (bad result but no exception):

```python
        if not result:
            span.fail("no_data_returned")
            return "No results found."
        span.set("result", result)
        return result
```

---

## Adding a new agent

Wrap the agent invocation with an `agent` span and pass `tracing_handler` as a
callback so the agent's internal LLM calls are automatically instrumented.

```python
from exceptionist.ai_engine.callbacks import tracing_handler
from exceptionist.core.tracer import tracer

with tracer.span("agent", attrs={"agent": "my_agent"}) as span:
    result = await my_agent.ainvoke(
        {"messages": [...]},
        config={"callbacks": [tracing_handler]},
    )
    span.set("outcome", result.get("structured_response"))
```
