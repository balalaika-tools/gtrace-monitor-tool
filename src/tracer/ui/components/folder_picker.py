from __future__ import annotations

from pathlib import Path

import streamlit as st

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


@st.cache_resource
def make_folder_picker():
    """Register the folder-picker component once per process (writes a temp index.html)."""
    import tempfile
    import streamlit.components.v1 as components

    d = Path(tempfile.mkdtemp())
    (d / "index.html").write_text(_FOLDER_PICKER_HTML, encoding="utf-8")
    return components.declare_component("folder_picker", path=str(d))
