"""사이드바 사용자 식별 (이름 + 역할).

docs/03_ui_design.md 3.2 절 + docs/07_scenarios.md 7.1 절 참조.

쿠키 보존은 ``extra-streamlit-components`` 의 CookieManager를 사용하되,
미설치 환경에서는 ImportError를 무시하고 session_state만 사용한다 (graceful degradation).
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

# 쿠키 키 / 쿠키 내부 값 키 / 변경 모드 플래그
_COOKIE_MGR_KEY = "user_cookie"
_COOKIE_VALUE_KEY = "user"
_EDIT_FLAG = "_user_edit"
_COOKIE_TTL = timedelta(days=30)
# 비동기 쿠키 읽기 재시도 카운터 — 1 tick rerun 가드
_COOKIE_INIT_TICK = "_cookie_init_tick"
_COOKIE_INIT_MAX = 2  # 최대 2회 rerun 후엔 폼 노출 (무한 루프 방지)
_COOKIE_MGR_CACHE = "_user_cookie_mgr"

# URL query parameter 키 — 쿠키가 동작 안 하는 환경 (HTTP+IP / samesite /
# 라이브러리 미설치 등) 에서도 새로고침 후 user 복원이 가능하도록 fallback.
_QP_NAME = "u"
_QP_ROLE = "r"


def _restore_user_from_query_params() -> dict | None:
    """URL query parameter (?u=...&r=...) 에서 user 복원. 없거나 잘못되면 None."""
    try:
        qp_name = st.query_params.get(_QP_NAME)
        qp_role = st.query_params.get(_QP_ROLE)
    except Exception:
        return None
    if isinstance(qp_name, list):
        qp_name = qp_name[0] if qp_name else None
    if isinstance(qp_role, list):
        qp_role = qp_role[0] if qp_role else None
    if not qp_name:
        return None
    role = qp_role if qp_role in ("reviewer", "developer") else "reviewer"
    return {"name": str(qp_name).strip(), "role": role}


def _persist_user_to_query_params(user: dict) -> None:
    """user 정보를 URL query parameter 에 set — 새로고침 후에도 보존."""
    try:
        st.query_params[_QP_NAME] = user.get("name", "")
        st.query_params[_QP_ROLE] = user.get("role", "reviewer")
    except Exception:
        pass  # query_params 미지원 streamlit 버전 graceful


def _clear_user_from_query_params() -> None:
    """user 변경/삭제 시 query parameter 도 정리."""
    try:
        if _QP_NAME in st.query_params:
            del st.query_params[_QP_NAME]
        if _QP_ROLE in st.query_params:
            del st.query_params[_QP_ROLE]
    except Exception:
        pass


def _get_cookie_manager() -> Any | None:
    """CookieManager 인스턴스 반환. 라이브러리 미설치/오류 시 None.

    한 페이지 라이프사이클 안에서 같은 key 로 여러 번 만들면 컴포넌트가
    재마운트되며 비동기 쿠키 읽기 상태가 매번 리셋된다. session_state 에
    캐시해 처음 한 번만 만든다.
    """
    cached = st.session_state.get(_COOKIE_MGR_CACHE)
    if cached is not None:
        return cached
    try:
        import extra_streamlit_components as stx  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        mgr = stx.CookieManager(key=_COOKIE_MGR_KEY)
    except Exception:
        return None
    st.session_state[_COOKIE_MGR_CACHE] = mgr
    return mgr


def _role_label(role: str) -> str:
    return "검토자" if role == "reviewer" else "개발자"


def _commit_user(user: dict, cookie_mgr: Any | None) -> None:
    """선택/등록한 user 를 확정 — session_state + 접속로그 + 영속화 후 rerun."""
    st.session_state["user"] = user
    # 접속 로그 (식별/로그인 시점 1회 기록) — 파일로만 적재
    try:
        from core import logger as _logger
        _logger.audit_log(
            user["name"], _logger.ACCESS, None, {"role": user["role"]}
        )
    except Exception:
        pass
    # 영속화 — query parameter(의존성 0) + Cookie(가능 시 30일)
    _persist_user_to_query_params(user)
    if cookie_mgr is not None:
        try:
            expires = datetime.now(timezone.utc) + _COOKIE_TTL
            cookie_mgr.set(
                _COOKIE_VALUE_KEY, user, expires_at=expires, key="_user_cookie_set"
            )
        except Exception:
            pass  # 쿠키 실패는 무시 — query param 으로 새로고침 보존
    st.session_state.pop(_EDIT_FLAG, None)
    st.rerun()


def _render_edit_form(cookie_mgr: Any | None, current: dict | None) -> None:
    """사이드바에 사용자 선택(radio) + 새 사용자 등록 UI 를 그린다.

    한 번 등록(이름+역할)된 사용자는 radio 로 골라 바로 로그인한다.
    """
    from core import user_registry

    with st.sidebar:
        st.subheader("사용자")
        users = user_registry.list_users()

        # 1) 등록된 사용자 — radio 로 선택
        if users:
            names = [u["name"] for u in users]
            role_map = {u["name"]: u["role"] for u in users}
            cur_name = (current or {}).get("name")
            default_idx = names.index(cur_name) if cur_name in names else 0
            picked = st.radio(
                "사용자 선택",
                options=names,
                index=default_idx,
                format_func=lambda n: f"{n} ({_role_label(role_map.get(n, 'reviewer'))})",
                key="_user_pick",
            )
            if st.button("선택", key="_user_pick_btn", type="primary"):
                _commit_user(
                    {"name": picked, "role": role_map.get(picked, "reviewer")},
                    cookie_mgr,
                )

        # 2) 새 사용자 등록 (처음이면 펼친 상태)
        with st.expander("+ 새 사용자 등록", expanded=not users):
            new_name = st.text_input("이름", key="_user_new_name")
            new_role = st.radio(
                "역할",
                options=["reviewer", "developer"],
                format_func=_role_label,
                key="_user_new_role",
            )
            if st.button("등록", key="_user_new_btn"):
                if new_name.strip():
                    user_registry.add_user(new_name.strip(), new_role)
                    _commit_user(
                        {"name": new_name.strip(), "role": new_role}, cookie_mgr
                    )
                else:
                    st.warning("이름을 입력해주세요.")

        # 3) 취소 (이미 로그인된 상태에서 '변경' 으로 들어온 경우만)
        if current is not None:
            if st.button("취소", key="_user_cancel"):
                st.session_state.pop(_EDIT_FLAG, None)
                st.rerun()


def get_or_init_user() -> dict | None:
    """사이드바에 사용자 위젯을 그리고 현재 user 정보를 반환.

    복원 우선순위:
      1) ``st.session_state["user"]`` — 같은 세션 내에서는 그대로
      2) URL query parameter (?u=...&r=...) — 새로고침 후에도 즉시 복원,
         의존성 0, HTTP+IP 환경에서도 확실히 동작
      3) Cookie (extra-streamlit-components) — 가능하면 30 일 보존
      4) 모두 실패 시 입력 폼 노출
    """
    cookie_mgr = _get_cookie_manager()

    # 1) URL query parameter 에서 우선 복원 — 의존성 / 비동기 이슈 없음.
    if "user" not in st.session_state:
        qp_user = _restore_user_from_query_params()
        if qp_user and qp_user.get("name"):
            st.session_state["user"] = qp_user

    # 2) cookie → session_state 복원 (1) 에서 못 찾았을 때만)
    #
    # extra-streamlit-components 의 CookieManager 는 컴포넌트 첫 렌더에서
    # 비동기로 쿠키를 가져오므로, 첫 호출의 .get() 은 None 일 수 있다.
    # 1~2회 짧게 rerun 해서 쿠키 도착을 기다린 후, 그래도 없으면 입력 폼.
    if "user" not in st.session_state and cookie_mgr is not None:
        saved: Any = None
        try:
            # get_all() 이 있으면 한 번에 읽어 1 tick 안에 도착 확률 ↑
            if hasattr(cookie_mgr, "get_all"):
                all_cookies = cookie_mgr.get_all() or {}
                saved = all_cookies.get(_COOKIE_VALUE_KEY)
            else:
                saved = cookie_mgr.get(_COOKIE_VALUE_KEY)
        except Exception:
            saved = None

        # 라이브러리가 dict 를 JSON 문자열로 보관할 수 있어 string 도 처리
        if isinstance(saved, str):
            try:
                import json
                saved = json.loads(saved)
            except Exception:
                saved = None

        if isinstance(saved, dict) and saved.get("name"):
            st.session_state["user"] = {
                "name": saved.get("name"),
                "role": saved.get("role", "reviewer"),
            }
            st.session_state.pop(_COOKIE_INIT_TICK, None)
            # 쿠키에서 복원했으면 query param 도 동기화 — 이후 새로고침에서
            # 비동기 이슈 없이 즉시 복원되도록.
            _persist_user_to_query_params(st.session_state["user"])
        else:
            # 쿠키가 아직 도착 안 했을 가능성 — 1~2 tick rerun 가드
            tick = int(st.session_state.get(_COOKIE_INIT_TICK, 0))
            if tick < _COOKIE_INIT_MAX:
                st.session_state[_COOKIE_INIT_TICK] = tick + 1
                st.rerun()
            # 한도 초과 → 폼 노출 진행

    # session_state 에 user 가 있는데 query param 에 없으면 동기화 — 이전 세션
    # 에서 cookie 로 복원된 user 가 새로고침 시 즉시 잡히도록.
    if "user" in st.session_state and not _restore_user_from_query_params():
        _persist_user_to_query_params(st.session_state["user"])

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


# ---------------------------------------------------------------------------
# 프로젝트 선택 사이드바 위젯
# ---------------------------------------------------------------------------

# session_state 키 — 다른 페이지 / 모듈에서 참조할 수 있도록 상수화
_PROJECT_KEY = "_current_project"
_LAST_USER_KEY = "_proj_last_user"


def render_project_selector(user_name: str | None = None) -> str | None:
    """사이드바에 현재 프로젝트 선택 위젯을 렌더하고 선택값을 반환.

    Parameters
    ----------
    user_name : str | None
        현재 사용자 이름. 지정 시 사용자가 *참여한 프로젝트* (author 또는
        assignee 였던 항목들의 unique project) 만 옵션으로 노출.
        None 이면 모든 프로젝트.

    동작
    ----
    - ``session_state["_current_project"]`` 에 선택값을 저장.
    - 옵션: ``["(전체 프로젝트)"] + 사용자 참여 프로젝트 + ["(새 프로젝트 추가)"]``
    - "(새 프로젝트 추가)" 선택 시 텍스트 입력 + [추가] 버튼 — 추가하면
      그 프로젝트가 즉시 현재 컨텍스트로 선택됨 (다음 새 등록 시점에 자동 적용).
    - 사용자가 바뀌면 (``_proj_last_user`` 비교) 이전 사용자의 프로젝트 선택을
      reset 해 다른 사용자의 프로젝트가 선택된 채 남는 사고 방지.
    - 반환값: 현재 선택 프로젝트 이름(str) 또는 None ("(전체 프로젝트)" 시).
    """
    # 지연 임포트 — 사이클 방지 + 테스트 환경 안전.
    from core import repository, user_projects as up_mod

    # 사용자 변경 감지 — 다른 사람으로 바뀌면 그 사람의 "마지막 등록 프로젝트"
    # 를 기본으로 새로 채운다 (프로젝트 풀은 글로벌이지만 default 는 사용자별).
    if user_name is not None:
        last_user = st.session_state.get(_LAST_USER_KEY)
        if last_user != user_name:
            st.session_state[_LAST_USER_KEY] = user_name
            # 사용자 바뀌었으니 이전 컨텍스트 무효화 → 아래에서 새로 채움
            st.session_state.pop(_PROJECT_KEY, None)
            # widget key 도 갱신 (옛 사용자가 selectbox 에 set 한 값 무효화).
            st.session_state["_proj_nonce"] = (
                int(st.session_state.get("_proj_nonce", 0)) + 1
            )

    # widget key 동적 nonce — 추가/삭제/사용자 변경 시 nonce 증가시켜 selectbox
    # 를 "첫 init" 상태로 다시 생성. 그래야 _proj_select 직접 수정 없이
    # default index 로 새 선택을 강제할 수 있다 (Streamlit 위젯 key 는
    # 인스턴스화 후 직접 변경 불가).
    proj_nonce: int = int(st.session_state.setdefault("_proj_nonce", 0))
    proj_select_key = f"_proj_select_{proj_nonce}"
    proj_input_key = f"_proj_new_name_{proj_nonce}"

    with st.sidebar:
        st.divider()
        st.markdown("**프로젝트**")

        try:
            projects = repository.list_projects()
        except Exception:  # noqa: BLE001 - 인덱스 손상 등은 빈 리스트로 격하
            projects = []

        ALL = "(전체 프로젝트)"
        NEW = "(새 프로젝트 추가)"
        options = [ALL] + projects + [NEW]

        current = st.session_state.get(_PROJECT_KEY)
        # 사용자 첫 진입 또는 사용자 바뀐 직후 → 그 사람의 마지막 등록 프로젝트
        # 를 기본으로. 이미 명시적으로 선택된 값(_current_project) 이 있으면 그대로.
        if not current and user_name:
            try:
                last_proj = repository.last_project_for_user(user_name)
            except Exception:  # noqa: BLE001
                last_proj = None
            if last_proj and last_proj in projects:
                current = last_proj
                st.session_state[_PROJECT_KEY] = last_proj
                # selectbox key 는 nonce 기반이라 직접 수정 X — index= 로 default 결정.

        # 현재 저장된 프로젝트가 옵션에 없으면 ALL(0) 로 fallback.
        default_idx = (
            options.index(current) if current and current in options else 0
        )

        pick = st.selectbox(
            "현재",
            options=options,
            index=default_idx,
            key=proj_select_key,
            label_visibility="collapsed",
        )

        if pick == NEW:
            new_name = st.text_input(
                "새 프로젝트 이름",
                key=proj_input_key,
                placeholder="예: Daily View 앱",
            )
            if st.button("추가", key=f"_proj_add_{proj_nonce}"):
                cleaned = (new_name or "").strip()
                if cleaned and user_name:
                    # 1) 사용자별 프로젝트 파일에 영속화 — 항목 0 건이라도 옵션에 노출
                    try:
                        up_mod.add_user_project(user_name, cleaned)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"프로젝트 저장 실패: {exc}")
                        return None
                    # 2) 현재 컨텍스트로 설정 — _PROJECT_KEY 만 set (selectbox 의
                    #    widget key 는 위젯 인스턴스화 후라 직접 수정 X).
                    st.session_state[_PROJECT_KEY] = cleaned
                    # 3) nonce 증가 → 다음 rerun 에 selectbox/text_input 이
                    #    새 key 로 첫 init → default_idx 가 cleaned 를 가리킴.
                    st.session_state["_proj_nonce"] = proj_nonce + 1
                    st.toast(f"프로젝트 '{cleaned}' 추가됨", icon="📁")
                    st.rerun()
                elif not cleaned:
                    st.warning("프로젝트 이름을 입력해주세요.")
                elif not user_name:
                    st.warning("먼저 사용자 이름을 입력해주세요.")
            # 추가 버튼을 누르기 전엔 필터 미적용
            return None

        # 빈 프로젝트 목록 + 첫 사용자 — 안내
        if not projects:
            st.caption(
                "참여한 프로젝트가 없습니다. \"(새 프로젝트 추가)\" 로 등록하세요."
            )

        # ALL 또는 기존 프로젝트
        selected = None if pick == ALL else pick
        st.session_state[_PROJECT_KEY] = selected

        # ── 글로벌 삭제 영역 — 특정 프로젝트 선택 시에만 표시 ─────────────
        if selected:
            try:
                item_count = repository.count_project_items(selected)
            except Exception:  # noqa: BLE001
                item_count = -1  # 알 수 없음 → 삭제 차단

            confirm_key = f"_proj_confirm_delete_{selected}"
            if st.session_state.get(confirm_key):
                # 2단계: 확인 / 취소
                st.warning(
                    f"'{selected}' 를 모든 사용자에게서 제거합니다. 계속할까요?"
                )
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("확인", key=f"_proj_del_yes_{selected}", type="primary"):
                        try:
                            up_mod.remove_project_globally(selected)
                            st.session_state.pop(_PROJECT_KEY, None)
                            # selectbox widget key 직접 수정 X — nonce 증가로
                            # 다음 rerun 에서 ALL(default_idx=0) 로 자연스럽게 fallback.
                            st.session_state["_proj_nonce"] = proj_nonce + 1
                            st.session_state.pop(confirm_key, None)
                            st.toast(f"'{selected}' 제거됨", icon="🗑")
                            st.rerun()
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"제거 실패: {exc}")
                with cc2:
                    if st.button("취소", key=f"_proj_del_no_{selected}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
            else:
                # 1단계: 트리거 버튼
                if item_count > 0:
                    st.caption(
                        f"이 프로젝트에 활성 요청 {item_count} 건이 있어 삭제할 수 없습니다. "
                        f"먼저 모두 [🗑 삭제(보관)] 처리하세요."
                    )
                else:
                    if st.button(
                        f"🗑 '{selected}' 삭제",
                        key=f"_proj_del_btn_{selected}",
                        help="프로젝트 목록에서 제거 (모든 사용자에게 적용). 항목 0 건일 때만 가능.",
                    ):
                        st.session_state[confirm_key] = True
                        st.rerun()

        # ── 프로젝트별 설정 expander — API 담당자 + 카테고리 관리 ────────
        if selected:
            # 지연 import — 백엔드 모듈 로드 사이클 / 부재 환경 안전.
            from core import project_settings as ps_mod

            with st.expander(f"⚙ '{selected}' 설정", expanded=False):
                # === 카테고리 관리 ===
                st.markdown("**카테고리**")
                st.caption(
                    "프로젝트별 카테고리 풀. 새 요청 등록 시 selectbox 옵션으로 노출. "
                    "각 항목 옆 **[×]** 로 삭제, 입력칸 + **[추가]** 로 신규 등록. "
                    "기존 항목들의 카테고리는 자동으로 1회 import 됩니다."
                )

                try:
                    # list_project_categories() 가 첫 호출 시 인덱스에서 자동 import
                    cats = ps_mod.list_project_categories(selected)
                except Exception:
                    cats = {"l1": [], "l2": [], "l3": []}

                for level, label in [
                    ("l1", "대분류"),
                    ("l2", "중분류"),
                    ("l3", "소분류"),
                ]:
                    st.markdown(f"_{label}_")
                    existing = cats.get(level, [])
                    if existing:
                        # 기존 목록 + 각 옆에 [×] 삭제 버튼
                        for cat_name in existing:
                            cc1, cc2 = st.columns([4, 1])
                            with cc1:
                                st.markdown(f"· {html.escape(cat_name)}")
                            with cc2:
                                if st.button(
                                    "×",
                                    key=f"_cat_del_{selected}_{level}_{cat_name}",
                                ):
                                    try:
                                        ps_mod.remove_project_category(
                                            selected, **{level: cat_name}
                                        )
                                        st.toast(
                                            f"'{cat_name}' 제거됨", icon="🗑"
                                        )
                                        st.rerun()
                                    except Exception as exc:  # noqa: BLE001
                                        st.error(f"제거 실패: {exc}")
                    else:
                        st.caption("(없음)")
                    # 추가 입력
                    new_cat = st.text_input(
                        f"{label} 추가",
                        key=f"_cat_add_input_{selected}_{level}",
                        placeholder=f"새 {label} 이름",
                        label_visibility="collapsed",
                    )
                    if st.button(
                        f"{label} 추가",
                        key=f"_cat_add_btn_{selected}_{level}",
                    ):
                        cleaned = (new_cat or "").strip()
                        if cleaned:
                            try:
                                ps_mod.add_project_category(
                                    selected, **{level: cleaned}
                                )
                                st.toast(f"'{cleaned}' 추가됨", icon="✅")
                                st.rerun()
                            except Exception as exc:  # noqa: BLE001
                                st.error(f"추가 실패: {exc}")
                        else:
                            st.warning("이름을 입력하세요.")

        return selected


__all__ = ["get_or_init_user", "require_user", "render_project_selector"]
