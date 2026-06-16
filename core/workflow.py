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
    # 담당자확인요청 → 담당자검토중 / 확인대기(되돌리기) (담당자)
    #   담당자도 확인대기로 보낼 수 있다 (등록자와 동일하게 확인요청목록으로 되돌림).
    (Status.assignee_request, Role.developer): [
        Status.assignee_reviewing,
        Status.pending_check,
    ],
    # 담당자검토중 → 검토완료 / (되돌리기)확인요청 (담당자)
    (Status.assignee_reviewing, Role.developer): [
        Status.assignee_reviewed,
        Status.assignee_request,  # 직전 단계로
    ],
    # 검토완료 → 신규개발 / 코드수정 / 개발사확인 / (되돌리기)검토중 (담당자)
    (Status.assignee_reviewed, Role.developer): [
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_wait,
        Status.author_request,  # 개발 불필요 시 바로 등록자확인요청
        Status.assignee_reviewing,  # 직전 단계로
    ],
    # 개발사요청대기 → 개발사확인중(요청 송부) / (되돌리기)검토완료 (담당자)
    (Status.vendor_wait, Role.developer): [
        Status.vendor_request,
        Status.assignee_reviewed,  # 직전 단계로
    ],
    # 개발사확인중 → 개발사회신확인중 / (되돌리기)개발사요청대기 (담당자)
    (Status.vendor_request, Role.developer): [
        Status.vendor_reply,
        Status.vendor_wait,  # 직전 단계로
    ],
    # 개발사회신확인중 → 등록자확인요청 / 신규개발 / 코드수정 / (되돌리기)개발사확인중 (담당자)
    (Status.vendor_reply, Role.developer): [
        Status.author_request,
        Status.assignee_developing,
        Status.assignee_fixing,
        Status.vendor_request,  # 직전 단계로
    ],
    # 신규개발 → 등록자확인요청 / 개발사요청대기 / (되돌리기)검토완료 (담당자)
    #   개발 중 개발사 요청이 필요한 상황이 생기면 개발사요청대기로 보낼 수 있다.
    (Status.assignee_developing, Role.developer): [
        Status.author_request,
        Status.vendor_wait,
        Status.assignee_reviewed,  # 직전 단계로
    ],
    (Status.assignee_fixing, Role.developer): [
        Status.author_request,
        Status.assignee_reviewed,  # 직전 단계로
    ],
    # 등록자확인요청 → 등록자검토중 (등록자) / (되돌리기)검토완료 (담당자)
    (Status.author_request, Role.reviewer): [Status.author_reviewing],
    (Status.author_request, Role.developer): [Status.assignee_reviewed],
    # 등록자검토중 → 완료 / 담당자확인요청(반려) / (되돌리기)등록자확인요청 (등록자)
    (Status.author_reviewing, Role.reviewer): [
        Status.closed,
        Status.assignee_request,
        Status.author_request,  # 직전 단계로
    ],
    # 완료 → 등록자검토중 (등록자; 재개발이 필요해 다시 검토 단계로 되돌림)
    (Status.closed, Role.reviewer): [Status.author_reviewing],
    # 확인대기 ↔ 담당자확인요청. 담당자확인요청 → 확인대기 는 담당자/등록자 모두 가능
    # (위 developer 전이 + 아래 reviewer 전이). 확인대기 → 담당자확인요청 은 등록자가
    # 담당자 지정과 함께 보낸다(상세보기). 확인대기에서 개발/Temp 로 빠져나가는 것은
    # 확인요청목록·Temp 의 버튼이 kind 변경으로 처리한다.
    (Status.assignee_request, Role.reviewer): [Status.pending_check],
    (Status.pending_check, Role.reviewer): [Status.assignee_request],
}


# 한국어 라벨 (UI 표시 전용)
STATUS_LABELS_KO: dict[Status, str] = {
    Status.assignee_request: "담당자확인요청",
    Status.assignee_reviewing: "담당자검토중",
    Status.assignee_reviewed: "담당자검토완료",
    Status.assignee_developing: "담당자신규개발중",
    Status.assignee_fixing: "담당자코드수정중",
    Status.vendor_wait: "개발사요청대기",
    Status.vendor_request: "개발사확인중",
    Status.vendor_reply: "개발사회신확인중",
    Status.author_request: "등록자확인요청",
    Status.author_reviewing: "등록자검토중",
    Status.closed: "완료",
    Status.pending_check: "확인대기",
    Status.temp: "Temp",
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
