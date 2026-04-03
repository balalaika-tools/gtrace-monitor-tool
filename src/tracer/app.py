from __future__ import annotations

import streamlit as st

from tracer.ui import state
from tracer.ui.components.main_content import render_main_content
from tracer.ui.components.sidebar import render_sidebar
from tracer.ui.styles.theme import apply_theme

st.set_page_config(
    page_title="gTrace Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
state.init_state()
render_sidebar()
render_main_content()
