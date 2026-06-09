"""상태 전이 로직 회귀 테스트 (등록자/담당자 워크플로, 10 단계).

권한: ``Role.developer`` = 담당자(assignee), ``Role.reviewer`` = 등록자(author).
디스크 I/O 는 일체 없으므로 가장 빠른 테스트 그룹.
"""

from __future__ import annotations

import pytest

from core.models import Role, Status
from core.workflow import (
    STATUS_LABELS_KO,
    URGENCY_LABELS_KO,
    WorkflowError,
    allowed_transitions,
    assert_transition,
    can_transition,
)


# ---------------------------------------------------------------------------
# 권한 매트릭스 — (상태, 역할) → 허용 next set. 표에 없으면 빈 집합.
#   developer=담당자, reviewer=등록자.
# ---------------------------------------------------------------------------
EXPECTED_TRANSITIONS: dict[tuple[Status, Role], set[Status]] = {
    (Status.assignee_request, Role.developer): {Status.assignee_reviewing},
    (Status.assignee_request, Role.reviewer): set(),
    (Status.assignee_reviewing, Role.developer): {
        Status.assignee_reviewed,
        Status.assignee_request,
    },
    (Status.assignee_reviewing, Role.reviewer): set(),
    (Status.assignee_reviewed, Role.developer): {
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_request,
        Status.assignee_reviewing,
    },
    (Status.assignee_reviewed, Role.reviewer): set(),
    (Status.vendor_request, Role.developer): {
        Status.vendor_reply,
        Status.assignee_reviewed,
    },
    (Status.vendor_request, Role.reviewer): set(),
    (Status.vendor_reply, Role.developer): {
        Status.author_request,
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_request,
    },
    (Status.vendor_reply, Role.reviewer): set(),
    (Status.assignee_developing, Role.developer): {
        Status.author_request,
        Status.assignee_reviewed,
    },
    (Status.assignee_developing, Role.reviewer): set(),
    (Status.assignee_fixing, Role.developer): {
        Status.author_request,
        Status.assignee_reviewed,
    },
    (Status.assignee_fixing, Role.reviewer): set(),
    (Status.author_request, Role.reviewer): {Status.author_reviewing},
    (Status.author_request, Role.developer): {Status.assignee_reviewed},
    (Status.author_reviewing, Role.reviewer): {
        Status.closed,
        Status.assignee_request,
        Status.author_request,
    },
    (Status.author_reviewing, Role.developer): set(),
    (Status.closed, Role.developer): set(),
    (Status.closed, Role.reviewer): {Status.author_reviewing},
}


@pytest.mark.parametrize(
    ("status", "role", "expected"),
    [
        (status, role, expected)
        for (status, role), expected in EXPECTED_TRANSITIONS.items()
    ],
)
def test_allowed_transitions_matches_spec(
    status: Status, role: Role, expected: set[Status]
) -> None:
    """권한 매트릭스 모든 칸이 코드와 일치."""
    actual = set(allowed_transitions(status, role))
    assert actual == expected, (
        f"{status.value} / {role.value}: expected {expected}, got {actual}"
    )


def test_closed_can_reopen_to_review() -> None:
    """완료(closed)는 등록자가 '등록자검토중'으로 되돌릴 수 있다 (재개발)."""
    assert set(allowed_transitions(Status.closed, Role.reviewer)) == {
        Status.author_reviewing
    }
    assert allowed_transitions(Status.closed, Role.developer) == []


# ---------------------------------------------------------------------------
# can_transition vs assert_transition 일관성
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "role", "target", "should_pass"),
    [
        # --- 정상 전이 (담당자) ---
        (Status.assignee_request, Role.developer, Status.assignee_reviewing, True),
        (Status.assignee_reviewing, Role.developer, Status.assignee_reviewed, True),
        (Status.assignee_reviewed, Role.developer, Status.assignee_developing, True),
        (Status.assignee_reviewed, Role.developer, Status.assignee_fixing, True),
        (Status.assignee_reviewed, Role.developer, Status.vendor_request, True),
        (Status.vendor_request, Role.developer, Status.vendor_reply, True),
        (Status.vendor_reply, Role.developer, Status.author_request, True),
        (Status.vendor_reply, Role.developer, Status.assignee_developing, True),
        (Status.vendor_reply, Role.developer, Status.assignee_fixing, True),
        (Status.assignee_developing, Role.developer, Status.author_request, True),
        (Status.assignee_fixing, Role.developer, Status.author_request, True),
        # --- 정상 전이 (등록자) ---
        (Status.author_request, Role.reviewer, Status.author_reviewing, True),
        (Status.author_reviewing, Role.reviewer, Status.closed, True),
        (Status.author_reviewing, Role.reviewer, Status.assignee_request, True),  # 반려
        # --- 위반: 권한 (담당자 단계를 등록자가 / 그 반대) ---
        (Status.assignee_request, Role.reviewer, Status.assignee_reviewing, False),
        (Status.assignee_reviewed, Role.reviewer, Status.assignee_developing, False),
        (Status.author_request, Role.developer, Status.author_reviewing, False),
        (Status.author_reviewing, Role.developer, Status.closed, False),
        # --- 위반: 흐름 점프 ---
        (Status.assignee_request, Role.developer, Status.assignee_reviewed, False),
        (Status.assignee_reviewing, Role.developer, Status.author_request, False),
        (Status.vendor_request, Role.developer, Status.author_request, False),
        # --- 되돌리기(직전 단계로) ---
        (Status.assignee_reviewing, Role.developer, Status.assignee_request, True),
        (Status.assignee_reviewed, Role.developer, Status.assignee_reviewing, True),
        (Status.vendor_reply, Role.developer, Status.vendor_request, True),
        (Status.author_reviewing, Role.reviewer, Status.author_request, True),
        # --- 완료 → 등록자검토중 (재개발) ---
        (Status.closed, Role.reviewer, Status.author_reviewing, True),
        # --- terminal/위반 ---
        (Status.closed, Role.developer, Status.assignee_request, False),
        (Status.closed, Role.reviewer, Status.assignee_request, False),
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
    """완료(terminal)에서 전이 시도 시 메시지에 한글 라벨 + 화살표가 들어감."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(Status.closed, Role.developer, Status.assignee_request)

    msg = str(exc_info.value)
    assert "완료" in msg, f"메시지에 'closed' 한글 라벨 누락: {msg!r}"
    assert "담당자확인요청" in msg, f"메시지에 대상 한글 라벨 누락: {msg!r}"
    assert "→" in msg, f"메시지에 '→' 없음: {msg!r}"


def test_workflow_error_wrong_position() -> None:
    """등록자(reviewer)가 담당자 전이를 시도하면 명확한 에러."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(
            Status.assignee_request, Role.reviewer, Status.assignee_reviewing
        )

    msg = str(exc_info.value)
    assert "담당자확인요청" in msg
    assert "담당자검토중" in msg
    assert "reviewer" in msg, f"메시지에 역할 'reviewer' 누락: {msg!r}"


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
    assert STATUS_LABELS_KO[Status.author_request] == "등록자확인요청"
    assert STATUS_LABELS_KO[Status.author_reviewing] == "등록자검토중"
    assert STATUS_LABELS_KO[Status.closed] == "완료"


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
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_request,
        Status.assignee_reviewing,
    ], "내부 TRANSITIONS 가 외부 변형에 노출됨"
