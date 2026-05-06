"""사이드바 사용자 식별 (이름 + 역할).

docs/03_ui_design.md 3.2 절 + docs/07_scenarios.md 7.1 절 참조.

쿠키 보존은 ``extra-streamlit-components`` 의 CookieManager를 사용하되,
미설치 환경에서는 ImportError를 무시하고 session_state만 사용한다 (graceful degradation).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

# 쿠키 키 / 쿠키 내부 값 키 / 변경 모드 플래그
_COOKIE_MGR_KEY = "user_cookie"
_COOKIE_VALUE_KEY = "user"
_EDIT_FLAG = "_user_edit"
_COOKIE_TTL = timedelta(days=30)


def _get_cookie_manager() -> Any | None:
    """CookieManager 인스턴스 반환. 라이브러리 미설치/오류 시 None."""
    try:
        import extra_streamlit_components as stx  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return stx.CookieManager(key=_COOKIE_MGR_KEY)
    except Exception:
        return None


def _role_label(role: str) -> str:
    return "검토자" if role == "reviewer" else "개발자"


def _render_edit_form(cookie_mgr: Any | None, current: dict | None) -> None:
    """사이드바에 이름/역할 입력 폼을 그린다."""
    with st.sidebar:
        st.subheader("사용자")
        default_name = (current or {}).get("name", "")
        default_role = (current or {}).get("role", "reviewer")
        name = st.text_input("이름", value=default_name, key="_user_name_input")
        role = st.radio(
            "역할",
            options=["reviewer", "developer"],
            format_func=_role_label,
            index=0 if default_role != "developer" else 1,
            key="_user_role_input",
        )
        col_save, col_cancel = st.columns(2)
        with col_save:
            save = st.button("저장", key="_user_save", type="primary")
        with col_cancel:
            cancel = st.button(
                "취소",
                key="_user_cancel",
                disabled=current is None,
            )

        if save and name.strip():
            user = {"name": name.strip(), "role": role}
            st.session_state["user"] = user
            if cookie_mgr is not None:
                try:
                    expires = datetime.now(timezone.utc) + _COOKIE_TTL
                    cookie_mgr.set(
                        _COOKIE_VALUE_KEY,
                        user,
                        expires_at=expires,
                        key="_user_cookie_set",
                    )
                except Exception:
                    pass  # 쿠키 실패는 무시 — session_state만 유지
            st.session_state.pop(_EDIT_FLAG, None)
            st.rerun()
        elif save and not name.strip():
            st.warning("이름을 입력해주세요.")

        if cancel and current is not None:
            st.session_state.pop(_EDIT_FLAG, None)
            st.rerun()


def get_or_init_user() -> dict | None:
    """사이드바에 사용자 위젯을 그리고 현재 user 정보를 반환.

    1. 쿠키에서 user 복원 시도
    2. session_state에 user 있으면 "현재: 김OO (검토자) [변경]" 표시
    3. 변경/미설정 시 입력 폼 노출
    """
    cookie_mgr = _get_cookie_manager()

    # 1) 쿠키 → session_state 복원
    if "user" not in st.session_state and cookie_mgr is not None:
        try:
            saved = cookie_mgr.get(_COOKIE_VALUE_KEY)
        except Exception:
            saved = None
        if isinstance(saved, dict) and saved.get("name"):
            st.session_state["user"] = {
                "name": saved.get("name"),
                "role": saved.get("role", "reviewer"),
            }

    user: dict | None = st.session_state.get("user")
    edit_mode = bool(st.session_state.get(_EDIT_FLAG, False))

    # 2) 사용자 있고 편집 모드 아니면 — 현재 표시 + 변경 버튼
    if user and not edit_mode:
        with st.sidebar:
            st.markdown(
                f"**현재**: {user.get('name', '')} ({_role_label(user.get('role', 'reviewer'))})"
            )
            if st.button("변경", key="_user_change_btn"):
                st.session_state[_EDIT_FLAG] = True
                st.rerun()
        return user

    # 3) user 없거나 편집 모드 → 폼 노출
    _render_edit_form(cookie_mgr, user)
    return st.session_state.get("user")


def require_user() -> dict:
    """페이지 상단에서 호출. user 없으면 안내 후 페이지 정지."""
    user = st.session_state.get("user")
    if not user or not user.get("name"):
        st.warning("좌측 사이드바에서 이름과 역할을 먼저 입력해주세요.")
        st.stop()
    return user  # type: ignore[return-value]


__all__ = ["get_or_init_user", "require_user"]
