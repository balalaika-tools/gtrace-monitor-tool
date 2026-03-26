from __future__ import annotations

from datetime import date, datetime, time, timedelta

import streamlit as st


def render_date_picker() -> tuple[datetime, datetime] | None:
    """Render date range picker. Returns (start, end) datetimes or None if not submitted."""
    st.markdown("#### Date Range")

    col1, col2 = st.columns(2)
    today = date.today()

    with col1:
        start_date = st.date_input(
            "Start date",
            value=today - timedelta(days=1),
            max_value=today,
            key="start_date",
        )
        start_time = st.time_input("Start time", value=time(0, 0), key="start_time")

    with col2:
        end_date = st.date_input(
            "End date",
            value=today,
            max_value=today,
            key="end_date",
        )
        end_time = st.time_input("End time", value=time(23, 59, 59), key="end_time")

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, end_time)

    if start_dt >= end_dt:
        st.warning("Start must be before end.")
        return None

    return start_dt, end_dt
