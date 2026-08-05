"""[개발 요청] 승격 핸드오프 수명주기 회귀 테스트 (#1).

`ui.promote_state` 는 순수 함수라 Streamlit 없이 dict 로 테스트할 수 있다. 다만
버그 자체가 **Streamlit 의 위젯 키 회수 동작**에서 비롯되므로, 그 동작을 아래
헬퍼로 명시적으로 재현한다.

- 페이지가 떠 있으면 위젯 키(``new_title_<nonce>``)가 session_state 에 남는다
- 페이지를 벗어나면 Streamlit 이 그 키를 회수한다 (반면 일반 키는 남는다)

`_enter_new_request_page` 는 `pages/2_새요청등록.py` 진입부와 같은 판단을 한다.
페이지 쪽 조건을 바꾸면 이 헬퍼도 같이 맞춰야 한다.
"""

from __future__ import annotations

from ui import promote_state

NONCE = 0
TITLE_KEY = f"new_title_{NONCE}"
DESC_KEY = f"new_desc_{NONCE}"


# ---------------------------------------------------------------------------
# Streamlit 위젯 수명 재현 헬퍼
# ---------------------------------------------------------------------------


def _enter_new_request_page(state: dict) -> tuple[str | None, bool]:
    """새요청등록 진입부와 동일한 판단 → (승격 대상, prefill 해야 하는가)."""
    form_mounted = TITLE_KEY in state
    promote_id = promote_state.sync_promote_context(state, form_mounted=form_mounted)
    return promote_id, bool(promote_id) and not form_mounted


def _render_form(state: dict, *, title: str = "", desc: str = "") -> None:
    """폼 위젯이 렌더된 상태 — 위젯 키가 session_state 에 자리잡는다."""
    state.setdefault(TITLE_KEY, title)
    state.setdefault(DESC_KEY, desc)


def _leave_page(state: dict) -> None:
    """페이지 이탈 — Streamlit 이 렌더되지 않은 위젯 키를 회수한다."""
    state.pop(TITLE_KEY, None)
    state.pop(DESC_KEY, None)


# ---------------------------------------------------------------------------
# 기본 흐름
# ---------------------------------------------------------------------------


def test_promote_entry_consumes_token_and_prefills() -> None:
    """[개발 요청] → 새요청등록: 토큰이 소비되고 prefill 이 지시된다."""
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")

    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id == "ITEM-A"
    assert should_prefill is True
    # 토큰은 1회용 — 소비 후 남아있으면 안 된다.
    assert promote_state.PROMOTE_REQUEST not in state


def test_rerun_on_same_page_keeps_context_without_refilling() -> None:
    """같은 페이지 rerun(입력·붙여넣기)은 컨텍스트 유지 + 재채움 없음.

    재채움이 일어나면 사용자가 편집 중이던 제목·설명이 원본으로 덮인다.
    """
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="사용자가 고친 제목")

    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id == "ITEM-A"
    assert should_prefill is False
    assert state[TITLE_KEY] == "사용자가 고친 제목"


def test_user_cleared_title_is_not_restored() -> None:
    """사용자가 제목을 직접 비워도 되살리지 않는다 (키는 남아있으므로)."""
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="원본 제목")
    state[TITLE_KEY] = ""

    _, should_prefill = _enter_new_request_page(state)

    assert should_prefill is False
    assert state[TITLE_KEY] == ""


# ---------------------------------------------------------------------------
# #1 회귀 — 등록하지 않고 나갔다 돌아오는 경우
# ---------------------------------------------------------------------------


def test_reentry_to_same_item_after_abandon_prefills_again() -> None:
    """#1 본증상: 등록 안 하고 나갔다가 같은 항목으로 재진입해도 prefill 된다.

    구버전은 `_promote_filled_{id}` 플래그가 세션에 살아남아 2회차 prefill 을
    건너뛰었고, 위젯 값은 회수된 뒤라 폼이 빈 채로 떴다.
    """
    state: dict = {}

    # 1회차 — 진입, prefill, 폼 렌더
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="원본 제목", desc="원본 설명")

    # 등록하지 않고 목록으로 이탈 → 위젯 키 회수
    _leave_page(state)

    # 2회차 — 같은 항목으로 다시 [개발 요청]
    promote_state.request_promote(state, "ITEM-A")
    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id == "ITEM-A"
    assert should_prefill is True


def test_menu_entry_after_abandon_is_not_promote() -> None:
    """#1 2차 버그: 승격을 중단한 뒤 메뉴로 들어오면 일반 신규 등록이어야 한다.

    구버전은 `promote_id` 가 남아 `create_issue` 대신 `promote_unimplemented` 를
    타서, 새 항목이 생기는 대신 예전 확인요청 항목이 승격되어 버렸다.
    """
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="원본 제목")
    _leave_page(state)

    # 토큰 없이 진입 = 좌측 메뉴로 새 요청을 쓰러 온 것
    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id is None
    assert should_prefill is False
    assert promote_state.PROMOTE_ID not in state


def test_switching_to_another_item_replaces_context() -> None:
    """A 를 열어둔 채 나가서 B 를 승격하면 대상이 B 로 바뀐다."""
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="A 제목")
    _leave_page(state)

    promote_state.request_promote(state, "ITEM-B")
    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id == "ITEM-B"
    assert should_prefill is True


# ---------------------------------------------------------------------------
# 정리 / 방어
# ---------------------------------------------------------------------------


def test_clear_promote_after_submit_ends_promote_mode() -> None:
    """등록 성공 후 정리하면 다음 진입은 일반 신규 등록이다."""
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")
    _enter_new_request_page(state)
    _render_form(state, title="원본 제목")

    promote_state.clear_promote(state)
    _leave_page(state)

    promote_id, _ = _enter_new_request_page(state)
    assert promote_id is None


def test_clear_promote_drops_unconsumed_token() -> None:
    """소비되지 않은 토큰도 함께 버린다 (조회 실패 폴백 경로)."""
    state: dict = {}
    promote_state.request_promote(state, "ITEM-A")

    promote_state.clear_promote(state)

    assert promote_state.PROMOTE_REQUEST not in state
    assert promote_state.PROMOTE_ID not in state


def test_blank_promote_id_is_treated_as_absent() -> None:
    """빈 문자열이 남아 있어도 승격 모드로 오인하지 않는다."""
    state: dict = {promote_state.PROMOTE_ID: ""}

    assert promote_state.sync_promote_context(state, form_mounted=True) is None


def test_plain_entry_without_token_is_noop() -> None:
    """승격과 무관한 진입은 아무 상태도 만들지 않는다."""
    state: dict = {}

    promote_id, should_prefill = _enter_new_request_page(state)

    assert promote_id is None
    assert should_prefill is False
    assert state == {}
