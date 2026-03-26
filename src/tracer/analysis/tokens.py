from __future__ import annotations

from dataclasses import dataclass

from tracer.models.trace import Span, Trace


@dataclass
class TokenSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0


def _extract_tokens(span: Span) -> dict:
    """Extract token dict from an llm_call span's attrs."""
    tokens = span.attrs.get("tokens", {})
    if not isinstance(tokens, dict):
        return {}
    return tokens


def summarize_span_tokens(span: Span) -> TokenSummary:
    """Get token summary for a single llm_call span."""
    tokens = _extract_tokens(span)
    inp = tokens.get("input", 0) or 0
    out = tokens.get("output", 0) or 0
    cache_read = tokens.get("input_cache_read", 0) or tokens.get("cache_read", 0) or 0
    cache_creation = tokens.get("input_cache_creation", 0) or tokens.get("cache_write", 0) or 0
    total = tokens.get("total", 0) or (inp + out)

    return TokenSummary(
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        total_tokens=total,
        llm_call_count=1,
    )


def summarize_trace_tokens(trace: Trace) -> TokenSummary:
    """Aggregate token usage across all llm_call spans in a trace."""
    summary = TokenSummary()
    for span in trace.llm_call_spans:
        span_summary = summarize_span_tokens(span)
        summary.input_tokens += span_summary.input_tokens
        summary.output_tokens += span_summary.output_tokens
        summary.cache_read_tokens += span_summary.cache_read_tokens
        summary.cache_creation_tokens += span_summary.cache_creation_tokens
        summary.total_tokens += span_summary.total_tokens
        summary.llm_call_count += 1
    return summary
