SPAN_NAMES = {"run", "agent", "llm_call", "tool_call"}
SPAN_EVENTS = {"span.start", "span.end", "span.error"}

VALID_CHILDREN: dict[str | None, set[str]] = {
    None: {"run"},
    "run": {"agent"},
    "agent": {"llm_call"},
    "llm_call": {"tool_call"},
    "tool_call": {"agent"},
}

# Known top-level fields on every span event (everything else is a tag)
KNOWN_FIELDS = {
    "ts",
    "level",
    "logger",
    "message",
    "event",
    "span_name",
    "trace_id",
    "span_id",
    "parent_span_id",
    "duration_ms",
    "status",
    "attrs",
}
