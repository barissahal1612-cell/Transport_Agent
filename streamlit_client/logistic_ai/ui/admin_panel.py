"""Admin panel (Requirements 4.1, 4.3-4.8).

Shown only to an ADMIN session. Every action goes through ``AdminService``,
which re-verifies the actor (active ADMIN) server-side on each call.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from logistic_ai_shared_auth.authorization.admin_service import (
    ROLE,
    USER,
    AdminError,
)
from logistic_ai_shared_auth.authorization.authorizer import PermissionDenied
from logistic_ai_shared_auth.authorization.resources import FUNCTION, FUNCTIONS, TABLE, TABLES
from logistic_ai_shared_auth.auth.users import ROLES

_DENIED_MSG = "Bu sayfaya erişim yetkiniz yok."
_GENERIC_MSG = "İşlem şu anda gerçekleştirilemedi. Lütfen tekrar deneyin."

_NO_CHANGE = "Değiştirme"
_ALLOW = "İzin ver"
_DENY = "Engelle"
_REMOVE = "Kaydı kaldır"
_ACTIONS = (_NO_CHANGE, _ALLOW, _DENY, _REMOVE)

_SUBJECT_LABELS = {"Rol": ROLE, "Kullanıcı": USER}


def _actor_userid(deps: Any) -> str | None:
    """Resolve the acting admin's userid defensively.

    Needs ``userid`` on ``UserContext`` or on the session view returned by
    ``SessionManager.require_valid_session()`` (task 8.1 must provide one).
    """
    try:
        ctx = deps.user_context.current()
    except Exception:
        return None
    userid = getattr(ctx, "userid", None)
    if not userid:
        try:
            userid = getattr(deps.session.require_valid_session(), "userid", None)
        except Exception:
            userid = None
    return userid if isinstance(userid, str) and userid else None


def _error_message(exc: Exception) -> str:
    if isinstance(exc, PermissionDenied):
        return _DENIED_MSG
    if isinstance(exc, AdminError):
        return str(exc) or "Geçersiz istek."
    return _GENERIC_MSG


def _is_admin(deps: Any) -> bool:
    try:
        return str(getattr(deps.user_context.current().role, "value", deps.user_context.current().role)) == "ADMIN"
    except Exception:
        return False


def _render_users(deps: Any, actor: str) -> None:
    st.subheader("Kullanıcılar")
    try:
        users = deps.admin_service.list_users(actor)
    except Exception as exc:
        st.error(_error_message(exc))
        return

    needle = st.text_input("Kullanıcı ara", key="admin_user_filter").strip().lower()
    rows = [
        u for u in users
        if not needle or needle in u.username.lower() or needle in u.role.lower()
    ]
    st.dataframe(
        [
            {
                "Kullanıcı ID": u.userid,
                "Kullanıcı adı": u.username,
                "Rol": u.role,
                "Aktif": "Evet" if u.active else "Hayır",
            }
            for u in rows
        ],
        use_container_width=True,
        hide_index=True,
    )

    if not rows:
        return
    by_label = {f"{u.username} ({u.role})": u for u in rows}
    label = st.selectbox("Kullanıcı seç", list(by_label), key="admin_user_pick")
    target = by_label[label]
    new_state = not target.active
    verb = "Aktif yap" if new_state else "Pasif yap"
    confirm = st.checkbox(
        f"'{target.username}' kullanıcısını {'aktif' if new_state else 'pasif'} yapmayı onaylıyorum",
        key=f"admin_confirm_active_{target.userid}_{new_state}",
    )
    if st.button(verb, key="admin_toggle_active", disabled=not confirm):
        try:
            deps.admin_service.set_user_active(actor, target.userid, new_state)
            st.success("Kullanıcı durumu güncellendi.")
            st.rerun()
        except Exception as exc:
            if type(exc).__name__ == "RerunException":
                raise
            st.error(_error_message(exc))


def _current_state(entries: list[Any]) -> dict[str, str]:
    return {e.resource: (_ALLOW if e.allowed else _DENY) for e in entries}


def _render_permissions(deps: Any, actor: str) -> None:
    st.subheader("İzinler")
    type_label = st.radio("Konu türü", list(_SUBJECT_LABELS), horizontal=True, key="admin_subj_type")
    subject_type = _SUBJECT_LABELS[type_label]

    if subject_type == ROLE:
        subject = st.selectbox("Rol", list(ROLES), key="admin_subj_role")
    else:
        try:
            users = deps.admin_service.list_users(actor)
        except Exception as exc:
            st.error(_error_message(exc))
            return
        if not users:
            st.info("Kullanıcı bulunamadı.")
            return
        ids = {f"{u.username} ({u.userid})": u.userid for u in users}
        subject = ids[st.selectbox("Kullanıcı", list(ids), key="admin_subj_user")]

    try:
        entries = deps.admin_service.list_permissions(actor, subject_type, subject)
    except Exception as exc:
        st.error(_error_message(exc))
        return
    state = _current_state(entries)

    st.caption("Mevcut kayıtlar: kayıt yoksa varsayılan olarak erişim yoktur; Engelle kaydı izin verenleri geçersiz kılar.")
    resources = [(TABLE, "Tablo", n) for n in TABLES] + [(FUNCTION, "Fonksiyon", n) for n in FUNCTIONS]
    st.dataframe(
        [
            {"Tür": label, "Kaynak": name, "Mevcut kayıt": state.get(f"{rtype}#{name}", "Kayıt yok")}
            for rtype, label, name in resources
        ],
        use_container_width=True,
        hide_index=True,
    )

    prefix = f"admin_perm_{subject_type}_{subject}"
    choices: list[tuple[str, str, str]] = []
    with st.form(f"{prefix}_form"):
        for rtype, label, name in resources:
            col1, col2 = st.columns([3, 2])
            col1.write(f"{label}: `{name}`")
            action = col2.selectbox(
                "İşlem", _ACTIONS, key=f"{prefix}_{rtype}_{name}", label_visibility="collapsed"
            )
            if action != _NO_CHANGE:
                choices.append((rtype, name, action))
        submitted = st.form_submit_button("Uygula")

    if not submitted:
        return
    if not choices:
        st.info("Uygulanacak değişiklik seçilmedi.")
        return
    ok = 0
    for rtype, name, action in choices:
        try:
            if action == _REMOVE:
                deps.admin_service.remove_permission(actor, subject_type, subject, rtype, name)
            else:
                deps.admin_service.set_permission(
                    actor, subject_type, subject, rtype, name, action == _ALLOW
                )
            ok += 1
        except Exception as exc:
            st.error(f"{name}: {_error_message(exc)}")
    if ok:
        st.success(f"{ok} izin değişikliği uygulandı.")


def render_admin_panel(deps: Any) -> None:
    if not _is_admin(deps):
        st.warning(_DENIED_MSG)
        return
    actor = _actor_userid(deps)
    if actor is None:
        st.error("Oturum bilgisi doğrulanamadı. Lütfen yeniden giriş yapın.")
        return
    st.header("Yönetim Paneli")
    users_tab, perms_tab = st.tabs(["Kullanıcılar", "İzinler"])
    with users_tab:
        _render_users(deps, actor)
    with perms_tab:
        _render_permissions(deps, actor)
