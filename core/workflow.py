"""상태 전이 규칙과 권한 체크.

docs/04_workflow.md 4.3 절의 권한 매트릭스를 코드로 옮겨 단일 진실 출처로 둔다.
UI는 :func:`allowed_transitions` 결과만 렌더해야 하며, 서버측 변경 직전에는
:func:`assert_transition` 으로 한 번 더 가드한다.
"""

from __future__ import annotations

from .models import Role, Status


class WorkflowError(Exception):
    """워크플로우 규칙 위반(허용되지 않은 상태 전이 등) 시 발생."""


# 권한 매트릭스 — (현재 상태, 역할) → 허용되는 다음 상태들.
#
# 운영 흐름 (단순화된 버전, 사용자 합의):
#   요청중 → 작업중 → (API대기) → 검토중 → 완료
#                                    ↘ 재요청 → 작업중
#
# - 검토자 등록 → ``requested`` (요청중)
# - 개발자 확인 → ``in_progress`` (작업중)  ※ 라벨 의미 변경: 확인중 → 작업중
# - 작업 중 외부 의존 발견 → ``api_check`` (API대기)
# - 개발자가 작업 종료 → 바로 ``reviewing`` (검토중) 으로 전환
#   (기존엔 done 단계를 거쳤으나 중간 단계 제거)
# - 검토자 OK → ``closed`` (완료)
# - 검토자 NG → ``reopened`` → ``in_progress`` 로 다시
#
# ``done`` 상태는 새 흐름에서는 사용하지 않지만 enum 은 유지 (기존 데이터 호환).
# 기존 done 항목은 검토자가 직접 검토중/완료/재요청으로 정리할 수 있도록
# 호환 전이만 남긴다.
TRANSITIONS: dict[tuple[Status, Role], list[Status]] = {
    # 새 흐름
    (Status.requested, Role.developer): [Status.in_progress],
    (Status.requested, Role.reviewer): [Status.closed],  # 검토자 자체 취소
    (Status.in_progress, Role.developer): [Status.api_check, Status.reviewing],
    (Status.api_check, Role.developer): [Status.in_progress, Status.reviewing],
    (Status.reviewing, Role.reviewer): [Status.closed, Status.reopened],
    (Status.reopened, Role.developer): [Status.in_progress],
    # 레거시 호환 — 옛 데이터의 done 항목용 (새 흐름에서는 도달 안 함)
    (Status.done, Role.reviewer): [Status.reviewing, Status.closed, Status.reopened],
}


# 한국어 라벨 (UI 표시 전용)
STATUS_LABELS_KO: dict[Status, str] = {
    Status.requested: "요청중",
    Status.in_progress: "작업중",
    Status.api_check: "API대기",
    Status.done: "작업완료",  # 레거시 — 새 흐름에서는 안 만들어짐
    Status.reviewing: "검토중",
    Status.closed: "완료",
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
