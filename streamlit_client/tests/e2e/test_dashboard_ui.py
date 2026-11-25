"""Dashboard + UI tests (task 12.5): Streamlit ``AppTest`` (no server, no AWS), real Excel data.

Run:  python -m pytest tests/e2e/test_dashboard_ui.py -v   (from streamlit_client/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dashboard_ui_helpers as U  # noqa: E402

_SKIP = U.skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")

ROLES = ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE", "ADMIN")
DASH_ROLES = ("TRANSPORT_OFFICE", "MATERIAL_RESPONSIBLE")
NON_DASH_ROLES = ("SUPPLIER", "ADMIN")


@pytest.fixture(scope="module")
def world_cls():
    return U.World


@pytest.fixture
def world(world_cls):
    return world_cls()


def logged_in(world, role):
    at = U.make_app(world)
    U.login(at, world.creds[role])
    assert not at.exception, [e.value for e in at.exception]
    return at


def texts(elements) -> list[str]:
    return [str(getattr(e, "value", e)) for e in elements]


# ------------------------------------------------------------------ login screen
def test_UI_01_login_screen_title_three_elements_masked_password(world):
    """UI-01 login screen: title, username input, masked password input, submit button."""
    at = U.make_app(world)
    at.run()
    assert not at.exception
    assert texts(at.title) == ["Logistics AI Assistant"]
    assert [t.label for t in at.text_input] == ["Kullanıcı adı", "Şifre"]
    assert [b.label for b in at.button] == ["Giriş yap"]
    pw = at.text_input(key="login_password")
    assert pw.proto.type == pw.proto.PASSWORD  # masked
    assert at.text_input(key="login_username").proto.type == pw.proto.DEFAULT
    assert not at.metric and not at.sidebar.radio


@pytest.mark.parametrize("role", ROLES)
def test_UI_02_login_succeeds_per_role_header_shows_username_and_role(world, role):
    """UI-02 real Excel user of each role logs in; header shows username and role; password not shown."""
    cred = world.creds[role]
    at = logged_in(world, role)
    shown = texts(at.text) + texts(at.sidebar.text)
    assert cred.username in shown and role in shown
    assert not [t for t in at.text_input if t.key == "login_password"]  # login form gone
    page = " ".join(texts(at.text) + texts(at.markdown) + texts(at.error)) + repr(at.session_state)
    assert not U.leaks(page, cred.password)
    assert at.session_state["role"] == role and at.session_state["username"] == cred.username
    assert ("login", cred.username, True) in world.audit.events


def test_UI_03_wrong_password_stays_on_login_with_generic_error(world):
    """UI-03 bad password: no session, generic error, still the login form."""
    cred = world.creds["SUPPLIER"]
    at = U.make_app(world)
    at.run()
    at.text_input(key="login_username").input(cred.username)
    at.text_input(key="login_password").input("definitely-not-the-password")
    [b for b in at.button if b.label == "Giriş yap"][0].click()
    at.run()
    assert "session_token" not in at.session_state
    assert [e.value for e in at.error]
    assert [t.label for t in at.text_input] == ["Kullanıcı adı", "Şifre"]


# ------------------------------------------------------------------ logout / session end
@pytest.mark.parametrize("role", ROLES)
def test_UI_04_logout_clears_session_and_returns_to_login(world, role):
    """UI-04 logout button clears session keys + history and shows the login screen."""
    at = logged_in(world, role)
    at.button(key="logout_button").click()
    at.run()
    assert not at.exception
    for key in ("session_token", "userid", "username", "role", "chat_history", "chat_runtime_session_id"):
        assert key not in at.session_state
    assert texts(at.title) == ["Logistics AI Assistant"]
    assert [t.label for t in at.text_input] == ["Kullanıcı adı", "Şifre"]
    assert ("logout", world.creds[role].username) in world.audit.events


def test_UI_05_session_end_shows_login(world):
    """UI-05 idle timeout (clock past 30 min) -> router shows the login screen with the session-ended message."""
    from logistic_ai.session.manager import SESSION_ENDED_MESSAGE

    at = logged_in(world, "SUPPLIER")
    world.clock.advance(31 * 60)
    at.run()
    assert [t.label for t in at.text_input] == ["Kullanıcı adı", "Şifre"]
    assert SESSION_ENDED_MESSAGE in texts(at.error)
    assert "session_token" not in at.session_state


def test_UI_06_no_session_shows_login_and_unknown_role_never_shows_content(world):
    """UI-06 forged state with an unknown role: login screen, no content, session wiped."""
    state = world.session_state_for("SUPPLIER")
    state["role"] = "GOD"
    at = U.make_app(world, state=state)
    at.run()
    assert [t.label for t in at.text_input] == ["Kullanıcı adı", "Şifre"]
    assert "role" not in at.session_state and not at.chat_input


# ------------------------------------------------------------------ chat
def test_UI_07_chat_message_stored_user_and_assistant_and_visible(world):
    """UI-07 sending a message stores user+assistant in history; history visible on the next run."""
    cred = world.creds["SUPPLIER"]
    at = logged_in(world, "SUPPLIER")
    assert at.session_state["chat_history"] == []
    at.chat_input[0].set_value("merhaba ilk soru").run()
    assert not at.exception
    hist = at.session_state["chat_history"]
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[0]["content"] == "merhaba ilk soru"
    assert hist[1]["content"] == f"answer-for-{cred.userid}:merhaba ilk soru"
    at.chat_input[0].set_value("ikinci soru").run()
    assert [m["role"] for m in at.session_state["chat_history"]] == ["user", "assistant"] * 2
    visible = [m.markdown[0].value if m.markdown else "" for m in at.chat_message]
    shown = texts(at.text)
    assert "merhaba ilk soru" in shown and f"answer-for-{cred.userid}:merhaba ilk soru" in shown
    assert len(at.chat_message) >= 2 and visible is not None
    # the real transport received prior history and the verified token only
    assert world.backend.history_by_userid[cred.userid] == ["merhaba ilk soru", "ikinci soru"]


def test_UI_08_new_chat_button_resets_history_and_runtime_session_id_without_logout(world):
    """UI-08 'Yeni sohbet': history emptied, new runtime session id (>=33 chars), still logged in."""
    at = logged_in(world, "SUPPLIER")
    assert "Yeni sohbet" in [b.label for b in at.button]
    at.chat_input[0].set_value("eski konuşma").run()
    old_id = at.session_state["chat_runtime_session_id"]
    token = at.session_state["session_token"]
    assert len(at.session_state["chat_history"]) == 2
    at.button(key="new_chat_button").click().run()
    assert not at.exception
    assert at.session_state["chat_history"] == []
    new_id = at.session_state["chat_runtime_session_id"]
    assert new_id != old_id and len(new_id) >= 33
    assert at.session_state["session_token"] == token  # not logged out
    assert "eski konuşma" not in texts(at.text)
    at.chat_input[0].set_value("yeni konuşma").run()
    assert world.backend.session_ids[-1] == new_id and world.backend.session_ids[0] == old_id
    assert [m["content"] for m in at.session_state["chat_history"]][0] == "yeni konuşma"


# ------------------------------------------------------------------ dashboard visibility
@pytest.mark.parametrize("role", DASH_ROLES)
def test_UI_09_dashboard_auto_shown_on_first_view_only_then_via_sidebar(world, role):
    """UI-09 TRANSPORT_OFFICE / MATERIAL_RESPONSIBLE: dashboard on first view after login, not on later reruns,
    reachable again through the sidebar radio ('Dashboard' option)."""
    at = logged_in(world, role)
    assert U.metrics(at), "dashboard not shown on first view"
    assert "Dashboard" in texts(at.subheader)
    radio = at.sidebar.radio(key="active_page")
    assert list(radio.options) == ["Sohbet", "Dashboard"]
    at.chat_input[0].set_value("selam").run()  # later rerun
    assert not U.metrics(at) and "Dashboard" not in texts(at.subheader)
    at.sidebar.radio(key="active_page").set_value("Dashboard").run()
    assert U.metrics(at) and "Dashboard" in texts(at.subheader)
    at.sidebar.radio(key="active_page").set_value("Sohbet").run()
    assert not U.metrics(at)


@pytest.mark.parametrize("role", DASH_ROLES)
def test_UI_10_dashboard_shown_again_after_new_login(world, role):
    """UI-10 'first view' is per login: logout + login shows the dashboard automatically again."""
    at = logged_in(world, role)
    at.chat_input[0].set_value("x").run()
    assert not U.metrics(at)
    at.button(key="logout_button").click().run()
    U.login(at, world.creds[role])
    assert U.metrics(at)


@pytest.mark.parametrize("role", NON_DASH_ROLES)
def test_UI_11_dashboard_not_automatic_for_supplier_and_admin(world, role):
    """UI-11 SUPPLIER / ADMIN: no dashboard (no metrics) on the first view."""
    at = logged_in(world, role)
    assert not U.metrics(at) and "Dashboard" not in texts(at.subheader)
    options = [list(r.options) for r in at.sidebar.radio]
    assert all("Dashboard" not in o for o in options)


def test_UI_12_supplier_has_no_sidebar_page_choice_and_admin_lands_on_admin_panel(world):
    """UI-12 SUPPLIER: chat only; ADMIN: radio [Yönetim Paneli, Sohbet] defaulting to the admin panel."""
    sup = logged_in(world, "SUPPLIER")
    assert not sup.sidebar.radio and sup.chat_input
    adm = logged_in(world, "ADMIN")
    assert list(adm.sidebar.radio(key="active_page").options) == ["Yönetim Paneli", "Sohbet"]
    assert "Yönetim Paneli" in texts(adm.header)
    assert not adm.metric
    adm.sidebar.radio(key="active_page").set_value("Sohbet").run()
    assert adm.chat_input and "Yönetim Paneli" not in texts(adm.header)


# ------------------------------------------------------------------ KPI / donut vs Excel
@pytest.mark.parametrize("role", DASH_ROLES)
def test_UI_13_kpi_metrics_equal_excel_summary_df(world, role):
    """UI-13 st.metric values equal Excel summary_df: total 46, delayed 13, completed 18, in progress 28, rate 13/46*100."""
    s = world.summary()
    assert (s["Tüm Seferler"], s["Geciken Seferler"], s["Tamamlanan Seferler"], s["Devam Eden Seferler"]) == (46, 13, 18, 28)
    at = logged_in(world, role)
    m = U.metrics(at)
    assert m["Tüm Seferler"] == "46"
    assert m["Geciken Seferler"] == "13"
    assert m["Tamamlanan Seferler"] == "18"
    assert m["Devam Eden Seferler"] == "28"
    assert m["Gecikme Oranı"] == f"{13 / 46 * 100:.1f}%"
    assert len(m) == 5


def test_UI_14_donut_figure_values_equal_excel(world):
    """UI-14 donut: labels Tamamlanan/Devam Eden, values 18/28, hole > 0; also rendered as a plotly chart."""
    from logistic_ai.dashboard.kpi import load_kpis
    from logistic_ai.ui.dashboard import _donut

    k = load_kpis(world.data_repo)
    s = world.summary()
    fig = _donut(k)
    trace = fig.data[0]
    assert trace.type == "pie"
    assert list(trace.labels) == ["Tamamlanan Seferler", "Devam Eden Seferler"]
    assert [lbl.split()[0] for lbl in trace.labels] == ["Tamamlanan", "Devam"]
    assert list(trace.values) == [18, 28] == [s["Tamamlanan Seferler"], s["Devam Eden Seferler"]]
    assert trace.hole and trace.hole > 0
    at = logged_in(world, "TRANSPORT_OFFICE")
    assert len(at.get("plotly_chart")) == 1


def test_UI_15_dashboard_hidden_without_summary_table_permission(world):
    """UI-15 dashboard role without TABLE summary_df permission: no KPI shown (permission check)."""
    from logistic_ai_shared_auth.authorization.permission_store import resource_key, role_subject

    world.perms.put(role_subject("TRANSPORT_OFFICE"), resource_key("TABLE", "summary_df"), False, "test")
    world.permission_service.invalidate() if hasattr(world.permission_service, "invalidate") else None
    at = logged_in(world, "TRANSPORT_OFFICE")
    assert not U.metrics(at)


# ------------------------------------------------------------------ admin panel
@pytest.mark.parametrize("role", ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE"))
def test_UI_16_non_admin_gets_no_panel(world, role):
    """UI-16 non-ADMIN: router offers no admin page; the panel renderer itself denies access."""
    at = logged_in(world, role)
    assert "Yönetim Paneli" not in texts(at.header)
    assert all("Yönetim Paneli" not in list(r.options) for r in at.sidebar.radio)
    direct = U.make_app(world, U.admin_panel_script, state=world.session_state_for(role))
    direct.run()
    assert "Bu sayfaya erişim yetkiniz yok." in texts(direct.warning)
    assert not direct.tabs and not direct.dataframe


def test_UI_17_admin_sees_panel_user_table_has_no_password_or_hash(world):
    """UI-17 ADMIN panel: user table columns are id/name/role/active; no password or hash anywhere in it."""
    at = logged_in(world, "ADMIN")
    assert "Yönetim Paneli" in texts(at.header)
    assert [t.label for t in at.tabs] == ["Kullanıcılar", "İzinler"]
    df = at.dataframe[0].value
    assert list(df.columns) == ["Kullanıcı ID", "Kullanıcı adı", "Rol", "Aktif"]
    flat = " ".join(map(str, df.to_numpy().ravel())) + " ".join(df.columns)
    assert "$argon2" not in flat and "hash" not in flat.lower() and "şifre" not in flat.lower()
    assert not any(U.leaks(flat, c.password) for c in world.creds.values())
    assert set(df["Rol"]) == set(ROLES)


FN, ROLE_UNDER_TEST = "get_delayed_truck", "TRANSPORT_OFFICE"


def _apply_action(at, action: str) -> None:
    """Pick the Rol subject, set FUNCTION ``FN`` to ``action`` and press 'Uygula'."""
    from logistic_ai_shared_auth.authorization.admin_service import ROLE

    at.selectbox(key="admin_subj_role").select(ROLE_UNDER_TEST).run()
    at.selectbox(key=f"admin_perm_{ROLE}_{ROLE_UNDER_TEST}_FUNCTION_{FN}").select(action)  # form widget: commit together with the submit click
    [b for b in at.button if b.label == "Uygula"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]


def test_UI_18_admin_removes_function_permission_effect_visible_then_regrants(world):
    """UI-18 ADMIN removes FUNCTION get_delayed_truck for TRANSPORT_OFFICE via the panel -> tool forbidden;
    re-grant via the panel -> allowed again. Non-admin roles cannot do this (UI-16)."""
    uid = world.creds[ROLE_UNDER_TEST].userid
    check = lambda: world.permission_service.check(uid, "FUNCTION", FN).allowed  # noqa: E731
    assert check() is True, "precondition: Excel grants the function to the role"
    at = logged_in(world, "ADMIN")
    _apply_action(at, "Kaydı kaldır")
    assert any("izin değişikliği uygulandı" in s for s in texts(at.success))
    assert check() is False  # forbidden for the transport user's tool call
    at.run()  # the table of the submit run was drawn before the change; the next run shows it
    rows = [r for r in at.dataframe if "Mevcut kayıt" in list(r.value.columns)][0].value
    assert rows[rows["Kaynak"] == FN]["Mevcut kayıt"].iloc[0] == "Kayıt yok"
    _apply_action(at, "İzin ver")
    assert check() is True
