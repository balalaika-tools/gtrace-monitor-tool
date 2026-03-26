from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SpanEvent:
    """A single raw span event line from the logs."""

    ts: datetime
    event: str  # span.start | span.end | span.error
    span_name: str  # run | agent | llm_call | tool_call
    trace_id: str
    span_id: str
    parent_span_id: str | None
    attrs: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    duration_ms: int | None = None
    status: str | None = None  # ok | error


@dataclass
class Span:
    """A reconstructed span (start + end paired)."""

    span_id: str
    span_name: str
    trace_id: str
    parent_span_id: str | None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str | None = None
    event: str | None = None  # span.end or span.error
    attrs: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    depth: int = 0
    children: list[Span] = field(default_factory=list)


@dataclass
class Trace:
    """A complete trace (all spans for one trace_id)."""

    trace_id: str
    spans: list[Span] = field(default_factory=list)
    tags: dict = field(default_factory=dict)

    @property
    def started_at(self) -> datetime | None:
        if not self.spans:
            return None
        return min(s.started_at for s in self.spans)

    @property
    def ended_at(self) -> datetime | None:
        ends = [s.ended_at for s in self.spans if s.ended_at]
        return max(ends) if ends else None

    @property
    def duration_ms(self) -> int | None:
        run_spans = [s for s in self.spans if s.span_name == "run" and s.duration_ms is not None]
        if run_spans:
            return sum(s.duration_ms for s in run_spans)
        return None

    @property
    def status(self) -> str:
        # Derive trace status from root run span(s) only, not child spans
        run_spans = [s for s in self.spans if s.span_name == "run" and s.parent_span_id is None]
        if run_spans:
            for s in run_spans:
                if s.event == "span.error":
                    return "error"
                if s.status == "error":
                    return "error"
            return "ok"
        # Fallback: no run spans, check for span.error events only
        for s in self.spans:
            if s.event == "span.error":
                return "error"
        return "ok"

    @property
    def root_spans(self) -> list[Span]:
        return [s for s in self.spans if s.parent_span_id is None]

    @property
    def llm_call_spans(self) -> list[Span]:
        return [s for s in self.spans if s.span_name == "llm_call"]

    @property
    def tool_call_spans(self) -> list[Span]:
        return [s for s in self.spans if s.span_name == "tool_call"]


@dataclass
class TraceSummary:
    """Lightweight summary of a trace for the list view. No Span objects."""

    trace_id: str
    started_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "ok"
    llm_call_count: int = 0
    tool_call_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    tags: dict = field(default_factory=dict)
