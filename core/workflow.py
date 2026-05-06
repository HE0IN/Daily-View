"""상태 전이 규칙과 권한 체크.

docs/04_workflow.md 4.3 절의 권한 매트릭스를 코드로 옮겨 단일 진실 출처로 둔다.
UI는 :func:`allowed_transitions` 결과만 렌더해야 하며, 서버측 변경 직전에는
:func:`assert_transition` 으로 한 번 더 가드한다.
"""

from __future__ import annotations

from .models import Role, Status


class WorkflowError(Exception):
    """워크플로우 규칙 위반(허용되지 않은 상태 전이 등) 시 발생."""


# 4.3 절 권한 매트릭스 — (현재 상태, 역할) → 허용되는 다음 상태들
TRANSITIONS: dict[tuple[Status, Role], list[Status]] = {
    (Status.requested, Role.developer): [Status.in_progress],
    (Status.requested, Role.reviewer): [Status.closed],
    (Status.in_progress, Role.developer): [Status.api_check, Status.done],
    (Status.api_check, Role.developer): [Status.in_progress, Status.done],
    (Status.done, Role.reviewer): [Status.reviewing, Status.closed],
    (Status.reviewing, Role.reviewer): [Status.closed, Status.reopened],
    (Status.reopened, Role.developer): [Status.in_progress],
}


# 한국어 라벨 (UI 표시 전용)
STATUS_LABELS_KO: dict[Status, str] = {
    Status.requested: "요청됨",
    Status.in_progress: "확인중",
    Status.api_check: "API대기",
    Status.done: "완료",
    Status.reviewing: "검토중",
    Status.closed: "검토완료",
    Status.reopened: "재요청",
}

URGENCY_LABELS_KO: dict[str, str] = {
    "high": "긴급",
    "normal": "보통",
    "low": "낮음",
}


def allowed_transitions(current: Status, role: Role) -> list[Status]:
    """현재 상태와 역할 조합에서 허용되는 다음 상태들을 반환."""
    return list(TRANSITIONS.get((current, role), []))


def can_transition(current: Status, role: Role, target: Status) -> bool:
    """`current` → `target` 전이를 `role` 이 수행할 수 있는지 여부."""
    return target in TRANSITIONS.get((current, role), [])


def assert_transition(current: Status, role: Role, target: Status) -> None:
    """전이가 불가능하면 :class:`WorkflowError` 발생.

    repository 의 상태 변경 진입점에서 호출해 권한 우회를 차단한다.
    """
    if not can_transition(current, role, target):
        current_label = STATUS_LABELS_KO.get(current, current.value)
        target_label = STATUS_LABELS_KO.get(target, target.value)
        raise WorkflowError(
            f"허용되지 않은 상태 전이입니다: "
            f"'{current_label}' → '{target_label}' (역할: {role.value})"
        )


__all__ = [
    "WorkflowError",
    "TRANSITIONS",
    "STATUS_LABELS_KO",
    "URGENCY_LABELS_KO",
    "allowed_transitions",
    "can_transition",
    "assert_transition",
]
