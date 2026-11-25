"""Dashboard screen (Req 7.1-7.10)."""
from __future__ import annotations

import logging

import streamlit as st

from logistic_ai.dashboard.kpi import (
    SUMMARY_TABLE,
    DashboardDataError,
    Kpis,
    load_kpis,
)
from logistic_ai.ui.deps import AppDeps

_LOGGER = logging.getLogger("logistic_ai.ui.dashboard")

DASHBOARD_ROLES = frozenset({"TRANSPORT_OFFICE", "MATERIAL_RESPONSIBLE"})
TITLE = "Dashboard"
ERROR_MESSAGE = "Dashboard verileri şu anda görüntülenemiyor"
LABEL_TOTAL = "Tüm Seferler"
LABEL_DELAYED = "Geciken Seferler"
LABEL_COMPLETED = "Tamamlanan Seferler"
LABEL_IN_PROGRESS = "Devam Eden Seferler"
LABEL_DELAY_RATE = "Gecikme Oranı"
DONUT_HOLE = 0.55


def dashboard_visible(role: object) -> bool:
    """True only for TRANSPORT_OFFICE and MATERIAL_RESPONSIBLE (Req 7.1, 7.2)."""
    value = getattr(role, "value", role)
    return isinstance(value, str) and value in DASHBOARD_ROLES


def _donut(kpis: Kpis):
    import plotly.graph_objects as go

    fig = go.Figure(
        go.Pie(
            labels=[LABEL_COMPLETED, LABEL_IN_PROGRESS],
            values=[kpis.completed, kpis.in_progress],
            hole=DONUT_HOLE,
        )
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
    return fig


def render_dashboard(deps: AppDeps) -> None:
    try:
        ctx = deps.user_context.current()
        userid = getattr(ctx, "userid", None) or getattr(ctx, "username")
        if not deps.permission_service.check(userid, "TABLE", SUMMARY_TABLE).allowed:
            return
    except Exception as exc:
        _LOGGER.warning("dashboard access check failed: %s", type(exc).__name__)
        return

    st.subheader(TITLE)
    try:
        kpis = load_kpis(deps.data_repo)
    except DashboardDataError:
        st.error(ERROR_MESSAGE)
        return
    except Exception as exc:
        _LOGGER.error("dashboard failed: %s", type(exc).__name__)
        st.error(ERROR_MESSAGE)
        return

    cols = st.columns(3)
    cols[0].metric(LABEL_TOTAL, kpis.total)
    cols[1].metric(LABEL_COMPLETED, kpis.completed)
    cols[2].metric(LABEL_IN_PROGRESS, kpis.in_progress)
    delayed_cols = st.columns(2)
    delayed_cols[0].metric(LABEL_DELAYED, kpis.delayed)
    delayed_cols[1].metric(LABEL_DELAY_RATE, f"{kpis.delay_rate_pct:.1f}%")
    st.plotly_chart(_donut(kpis), use_container_width=True)
