from __future__ import annotations

from dataclasses import dataclass, field

from tracer.models.trace import TraceSummary


@dataclass
class FilterCriteria:
    """A single filter: key + value to match on trace tags or top-level fields."""

    key: str
    value: str


@dataclass
class FilterState:
    """Collection of active filters (AND logic)."""

    filters: list[FilterCriteria] = field(default_factory=list)

    def add(self, key: str, value: str) -> None:
        self.filters.append(FilterCriteria(key=key, value=value))

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.filters):
            self.filters.pop(index)

    def clear(self) -> None:
        self.filters.clear()

    @property
    def is_active(self) -> bool:
        return len(self.filters) > 0

    @property
    def active_keys(self) -> list[str]:
        return [f.key for f in self.filters]

    def apply(self, summaries: list[TraceSummary]) -> list[TraceSummary]:
        if not self.filters:
            return summaries
        result = summaries
        for f in self.filters:
            result = [s for s in result if _summary_matches(s, f)]
        return result


def _summary_matches(summary: TraceSummary, criteria: FilterCriteria) -> bool:
    """Check if a TraceSummary matches the filter criteria."""
    # Check tags (exception_id, session_id, etc.)
    if criteria.key in summary.tags and str(summary.tags[criteria.key]) == criteria.value:
        return True
    # Check direct fields
    if criteria.key == "trace_id" and summary.trace_id == criteria.value:
        return True
    if criteria.key == "status" and summary.status == criteria.value:
        return True
    return False


def get_filterable_keys(summaries: list[TraceSummary]) -> list[str]:
    """Collect all unique filterable keys across all trace summaries."""
    keys: set[str] = {"trace_id", "status"}
    for s in summaries:
        keys.update(s.tags.keys())
    keys.discard("")
    return sorted(keys)
