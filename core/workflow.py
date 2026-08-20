"""상태 전이 규칙.

**워크플로우 14 단계 사이는 자유롭게 이동한다** (2026-08-19 사용자 결정).
어느 단계에서든 어느 단계로든 바로 갈 수 있다 — 건너뛰기·되돌리기 모두 허용.

예전에는 ``(현재 상태, 역할) → 허용 목록`` 매트릭스로 다음 단계를 강제했는데,
실제 업무에서는 순서를 건너뛰거나 앞 단계로 되돌리는 일이 수시로 생겨 매번
막혔다. 그래서 매트릭스를 걷어냈다.

다만 **확인대기(pending_check)** 와 **Temp(temp)** 는 예외다. 이 둘은 항목 종류
(``kind``)와 묶여 있어서, 상태만 바꾸면 확인요청목록에도 개발목록에도 안 잡히는
미아 항목이 된다. 그래서 kind 까지 함께 바꾸는 전용 경로로만 오간다
(``repository.send_dev_to_pending`` / ``send_pending_to_dev`` /
``promote_to_criteria`` / ``revert_criteria_to_request``).
"""

from __future__ import annotations

from .models import Role, Status


class WorkflowError(Exception):
    """워크플로우 규칙 위반(허용되지 않은 상태 전이 등) 시 발생."""


# 워크플로우 단계 — 이 안에서는 어느 쪽으로든 자유롭게 이동한다.
# 목록 순서 = UI 에 노출되는 순서(업무 흐름 순)라 그대로 화면 정렬에 쓴다.
WORKFLOW_STATUSES: tuple[Status, ...] = (
    Status.assignee_request,      # 담당자확인요청
    Status.assignee_reviewing,    # 담당자검토중
    Status.assignee_reviewed,     # 담당자검토완료
    Status.assignee_developing,   # 담당자신규개발중
    Status.assignee_fixing,       # 담당자코드수정중
    Status.vendor_wait,           # 개발사요청대기
    Status.vendor_request,        # 개발사확인중
    Status.vendor_reply,          # 개발사회신확인중
    Status.team_wait,             # 담당팀요청대기
    Status.team_request,          # 담당팀확인중
    Status.team_reply,            # 담당팀회신확인중
    Status.author_request,        # 등록자확인요청
    Status.author_reviewing,      # 등록자검토중
    Status.closed,                # 완료
)

# kind 와 묶인 상태들 — 자유 이동에서 제외. 여기서 나가는 경로만 좁게 허용하고,
# 실제 이동은 kind 까지 바꾸는 repository 전용 함수가 처리한다.
KIND_BOUND_TRANSITIONS: dict[Status, list[Status]] = {
    Status.pending_check: [Status.assignee_request],  # 확인요청목록 → 개발목록
    Status.temp: [Status.pending_check],              # Temp → 확인요청목록
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
    Status.team_wait: "담당팀요청대기",
    Status.team_request: "담당팀확인중",
    Status.team_reply: "담당팀회신확인중",
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

# 성격(정리) 라벨 — rule_status (docs/09). Temp/RuleBook UI 표시 전용.
RULE_STATUS_LABELS_KO: dict[str, str] = {
    "unsorted": "미분류",
    "needs_check": "확인필요",
    "confirmed": "확정규칙",
}
RULE_STATUS_ICONS: dict[str, str] = {
    "unsorted": "⬜",
    "needs_check": "🔍",
    "confirmed": "✅",
}
RULE_STATUS_COLORS: dict[str, str] = {
    "unsorted": "#9CA3AF",   # 회색
    "needs_check": "#D97706",  # 주황
    "confirmed": "#16A34A",  # 녹색
}


def rule_status_label(rule_status: str, *, icon: bool = True) -> str:
    """rule_status 를 아이콘+한국어 라벨로. 알 수 없으면 값 그대로."""
    ko = RULE_STATUS_LABELS_KO.get(rule_status, rule_status)
    if icon:
        return f"{RULE_STATUS_ICONS.get(rule_status, '')} {ko}".strip()
    return ko


def allowed_transitions(current: Status, role: Role | None = None) -> list[Status]:
    """현재 상태에서 갈 수 있는 상태 목록.

    워크플로우 단계면 **자기 자신을 뺀 나머지 전부** 를 흐름 순서대로 반환한다.
    ``role`` 은 더 이상 결과에 영향을 주지 않는다 — 옛 호출부 호환을 위해 인자만
    남겨뒀다 (누가 바꾸든 갈 수 있는 단계는 같다).
    """
    if current in WORKFLOW_STATUSES:
        return [s for s in WORKFLOW_STATUSES if s != current]
    return list(KIND_BOUND_TRANSITIONS.get(current, []))


def can_transition(
    current: Status, role: Role | None, target: Status
) -> bool:
    """`current` → `target` 이동이 가능한지 여부. 역할은 보지 않는다."""
    return target in allowed_transitions(current, role)


def assert_transition(
    current: Status, role: Role | None, target: Status
) -> None:
    """이동이 불가능하면 :class:`WorkflowError` 발생.

    자유 이동이라 워크플로우 단계끼리는 통과한다. 확인대기/Temp 처럼 kind 와
    묶인 상태로 곧장 넘어가려 할 때만 막는다 (그건 전용 함수로 가야 한다).
    """
    if not can_transition(current, role, target):
        current_label = STATUS_LABELS_KO.get(current, current.value)
        target_label = STATUS_LABELS_KO.get(target, target.value)
        raise WorkflowError(
            f"허용되지 않은 상태 전이입니다: "
            f"'{current_label}' → '{target_label}' "
            f"(확인대기·Temp 는 목록 이동 전용 버튼을 사용하세요)"
        )


__all__ = [
    "WorkflowError",
    "WORKFLOW_STATUSES",
    "KIND_BOUND_TRANSITIONS",
    "STATUS_LABELS_KO",
    "URGENCY_LABELS_KO",
    "RULE_STATUS_LABELS_KO",
    "RULE_STATUS_ICONS",
    "RULE_STATUS_COLORS",
    "rule_status_label",
    "allowed_transitions",
    "can_transition",
    "assert_transition",
]
