"""상태 전이 로직 회귀 테스트.

**전이는 자유다** (2026-08-19) — 워크플로우 14 단계 사이는 역할·순서와 무관하게
어느 쪽으로든 이동한다. 확인대기/Temp 만 kind 와 묶여 있어 예외.
디스크 I/O 는 일체 없으므로 가장 빠른 테스트 그룹.
"""

from __future__ import annotations

import pytest

from core.models import Role, Status
from core.workflow import (
    KIND_BOUND_TRANSITIONS,
    STATUS_LABELS_KO,
    URGENCY_LABELS_KO,
    WORKFLOW_STATUSES,
    WorkflowError,
    allowed_transitions,
    assert_transition,
    can_transition,
)


# ---------------------------------------------------------------------------
# 자유 전이 — 워크플로우 14 단계는 서로 오갈 수 있다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(WORKFLOW_STATUSES))
@pytest.mark.parametrize("role", [Role.developer, Role.reviewer])
def test_any_workflow_status_reaches_every_other(
    status: Status, role: Role
) -> None:
    """어느 단계에서든 자기 자신을 뺀 나머지 전 단계로 갈 수 있다 (역할 무관)."""
    actual = set(allowed_transitions(status, role))
    assert actual == set(WORKFLOW_STATUSES) - {status}


def test_allowed_transitions_ignores_role() -> None:
    """담당자/등록자 구분 없이 같은 목록. role 을 안 줘도 동작한다."""
    dev = allowed_transitions(Status.assignee_developing, Role.developer)
    rev = allowed_transitions(Status.assignee_developing, Role.reviewer)
    none_role = allowed_transitions(Status.assignee_developing)
    assert dev == rev == none_role


def test_skip_ahead_and_go_back() -> None:
    """건너뛰기(신규개발중 → 완료)와 되돌리기(완료 → 담당자확인요청) 모두 허용."""
    assert can_transition(
        Status.assignee_developing, Role.developer, Status.closed
    )
    assert can_transition(Status.closed, Role.reviewer, Status.assignee_request)
    assert can_transition(
        Status.closed, Role.developer, Status.assignee_developing
    )
    # 예외 없이 통과해야 한다
    assert_transition(Status.assignee_developing, Role.developer, Status.closed)
    assert_transition(Status.closed, Role.developer, Status.assignee_request)


def test_transition_order_follows_workflow_sequence() -> None:
    """반환 순서는 업무 흐름 순 — UI 버튼 정렬이 뒤죽박죽되지 않게."""
    opts = allowed_transitions(Status.vendor_request)
    expected = [s for s in WORKFLOW_STATUSES if s != Status.vendor_request]
    assert opts == expected


def test_same_status_is_not_a_transition() -> None:
    """자기 자신으로의 전이는 목록에 없다."""
    for status in WORKFLOW_STATUSES:
        assert status not in allowed_transitions(status)
        assert not can_transition(status, Role.developer, status)


# ---------------------------------------------------------------------------
# kind 와 묶인 상태 — 자유 전이에서 제외 (미아 항목 방지)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(WORKFLOW_STATUSES))
@pytest.mark.parametrize("target", [Status.pending_check, Status.temp])
def test_kind_bound_targets_are_blocked(status: Status, target: Status) -> None:
    """워크플로우 단계에서 확인대기/Temp 로 곧장 넘어가는 것은 막힌다.

    상태만 바꾸면 확인요청목록에도 개발목록에도 안 잡히는 미아가 되므로,
    kind 까지 바꾸는 repository 전용 함수로만 이동해야 한다.
    """
    assert not can_transition(status, Role.developer, target)
    with pytest.raises(WorkflowError):
        assert_transition(status, Role.developer, target)


def test_kind_bound_sources_keep_narrow_exit() -> None:
    """확인대기/Temp 에서 나가는 경로는 좁게 유지된다."""
    assert allowed_transitions(Status.pending_check) == [Status.assignee_request]
    assert allowed_transitions(Status.temp) == [Status.pending_check]
    assert set(KIND_BOUND_TRANSITIONS) == {Status.pending_check, Status.temp}


@pytest.mark.parametrize(
    ("current", "role", "target", "should_pass"),
    [
        # --- 자유 이동 (모두 통과) ---
        (Status.assignee_request, Role.reviewer, Status.assignee_reviewing, True),
        (Status.assignee_request, Role.developer, Status.closed, True),
        (Status.assignee_developing, Role.reviewer, Status.vendor_reply, True),
        (Status.team_reply, Role.developer, Status.assignee_request, True),
        (Status.closed, Role.developer, Status.assignee_request, True),
        (Status.closed, Role.reviewer, Status.author_reviewing, True),
        # --- kind 묶인 상태로의 직행 (차단) ---
        (Status.assignee_request, Role.developer, Status.pending_check, False),
        (Status.closed, Role.reviewer, Status.temp, False),
        (Status.pending_check, Role.developer, Status.vendor_wait, False),
        (Status.temp, Role.reviewer, Status.closed, False),
    ],
)
def test_can_transition_matches_assert_transition(
    current: Status, role: Role, target: Status, should_pass: bool
) -> None:
    """``can_transition`` 의 결과가 ``assert_transition`` 의 통과/실패와 일치."""
    assert can_transition(current, role, target) is should_pass, (
        f"can_transition({current.value}, {role.value}, {target.value}) "
        f"!= {should_pass}"
    )

    if should_pass:
        assert_transition(current, role, target)
    else:
        with pytest.raises(WorkflowError):
            assert_transition(current, role, target)


# ---------------------------------------------------------------------------
# 에러 메시지에 한글 라벨이 포함되는지
# ---------------------------------------------------------------------------


def test_workflow_error_message_includes_korean_labels() -> None:
    """차단되는 전이(확인대기 직행) 메시지에 한글 라벨 + 화살표가 들어감."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(Status.closed, Role.developer, Status.pending_check)

    msg = str(exc_info.value)
    assert "완료" in msg, f"메시지에 'closed' 한글 라벨 누락: {msg!r}"
    assert "확인대기" in msg, f"메시지에 대상 한글 라벨 누락: {msg!r}"
    assert "→" in msg, f"메시지에 '→' 없음: {msg!r}"


def test_workflow_error_hints_dedicated_button() -> None:
    """확인대기/Temp 는 전용 경로로 가야 한다는 안내가 메시지에 있다."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(Status.assignee_request, Role.reviewer, Status.temp)

    msg = str(exc_info.value)
    assert "Temp" in msg
    assert "전용" in msg, f"안내 문구 누락: {msg!r}"


# ---------------------------------------------------------------------------
# 한글 라벨 자체 검증 (UI 회귀 방지)
# ---------------------------------------------------------------------------


def test_status_labels_ko_are_complete() -> None:
    """모든 Status enum 에 대해 한글 라벨이 정의되어 있다."""
    for status in Status:
        assert status in STATUS_LABELS_KO, f"한글 라벨 누락: {status.value}"
        assert STATUS_LABELS_KO[status], f"빈 라벨: {status.value}"


def test_status_labels_ko_specific_values() -> None:
    """10 단계 라벨 검증."""
    assert STATUS_LABELS_KO[Status.assignee_request] == "담당자확인요청"
    assert STATUS_LABELS_KO[Status.assignee_reviewing] == "담당자검토중"
    assert STATUS_LABELS_KO[Status.assignee_reviewed] == "담당자검토완료"
    assert STATUS_LABELS_KO[Status.assignee_developing] == "담당자신규개발중"
    assert STATUS_LABELS_KO[Status.assignee_fixing] == "담당자코드수정중"
    assert STATUS_LABELS_KO[Status.vendor_request] == "개발사확인중"
    assert STATUS_LABELS_KO[Status.vendor_reply] == "개발사회신확인중"
    assert STATUS_LABELS_KO[Status.team_wait] == "담당팀요청대기"
    assert STATUS_LABELS_KO[Status.team_request] == "담당팀확인중"
    assert STATUS_LABELS_KO[Status.team_reply] == "담당팀회신확인중"
    assert STATUS_LABELS_KO[Status.author_request] == "등록자확인요청"
    assert STATUS_LABELS_KO[Status.author_reviewing] == "등록자검토중"
    assert STATUS_LABELS_KO[Status.closed] == "완료"
    assert STATUS_LABELS_KO[Status.pending_check] == "확인대기"


def test_urgency_labels_ko_are_complete() -> None:
    """긴급도 한글 라벨 — 4 단계 (critical/high/normal/low)."""
    assert URGENCY_LABELS_KO == {
        "critical": "긴급",
        "high": "상",
        "normal": "중",
        "low": "하",
    }


def test_allowed_transitions_returns_independent_list() -> None:
    """반환된 list 를 변형해도 내부 상태가 오염되지 않는다."""
    first = allowed_transitions(Status.assignee_reviewed, Role.developer)
    first.clear()
    second = allowed_transitions(Status.assignee_reviewed, Role.developer)
    assert second == [
        s for s in WORKFLOW_STATUSES if s != Status.assignee_reviewed
    ], "내부 WORKFLOW_STATUSES 가 외부 변형에 노출됨"

    # kind 묶인 상태의 목록도 마찬가지로 복사본이어야 한다.
    pend = allowed_transitions(Status.pending_check)
    pend.clear()
    assert allowed_transitions(Status.pending_check) == [Status.assignee_request]
