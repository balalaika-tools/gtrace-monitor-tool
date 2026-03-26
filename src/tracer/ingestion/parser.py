from __future__ import annotations

import json
from datetime import datetime

from tracer.core.constants import KNOWN_FIELDS, SPAN_EVENTS
from tracer.core.logging import get_logger
from pathlib import Path

from tracer.models.trace import Span, SpanEvent, Trace, TraceSummary

logger = get_logger(__name__)


def parse_log_line(line: str) -> SpanEvent | None:
    """Parse a single log line into a SpanEvent, or None if not a span event."""
    line = line.strip()
    if not line:
        return None

    # Lines may be prefixed with a timestamp: "2026-03-26T08:10:03 {json}"
    raw = line
    if not line.startswith("{"):
        idx = line.find("{")
        if idx == -1:
            return None
        raw = line[idx:]

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Skipping non-JSON line: %s", line[:120])
        return None

    event = obj.get("event")
    if event not in SPAN_EVENTS:
        return None

    # Extract tags: any top-level field not in KNOWN_FIELDS
    tags = {k: v for k, v in obj.items() if k not in KNOWN_FIELDS and v is not None}

    try:
        ts = datetime.fromisoformat(obj["ts"])
    except (KeyError, ValueError):
        ts = datetime.now()

    return SpanEvent(
        ts=ts,
        event=event,
        span_name=obj.get("span_name", obj.get("name", "")),
        trace_id=obj.get("trace_id", ""),
        span_id=obj.get("span_id", ""),
        parent_span_id=obj.get("parent_span_id"),
        attrs=obj.get("attrs", {}),
        tags=tags,
        duration_ms=obj.get("duration_ms"),
        status=obj.get("status"),
    )


def parse_log_lines(lines: list[str]) -> list[SpanEvent]:
    """Parse multiple log lines, skipping invalid ones."""
    events = []
    for line in lines:
        evt = parse_log_line(line)
        if evt is not None:
            events.append(evt)
    logger.info("Parsed %d span events from %d lines", len(events), len(lines))
    return events


def reconstruct_spans(events: list[SpanEvent]) -> list[Span]:
    """Pair span.start + span.end/span.error by span_id into Span objects."""
    starts: dict[str, SpanEvent] = {}
    ends: dict[str, SpanEvent] = {}

    for evt in events:
        if evt.event == "span.start":
            starts[evt.span_id] = evt
        elif evt.event in ("span.end", "span.error"):
            ends[evt.span_id] = evt

    spans = []
    for span_id, start in starts.items():
        end = ends.get(span_id)
        merged_attrs = dict(start.attrs)
        merged_tags = dict(start.tags)

        if end:
            merged_attrs.update(end.attrs)
            merged_tags.update(end.tags)

        span = Span(
            span_id=span_id,
            span_name=start.span_name,
            trace_id=start.trace_id,
            parent_span_id=start.parent_span_id,
            started_at=start.ts,
            ended_at=end.ts if end else None,
            duration_ms=end.duration_ms if end else None,
            status=end.status if end else None,
            event=end.event if end else None,
            attrs=merged_attrs,
            tags=merged_tags,
        )
        spans.append(span)

    # Also include orphan ends (spans whose start was missed)
    for span_id, end in ends.items():
        if span_id not in starts:
            spans.append(
                Span(
                    span_id=span_id,
                    span_name=end.span_name,
                    trace_id=end.trace_id,
                    parent_span_id=end.parent_span_id,
                    started_at=end.ts,
                    ended_at=end.ts,
                    duration_ms=end.duration_ms,
                    status=end.status,
                    event=end.event,
                    attrs=end.attrs,
                    tags=end.tags,
                )
            )

    return sorted(spans, key=lambda s: s.started_at)


def build_span_tree(spans: list[Span]) -> list[Span]:
    """Compute depth for each span by walking parent_span_id links."""
    id_to_span = {s.span_id: s for s in spans}

    def _get_depth(span_id: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if span_id in visited:
            return 0
        visited.add(span_id)
        span = id_to_span.get(span_id)
        if not span or not span.parent_span_id:
            return 0
        return _get_depth(span.parent_span_id, visited) + 1

    for span in spans:
        span.depth = _get_depth(span.span_id)

    # Wire children
    for span in spans:
        span.children = []
    for span in spans:
        if span.parent_span_id and span.parent_span_id in id_to_span:
            id_to_span[span.parent_span_id].children.append(span)

    return sorted(spans, key=lambda s: s.started_at)


def group_into_traces(spans: list[Span]) -> list[Trace]:
    """Group spans by trace_id into Trace objects."""
    trace_map: dict[str, list[Span]] = {}
    for span in spans:
        trace_map.setdefault(span.trace_id, []).append(span)

    traces = []
    for trace_id, trace_spans in trace_map.items():
        # Collect all tags from root spans
        tags: dict = {}
        for s in trace_spans:
            if s.parent_span_id is None:
                tags.update(s.tags)

        # Fallback: collect tags from any span
        if not tags:
            for s in trace_spans:
                tags.update(s.tags)

        traces.append(
            Trace(
                trace_id=trace_id,
                spans=build_span_tree(trace_spans),
                tags=tags,
            )
        )

    return sorted(traces, key=lambda t: t.started_at or datetime.min, reverse=True)


def parse_and_build_traces(lines: list[str]) -> list[Trace]:
    """Full pipeline: raw lines → SpanEvents → Spans → Traces."""
    events = parse_log_lines(lines)
    spans = reconstruct_spans(events)
    return group_into_traces(spans)


def parse_and_store_traces(bulk_file: str, store_dir: str) -> list[TraceSummary]:
    """Two-tier pipeline: stream bulk JSONL file, split into per-trace files, return summaries.

    Reads the bulk file line by line — only one trace's worth of data is
    fully materialized in memory at a time (during summary computation).
    """
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)

    # Pass 1: stream bulk file, append each line to a per-trace file on disk
    trace_ids: list[str] = []
    trace_ids_seen: set[str] = set()
    # Keep per-trace file handles open for efficient appending
    handles: dict[str, object] = {}
    total_lines = 0
    valid_count = 0

    try:
        with open(bulk_file) as f:
            for line in f:
                total_lines += 1
                line = line.strip()
                if not line:
                    continue
                evt = parse_log_line(line)
                if evt is None:
                    continue
                valid_count += 1
                tid = evt.trace_id

                if tid not in trace_ids_seen:
                    trace_ids_seen.add(tid)
                    trace_ids.append(tid)
                    handles[tid] = open(store / f"{tid}.json", "w")

                handles[tid].write(line + "\n")
    finally:
        for fh in handles.values():
            fh.close()

    logger.info(
        "Split %d span events from %d lines into %d trace files",
        valid_count, total_lines, len(trace_ids),
    )

    # Pass 2: for each trace file, read it, reconstruct spans, compute summary
    # Only one trace's spans are in memory at a time
    summaries: list[TraceSummary] = []

    for trace_id in trace_ids:
        trace_file = store / f"{trace_id}.json"
        events: list[SpanEvent] = []
        with open(trace_file) as f:
            for line in f:
                evt = parse_log_line(line.strip())
                if evt is not None:
                    events.append(evt)

        spans = reconstruct_spans(events)
        summary = _build_summary(trace_id, spans)
        summaries.append(summary)
        # spans and events go out of scope here

    # Delete the bulk file — no longer needed
    Path(bulk_file).unlink(missing_ok=True)
    logger.info("Deleted bulk file %s", bulk_file)

    summaries.sort(key=lambda s: s.started_at or datetime.min, reverse=True)
    return summaries


def _build_summary(trace_id: str, spans: list[Span]) -> TraceSummary:
    """Compute a TraceSummary from a list of Spans, then the spans can be discarded."""
    # Tags from root spans
    tags: dict = {}
    for s in spans:
        if s.parent_span_id is None:
            tags.update(s.tags)
    if not tags:
        for s in spans:
            tags.update(s.tags)

    # Status from root run spans
    status = "ok"
    run_spans = [s for s in spans if s.span_name == "run" and s.parent_span_id is None]
    if run_spans:
        for s in run_spans:
            if s.event == "span.error" or s.status == "error":
                status = "error"
                break
    else:
        for s in spans:
            if s.event == "span.error":
                status = "error"
                break

    # Duration from run spans
    duration_ms = None
    run_durations = [s.duration_ms for s in run_spans if s.duration_ms is not None]
    if run_durations:
        duration_ms = sum(run_durations)

    # Timestamps
    started_at = min(s.started_at for s in spans) if spans else None

    # Token aggregation from llm_call spans
    llm_call_count = 0
    tool_call_count = 0
    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    for s in spans:
        if s.span_name == "llm_call":
            llm_call_count += 1
            tok = s.attrs.get("tokens", {})
            if isinstance(tok, dict):
                input_tokens += tok.get("input", 0) or 0
                output_tokens += tok.get("output", 0) or 0
                cache_read_tokens += tok.get("input_cache_read", 0) or tok.get("cache_read", 0) or 0
                cache_creation_tokens += tok.get("input_cache_creation", 0) or tok.get("cache_write", 0) or 0
                total_tokens += tok.get("total", 0) or 0
        elif s.span_name == "tool_call":
            tool_call_count += 1

    return TraceSummary(
        trace_id=trace_id,
        started_at=started_at,
        duration_ms=duration_ms,
        status=status,
        llm_call_count=llm_call_count,
        tool_call_count=tool_call_count,
        total_tokens=total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        tags=tags,
    )


def load_trace_from_disk(trace_id: str, store_dir: str) -> Trace | None:
    """Load a single trace from its on-disk JSON file and fully parse it."""
    trace_file = Path(store_dir) / f"{trace_id}.json"
    if not trace_file.exists():
        logger.warning("Trace file not found: %s", trace_file)
        return None

    lines = trace_file.read_text().splitlines()
    events = parse_log_lines(lines)
    spans = reconstruct_spans(events)

    # Build tags
    tags: dict = {}
    for s in spans:
        if s.parent_span_id is None:
            tags.update(s.tags)
    if not tags:
        for s in spans:
            tags.update(s.tags)

    return Trace(
        trace_id=trace_id,
        spans=build_span_tree(spans),
        tags=tags,
    )
