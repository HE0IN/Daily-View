"""[개발 요청] 승격 핸드오프의 session_state 수명주기 (#1).

상세보기 / 확인요청목록의 **[개발 요청]** 버튼은 새요청등록 페이지로 항목 ID 를
session_state 로 넘긴다. 이때 session_state 안에는 수명이 다른 두 종류의 키가 섞인다.

- **위젯 키** (``new_title_<nonce>`` 등) — 해당 위젯이 렌더되지 않은 run 이 지나면
  Streamlit 이 회수한다. 즉 **페이지를 벗어나는 순간 사라진다.**
- **일반 키** (``promote_id``, prefill 완료 플래그) — 아무도 지우지 않으면
  **세션이 끝날 때까지 남는다.**

이 수명 차이를 무시하면 승격 폼이 두 가지로 깨진다.

1. "이미 채웠음" 플래그만 보고 prefill 을 건너뛰면, 등록하지 않고 나갔다가 같은
   항목으로 다시 들어왔을 때 제목·설명이 빈 채로 뜬다. 플래그는 남았는데 위젯
   값은 회수됐기 때문이다.
2. 등록하지 않고 나가도 ``promote_id`` 가 남아, 이후 메뉴에서 새 요청을 등록하면
   ``create_issue`` 대신 ``promote_unimplemented`` 를 타서 엉뚱한 원본 항목이
   승격되어 버린다.

해결은 **회수되는 쪽(위젯 키)의 존재 자체를 "폼이 새로 마운트됐는가" 신호로 쓰는
것**이다. 살아남는 플래그 대신 사라지는 쪽을 기준으로 삼으면 별도 플래그를 관리할
필요가 없고, 위 두 증상이 같은 한 가지 규칙으로 정리된다.
"""

from __future__ import annotations

from typing import MutableMapping

#: 확정된 승격 대상. 이 키가 있으면 새요청등록이 승격 모드로 동작한다.
PROMOTE_ID = "promote_id"

#: [개발 요청] 버튼이 남기는 1회용 토큰. 새요청등록이 마운트될 때 소비된다.
PROMOTE_REQUEST = "_promote_request"

State = MutableMapping[str, object]


def request_promote(state: State, item_id: str) -> None:
    """[개발 요청] 버튼용 — 새요청등록으로 넘길 1회용 승격 토큰을 남긴다.

    ``promote_id`` 를 버튼에서 직접 세팅하지 않는 이유: 직접 세팅하면 "지금 눌러서
    들어온 것" 과 "예전에 눌렀다가 등록하지 않고 나간 것" 이 session_state 상에서
    완전히 똑같아 구분할 수 없다.
    """
    state[PROMOTE_REQUEST] = item_id


def sync_promote_context(state: State, *, form_mounted: bool) -> str | None:
    """새요청등록 진입 시 이번 run 의 승격 대상을 확정해 반환한다.

    ``form_mounted`` 는 폼 위젯 키가 session_state 에 남아 있는지 — 즉 직전 run 에도
    이 페이지가 떠 있었는지다.

    - **새로 마운트됨** (``form_mounted=False``): 이전 승격 컨텍스트를 버리고, 토큰이
      있으면 그것을 채택한다. 토큰 없이 들어왔다는 건 메뉴로 새 요청을 쓰러 왔다는
      뜻이므로 승격이 아니다.
    - **이미 떠 있음** (``form_mounted=True``): 같은 페이지 안의 rerun (입력·붙여넣기
      등) 이므로 현재 컨텍스트를 그대로 유지한다.

    Returns:
        승격 대상 항목 ID. 일반 신규 등록이면 ``None``.
    """
    if not form_mounted:
        state.pop(PROMOTE_ID, None)
        token = state.pop(PROMOTE_REQUEST, None)
        if token:
            state[PROMOTE_ID] = token
    value = state.get(PROMOTE_ID)
    return value if isinstance(value, str) and value else None


def clear_promote(state: State) -> None:
    """승격 컨텍스트 폐기 — 등록 완료 후, 또는 원본 조회 실패 시."""
    state.pop(PROMOTE_ID, None)
    state.pop(PROMOTE_REQUEST, None)
