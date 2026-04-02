from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# ── Inline folder-picker component (uses browser's webkitdirectory) ──
_FOLDER_PICKER_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
*{box-sizing:border-box}
body{margin:0;padding:0;background:transparent;
  font-family:-apple-system,BlinkMacSystemFont,"Inter",sans-serif}
#btn{background:#4fc3f7;color:#0e1117;border:none;border-radius:8px;
  font-weight:600;font-size:0.85rem;padding:0 16px;width:100%;height:36px;
  cursor:pointer;transition:background .15s}
#btn:hover{background:#29b6f6}
#btn:disabled{background:#444;color:#777;cursor:default}
#fp{display:none}
</style></head><body>
<input type="file" id="fp" webkitdirectory multiple>
<button id="btn" onclick="document.getElementById('fp').click()">Browse Folder</button>
<script>
const btn=document.getElementById('btn'),
      fp=document.getElementById('fp');
function send(type,data){
  window.parent.postMessage(
    Object.assign({isStreamlitMessage:true,type},data),"*");
}
send("streamlit:componentReady",{apiVersion:1});
send("streamlit:setFrameHeight",{height:37});
fp.addEventListener('change',async function(){
  const files=[...this.files].filter(f=>/\\.(jsonl|log|txt|json)$/i.test(f.name));
  if(!files.length){
    send("streamlit:setComponentValue",{value:null,dataType:"json"});
    return;
  }
  btn.disabled=true;
  btn.textContent='Reading '+files.length+' file(s)\u2026';
  try{
    const parts=await Promise.all(files.map(f=>f.text()));
    btn.textContent='Browse Folder';
    send("streamlit:setComponentValue",{
      value:{content:parts.join('\\n'),file_count:files.length},
      dataType:"json"});
  }catch(e){
    btn.textContent='Browse Folder';
    send("streamlit:setComponentValue",{value:null,dataType:"json"});
  }finally{
    btn.disabled=false;
  }
});
</script></body></html>
"""

# Ensure src/ is on the path for local dev
_src = str(Path(__file__).resolve().parents[1])
if _src not in sys.path:
    sys.path.insert(0, _src)

from tracer.ingestion.cloudwatch import (
    copy_local_file_to_store,
    fetch_cloudwatch_logs,
    write_upload_to_store,
)
from tracer.ingestion.parser import parse_and_store_traces
from tracer.ui import state
from tracer.ui.components.date_picker import render_date_picker
from tracer.ui.components.filter_bar import render_filter_bar
from tracer.ui.components.trace_detail import render_trace_detail
from tracer.ui.components.trace_list import render_trace_list, render_trace_metrics
from tracer.ui.styles.theme import apply_theme

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _PROJECT_ROOT / ".cache" / "traces"
_TRACE_QUERY_PARAM = "trace_id"


@st.cache_resource
def _make_folder_picker():
    """Register the folder-picker component once per process (writes a temp index.html)."""
    import tempfile
    import streamlit.components.v1 as components

    d = Path(tempfile.mkdtemp())
    (d / "index.html").write_text(_FOLDER_PICKER_HTML, encoding="utf-8")
    return components.declare_component("folder_picker", path=str(d))


def _label_with_help(label: str, tooltip: str) -> str:
    """Render a small label + ? tooltip circle via st.markdown."""
    safe = tooltip.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return (
        f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px;">'
        f'<span style="font-size:0.82rem;color:#e0e0e0;font-weight:500;">{label}</span>'
        f'<span class="help-icon">?'
        f'<span class="help-tooltip">{safe}</span>'
        f'</span></div>'
    )


def _new_store_dir() -> str:
    """Create and return a fresh timestamped store directory under .cache/traces/.

    Wipes all existing subdirectories first to prevent orphans from previous sessions.
    """
    import shutil
    from datetime import datetime

    if _CACHE_DIR.exists():
        shutil.rmtree(_CACHE_DIR, ignore_errors=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    store = _CACHE_DIR / ts
    store.mkdir(parents=True, exist_ok=True)
    return str(store)


def _clear_trace_query_param():
    if _TRACE_QUERY_PARAM in st.query_params:
        del st.query_params[_TRACE_QUERY_PARAM]


def _sync_selected_trace_from_query():
    trace_id = st.query_params.get(_TRACE_QUERY_PARAM)
    if isinstance(trace_id, list):
        trace_id = trace_id[0] if trace_id else None
    if trace_id:
        state.set_selected_trace_id(trace_id)


# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="gTrace Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
state.init_state()


# ── Sidebar: data source ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="padding:4px 0 12px 0;line-height:1.1">'
        '<span style="font-size:1.5rem;font-weight:900;letter-spacing:-0.03em;color:#4fc3f7">g</span>'
        '<span style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em;color:#e0e0e0">Trace</span>'
        '<span style="font-size:1.5rem;font-weight:300;color:#9e9e9e;margin-left:6px">Monitor</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    source = st.radio(
        "Data source",
        options=["CloudWatch", "Local file"],
        index=1,
        key="source_radio",
        horizontal=True,
    )

    if source == "CloudWatch":
        date_range = render_date_picker()
        fetch = st.button("Fetch logs", type="primary", use_container_width=True)

        if fetch and date_range:
            start_dt, end_dt = date_range
            with st.spinner("Fetching from CloudWatch..."):
                try:
                    state.clear_data()
                    _clear_trace_query_param()
                    store_dir = _new_store_dir()
                    result = fetch_cloudwatch_logs(
                        start_dt,
                        end_dt,
                        store_dir,
                        progress_callback=lambda n, p: st.caption(f"Page {p} — {n} events"),
                    )
                    summaries = parse_and_store_traces(result.bulk_file, store_dir)
                    state.set_traces(summaries, store_dir)
                    state.set_data_source("cloudwatch")
                    st.success(f"Loaded {len(summaries)} traces from {result.event_count} events")
                    if result.truncated:
                        st.warning(
                            f"Fetch was capped at {result.limit:,} events. "
                            "Try a narrower date range to see all data. "
                            "You can adjust MAX_LOG_EVENTS in your .env."
                        )
                except Exception as e:
                    st.error(f"Failed to fetch logs: {e}")

    else:  # Local file
        local_mode = st.segmented_control(
            "mode",
            options=["📄 File(s)", "📁 Folder"],
            default="📄 File(s)",
            label_visibility="collapsed",
            key="local_mode",
        ) or "📄 File(s)"

        st.markdown("")  # breathing room

        if local_mode == "📄 File(s)":
            st.markdown(
                _label_with_help(
                    "Upload log file(s)",
                    "Accepted: .jsonl  .log  .txt  .json\n"
                    "Select multiple files at once (Ctrl/⌘+click)\n"
                    "Multiple traces per file are supported",
                ),
                unsafe_allow_html=True,
            )
            _upload_key = st.session_state.get("_upload_key", 0)
            uploaded_files = st.file_uploader(
                "Upload Log file(s)",
                type=["jsonl", "log", "txt", "json"],
                accept_multiple_files=True,
                label_visibility="collapsed",
                key=f"file_upload_{_upload_key}",
            )
            if st.session_state.get("_upload_flash"):
                st.success(st.session_state.pop("_upload_flash"))
            if uploaded_files:
                state.clear_data()
                _clear_trace_query_param()
                store_dir = _new_store_dir()
                combined = "\n".join(f.read().decode("utf-8") for f in uploaded_files)
                bulk_file = write_upload_to_store(combined, store_dir)
                summaries = parse_and_store_traces(bulk_file, store_dir)
                state.set_traces(summaries, store_dir)
                state.set_data_source("upload")
                label = f"{len(uploaded_files)} file(s)" if len(uploaded_files) > 1 else uploaded_files[0].name
                st.session_state["_upload_flash"] = f"Loaded {len(summaries)} traces from {label}"
                st.session_state["_upload_key"] = _upload_key + 1
                st.rerun()

            st.markdown("")
            st.markdown("")  # equalise bottom gap with Folder mode

        else:  # Folder
            st.markdown(
                _label_with_help(
                    "Browse folder",
                    "Picks a folder from your filesystem\n"
                    "Scans for: .jsonl  .log  .txt  .json\n"
                    "All matching files are merged before parsing",
                ),
                unsafe_allow_html=True,
            )
            folder_picker = _make_folder_picker()
            folder_result = folder_picker(key="folder_picker_widget", height=37)
            if folder_result is not None:
                result_id = f"{folder_result.get('file_count')}_{len(folder_result.get('content', ''))}"
                if st.session_state.get("_last_folder_id") != result_id:
                    try:
                        state.clear_data()
                        _clear_trace_query_param()
                        store_dir = _new_store_dir()
                        bulk_file = write_upload_to_store(folder_result["content"], store_dir)
                        summaries = parse_and_store_traces(bulk_file, store_dir)
                        state.set_traces(summaries, store_dir)
                        state.set_data_source("upload")
                        st.session_state["_last_folder_id"] = result_id
                        n = folder_result["file_count"]
                        st.success(f"Loaded {len(summaries)} traces from {n} file(s)")
                    except Exception as e:
                        st.error(f"Failed to parse folder: {e}")

        if st.button("🧪", key="sample_btn", help="Load sample logs", type="secondary"):
            sample_path = Path(__file__).resolve().parent / "samples" / "logs.jsonl"
            if sample_path.exists():
                state.clear_data()
                _clear_trace_query_param()
                store_dir = _new_store_dir()
                bulk_file = copy_local_file_to_store(str(sample_path), store_dir)
                summaries = parse_and_store_traces(bulk_file, store_dir)
                state.set_traces(summaries, store_dir)
                state.set_data_source("sample")
                st.success(f"Loaded {len(summaries)} traces from sample file")
            else:
                st.error(f"Sample file not found: {sample_path}")


# ── Main content ─────────────────────────────────────────────────────
_sync_selected_trace_from_query()

# Load full trace from disk only when viewing detail
_selected_trace = None
if state.get_selected_trace_id():
    with st.spinner("Loading trace..."):
        _selected_trace = state.load_selected_trace()

if _selected_trace:
    render_trace_detail(_selected_trace)
elif state.get_traces():
    st.markdown("## Traces")
    render_trace_metrics(state.get_filtered_traces())
    st.markdown("---")
    render_filter_bar(state.get_traces())
    st.caption(f"{len(state.get_filtered_traces())} of {len(state.get_traces())} traces shown")
    st.markdown("---")
    render_trace_list(state.get_filtered_traces())
else:
    # Empty state
    st.markdown(
        '<div style="padding:4px 0 24px 0;line-height:1.1">'
        '<span style="font-size:2rem;font-weight:900;letter-spacing:-0.03em;color:#4fc3f7">g</span>'
        '<span style="font-size:2rem;font-weight:700;letter-spacing:-0.02em;color:#e0e0e0">Trace</span>'
        '<span style="font-size:2rem;font-weight:300;color:#9e9e9e;margin-left:7px">Monitor</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div style="text-align:center; padding:60px 20px; color:#9e9e9e;">
            <div style="font-size:3rem; margin-bottom:16px;">🔍</div>
            <div style="font-size:1.2rem; margin-bottom:8px;">No traces loaded</div>
            <div style="font-size:0.9rem;">
                Use the sidebar to fetch logs from <b>CloudWatch</b> or upload a local <b>JSONL</b> file.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
