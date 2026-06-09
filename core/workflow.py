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
# 운영 흐름 (검토중 1 단계, 사용자 합의):
#   요청중 → 개발중 → (API대기) → 검토중 → 완료
#                                    ├ 추가확인필요 → 개발중
#                                    └ 반려          → 개발중
#
# - 등록 → ``requested`` (요청중)               ※ 검토자/개발자 모두
# - 개발자 착수 → ``in_progress`` (개발중)
# - 작업 중 외부 의존 발견 → ``api_check`` (API대기)
# - 개발자가 작업 종료 → 바로 ``reviewing`` (검토중) 으로 전환
# - 검토자 판단 (검토중에서 3 갈래):
#     · OK            → ``closed``        (완료)
#     · 추가확인필요  → ``needs_recheck`` → 개발자가 ``in_progress`` 로
#     · 반려(불통)    → ``rejected``      → 개발자가 ``in_progress`` 로
#
# ``done`` / ``reopened`` 은 레거시 — 새 흐름에서는 도달하지 않지만 옛 데이터
# 호환을 위해 전이를 남겨, 검토자/개발자가 새 상태로 정리할 수 있게 한다.
#   Role.developer = '담당자'(assignee) 권한, Role.reviewer = '등록자'(author) 권한.
TRANSITIONS: dict[tuple[Status, Role], list[Status]] = {
    # 담당자확인요청 → 담당자검토중 (담당자)
    (Status.assignee_request, Role.developer): [Status.assignee_reviewing],
    # 담당자검토중 → 담당자검토완료 (담당자)
    (Status.assignee_reviewing, Role.developer): [Status.assignee_reviewed],
    # 담당자검토완료 → 신규개발 / 코드수정 / 개발사확인 (담당자)
    (Status.assignee_reviewed, Role.developer): [
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_request,
    ],
    # 개발사확인중 → 개발사회신확인중 (담당자)
    (Status.vendor_request, Role.developer): [Status.vendor_reply],
    # 개발사회신확인중 → 등록자확인요청 / 신규개발 / 코드수정 (담당자)
    (Status.vendor_reply, Role.developer): [
        Status.author_request,
        Status.assignee_developing,
        Status.assignee_fixing,
    ],
    # 담당자 신규개발/코드수정 → 등록자확인요청 (담당자)
    (Status.assignee_developing, Role.developer): [Status.author_request],
    (Status.assignee_fixing, Role.developer): [Status.author_request],
    # 등록자확인요청 → 등록자검토중 (등록자)
    (Status.author_request, Role.reviewer): [Status.author_reviewing],
    # 등록자검토중 → 완료 / 담당자확인요청(반려) (등록자)
    (Status.author_reviewing, Role.reviewer): [
        Status.closed,
        Status.assignee_request,
    ],
}


# 한국어 라벨 (UI 표시 전용)
STATUS_LABELS_KO: dict[Status, str] = {
    Status.assignee_request: "담당자확인요청",
    Status.assignee_reviewing: "담당자검토중",
    Status.assignee_reviewed: "담당자검토완료",
    Status.assignee_developing: "담당자신규개발중",
    Status.assignee_fixing: "담당자코드수정중",
    Status.vendor_request: "개발사확인중",
    Status.vendor_reply: "개발사회신확인중",
    Status.author_request: "등록자확인요청",
    Status.author_reviewing: "등록자검토중",
    Status.closed: "완료",
}

URGENCY_LABELS_KO: dict[str, str] = {
    "critical": "긴급",
    "high": "상",
    "normal": "중",
    "low": "하",
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
