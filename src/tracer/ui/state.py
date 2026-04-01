from __future__ import annotations

import shutil

import streamlit as st

from tracer.models.filters import FilterState
from tracer.models.trace import Trace, TraceSummary

# Keys used in st.session_state
_TRACES = "traces"
_FILTERED_TRACES = "filtered_traces"
_FILTER_STATE = "filter_state"
_SELECTED_TRACE_ID = "selected_trace_id"
_DATA_SOURCE = "data_source"
_TRACE_STORE_DIR = "trace_store_dir"


def init_state():
    """Initialize session state with defaults."""
    defaults = {
        _TRACES: [],
        _FILTERED_TRACES: [],
        _FILTER_STATE: FilterState(),
        _SELECTED_TRACE_ID: None,
        _DATA_SOURCE: None,
        _TRACE_STORE_DIR: None,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def clear_data():
    """Release all trace data from memory and wipe the on-disk store."""
    old_dir = st.session_state.get(_TRACE_STORE_DIR)
    if old_dir:
        shutil.rmtree(old_dir, ignore_errors=True)

    st.session_state[_TRACES] = []
    st.session_state[_FILTERED_TRACES] = []
    st.session_state[_SELECTED_TRACE_ID] = None
    st.session_state[_FILTER_STATE] = FilterState()
    st.session_state[_TRACE_STORE_DIR] = None
    # Reset folder-picker dedup so the same folder can be re-selected
    st.session_state.pop("_last_folder_id", None)


def get_traces() -> list[TraceSummary]:
    return st.session_state.get(_TRACES, [])


def set_traces(summaries: list[TraceSummary], store_dir: str):
    st.session_state[_TRACES] = summaries
    st.session_state[_TRACE_STORE_DIR] = store_dir
    # Re-apply filters
    fs = get_filter_state()
    st.session_state[_FILTERED_TRACES] = fs.apply(summaries)


def get_filtered_traces() -> list[TraceSummary]:
    return st.session_state.get(_FILTERED_TRACES, [])


def get_filter_state() -> FilterState:
    return st.session_state.get(_FILTER_STATE, FilterState())


def set_filter_state(fs: FilterState):
    st.session_state[_FILTER_STATE] = fs
    summaries = get_traces()
    st.session_state[_FILTERED_TRACES] = fs.apply(summaries)


def get_selected_trace_id() -> str | None:
    return st.session_state.get(_SELECTED_TRACE_ID)


def set_selected_trace_id(trace_id: str | None):
    st.session_state[_SELECTED_TRACE_ID] = trace_id


def get_trace_store_dir() -> str | None:
    return st.session_state.get(_TRACE_STORE_DIR)


def load_selected_trace() -> Trace | None:
    """Load the full Trace for the currently selected trace_id from disk."""
    trace_id = get_selected_trace_id()
    store_dir = get_trace_store_dir()
    if not trace_id or not store_dir:
        return None

    from tracer.ingestion.parser import load_trace_from_disk

    return load_trace_from_disk(trace_id, store_dir)


def set_data_source(source: str):
    st.session_state[_DATA_SOURCE] = source


def get_data_source() -> str | None:
    return st.session_state.get(_DATA_SOURCE)
