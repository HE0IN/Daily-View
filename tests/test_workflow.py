"""상태 전이 로직 회귀 테스트.

docs/04_workflow.md 4.3 절의 권한 매트릭스가 ``core.workflow.TRANSITIONS`` 와
정확히 일치하는지 보장한다. 디스크 I/O 는 일체 없으므로 가장 빠른 테스트 그룹.
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
# 운영 매트릭스 — 검토중 1 단계, 검토자가 완료/추가확인필요/반려 3 갈래.
# ---------------------------------------------------------------------------
# (현재 상태, 역할) → 정렬된 next status set. 표에 없으면 빈 집합.
# - 검토중 → 완료 / 추가확인필요 / 반려 (검토자)
# - 추가확인필요·반려 → 개발중 (개발자 재착수)
# - done / reopened 은 레거시 — 새 흐름 미사용이나 옛 데이터 호환 전이만 유지.
EXPECTED_TRANSITIONS: dict[tuple[Status, Role], set[Status]] = {
    (Status.requested, Role.developer): {Status.dev_review, Status.in_progress},
    (Status.requested, Role.reviewer): {Status.closed},
    (Status.dev_review, Role.developer): {Status.in_progress, Status.modifying},
    (Status.dev_review, Role.reviewer): set(),
    (Status.in_progress, Role.developer): {
        Status.modifying,
        Status.api_check,
        Status.reviewing,
        Status.closed,
    },
    (Status.in_progress, Role.reviewer): set(),
    (Status.modifying, Role.developer): {
        Status.in_progress,
        Status.api_check,
        Status.reviewing,
        Status.closed,
    },
    (Status.modifying, Role.reviewer): set(),
    (Status.api_check, Role.developer): {
        Status.vendor_dev,
        Status.vendor_fix,
        Status.in_progress,
    },
    (Status.api_check, Role.reviewer): set(),
    (Status.vendor_dev, Role.developer): {
        Status.vendor_fix,
        Status.reviewing,
        Status.api_check,
        Status.closed,
    },
    (Status.vendor_dev, Role.reviewer): set(),
    (Status.vendor_fix, Role.developer): {
        Status.vendor_dev,
        Status.reviewing,
        Status.api_check,
        Status.closed,
    },
    (Status.vendor_fix, Role.reviewer): set(),
    (Status.reviewing, Role.developer): {Status.closed},
    (Status.reviewing, Role.reviewer): {
        Status.closed,
        Status.needs_recheck,
        Status.rejected,
    },
    (Status.needs_recheck, Role.developer): {Status.dev_review},
    (Status.needs_recheck, Role.reviewer): set(),
    (Status.rejected, Role.developer): {Status.dev_review},
    (Status.rejected, Role.reviewer): set(),
    (Status.closed, Role.developer): {Status.in_progress},
    (Status.closed, Role.reviewer): {Status.requested, Status.in_progress},
    # --- 레거시 (옛 데이터 호환) ---
    (Status.reopened, Role.developer): {Status.in_progress},
    (Status.reopened, Role.reviewer): set(),
    (Status.done, Role.developer): set(),
    (Status.done, Role.reviewer): {
        Status.reviewing,
        Status.closed,
        Status.needs_recheck,
        Status.rejected,
    },
}


# ---------------------------------------------------------------------------
# allowed_transitions: 7 × 2 = 14 조합 모두 검증
# ---------------------------------------------------------------------------


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
    """4.3 절 권한 매트릭스 모든 칸이 코드와 일치."""
    actual = set(allowed_transitions(status, role))
    assert actual == expected, (
        f"{status.value} / {role.value}: expected {expected}, got {actual}"
    )


def test_closed_can_reopen() -> None:
    """완료(closed)는 재오픈 가능 — 검토자는 요청/개발, 개발자는 개발로."""
    assert set(allowed_transitions(Status.closed, Role.reviewer)) == {
        Status.requested,
        Status.in_progress,
    }
    assert set(allowed_transitions(Status.closed, Role.developer)) == {
        Status.in_progress,
    }


# ---------------------------------------------------------------------------
# can_transition vs assert_transition 일관성
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "role", "target", "should_pass"),
    [
        # --- 정상 전이 (11단계 흐름) ---
        (Status.requested, Role.developer, Status.dev_review, True),
        (Status.dev_review, Role.developer, Status.in_progress, True),
        (Status.dev_review, Role.developer, Status.modifying, True),
        (Status.in_progress, Role.developer, Status.modifying, True),
        (Status.in_progress, Role.developer, Status.api_check, True),
        (Status.in_progress, Role.developer, Status.reviewing, True),
        (Status.modifying, Role.developer, Status.reviewing, True),
        (Status.api_check, Role.developer, Status.vendor_dev, True),
        (Status.api_check, Role.developer, Status.vendor_fix, True),
        (Status.api_check, Role.developer, Status.in_progress, True),
        (Status.vendor_dev, Role.developer, Status.reviewing, True),
        (Status.vendor_dev, Role.developer, Status.closed, True),
        (Status.vendor_fix, Role.developer, Status.api_check, True),
        (Status.vendor_fix, Role.developer, Status.vendor_dev, True),
        (Status.reviewing, Role.reviewer, Status.closed, True),
        (Status.reviewing, Role.reviewer, Status.needs_recheck, True),
        (Status.reviewing, Role.reviewer, Status.rejected, True),
        (Status.needs_recheck, Role.developer, Status.dev_review, True),
        (Status.rejected, Role.developer, Status.dev_review, True),
        # 개발자도 closed 가능 (두 명 환경)
        (Status.in_progress, Role.developer, Status.closed, True),
        (Status.reviewing, Role.developer, Status.closed, True),
        # 완료 재오픈
        (Status.closed, Role.reviewer, Status.requested, True),
        (Status.closed, Role.reviewer, Status.in_progress, True),
        (Status.closed, Role.developer, Status.in_progress, True),
        # 레거시
        (Status.reopened, Role.developer, Status.in_progress, True),
        (Status.done, Role.reviewer, Status.closed, True),
        # --- 위반 / 흐름 점프 ---
        (Status.requested, Role.reviewer, Status.dev_review, False),
        (Status.dev_review, Role.reviewer, Status.in_progress, False),
        (Status.api_check, Role.developer, Status.reviewing, False),  # vendor 거침
        (Status.needs_recheck, Role.developer, Status.in_progress, False),  # dev_review 거침
        (Status.needs_recheck, Role.reviewer, Status.dev_review, False),
        (Status.reviewing, Role.reviewer, Status.reopened, False),
        (Status.closed, Role.developer, Status.reopened, False),
        (Status.in_progress, Role.developer, Status.done, False),
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
        # 정상 전이는 예외 없이 통과해야
        assert_transition(current, role, target)
    else:
        with pytest.raises(WorkflowError):
            assert_transition(current, role, target)


# ---------------------------------------------------------------------------
# 에러 메시지에 한글 라벨이 포함되는지
# ---------------------------------------------------------------------------


def test_workflow_error_message_includes_korean_labels() -> None:
    """closed → reopened 시도 시 메시지에 '완료' 와 '재요청' 한글 라벨이 들어감."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(Status.closed, Role.developer, Status.reopened)

    msg = str(exc_info.value)
    assert "완료" in msg, f"메시지에 'closed' 한글 라벨 누락: {msg!r}"
    assert "재요청" in msg, f"메시지에 'reopened' 한글 라벨 누락: {msg!r}"
    # 화살표 형식
    assert "→" in msg, f"메시지에 '→' 없음: {msg!r}"


def test_workflow_error_for_reviewer_to_in_progress() -> None:
    """검토자가 작업중으로 바꾸려 하면 명확한 에러 발생."""
    with pytest.raises(WorkflowError) as exc_info:
        assert_transition(Status.requested, Role.reviewer, Status.in_progress)

    msg = str(exc_info.value)
    assert "요청중" in msg
    assert "개발중" in msg
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
    """주요 라벨 — 단순화 후 (요청중/작업중/완료 등으로 변경)."""
    assert STATUS_LABELS_KO[Status.requested] == "요청중"
    assert STATUS_LABELS_KO[Status.dev_review] == "개발 검토"
    assert STATUS_LABELS_KO[Status.in_progress] == "개발중"
    assert STATUS_LABELS_KO[Status.modifying] == "수정중"
    assert STATUS_LABELS_KO[Status.api_check] == "개발사 확인중"
    assert STATUS_LABELS_KO[Status.vendor_dev] == "개발사 개발 중"
    assert STATUS_LABELS_KO[Status.vendor_fix] == "개발사 수정 중"
    assert STATUS_LABELS_KO[Status.reviewing] == "검토중"
    assert STATUS_LABELS_KO[Status.needs_recheck] == "추가확인필요"
    assert STATUS_LABELS_KO[Status.rejected] == "반려"
    assert STATUS_LABELS_KO[Status.closed] == "완료"
    # 레거시
    assert STATUS_LABELS_KO[Status.done] == "작업완료"
    assert STATUS_LABELS_KO[Status.reopened] == "재요청"


def test_urgency_labels_ko_are_complete() -> None:
    """긴급도 한글 라벨이 정의되어 있다 — 4 단계 (critical/high/normal/low)."""
    assert URGENCY_LABELS_KO == {
        "critical": "긴급",
        "high": "상",
        "normal": "중",
        "low": "하",
    }


# ---------------------------------------------------------------------------
# allowed_transitions 가 매번 새 list 를 반환 (외부 변경 격리)
# ---------------------------------------------------------------------------


def test_allowed_transitions_returns_independent_list() -> None:
    """반환된 list 를 변형해도 내부 상태가 오염되지 않는다."""
    first = allowed_transitions(Status.in_progress, Role.developer)
    first.clear()  # 호출자가 변형
    second = allowed_transitions(Status.in_progress, Role.developer)
    assert second == [
        Status.modifying,
        Status.api_check,
        Status.reviewing,
        Status.closed,
    ], "내부 TRANSITIONS 가 외부 변형에 노출됨"
