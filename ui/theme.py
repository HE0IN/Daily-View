"""색상/라벨 상수와 배지 HTML 헬퍼.

docs/03_ui_design.md 3.8 절(색상 매핑) 참고.
순수 상수 + 문자열 가공만 담당하므로 streamlit 의존성 없음.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 긴급도 (Urgency) 매핑 — 빨강/주황/초록 (3.8절)
# ---------------------------------------------------------------------------

URGENCY_COLORS: dict[str, str] = {
    "critical": "#DC2626",  # 빨강 (긴급)
    "high":     "#E53935",  # 진빨강 (상)
    "normal":   "#FB8C00",  # 주황 (중)
    "low":      "#43A047",  # 초록 (하)
}

URGENCY_LABELS: dict[str, str] = {
    "critical": "긴급",
    "high": "상",
    "normal": "중",
    "low": "하",
}

# ---------------------------------------------------------------------------
# 상태 (Status) 매핑 — 무채색/한색 계열 (3.8절)
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, str] = {
    "requested": "#3B82F6",      # 파랑
    "in_progress": "#8B5CF6",    # 보라
    "api_check": "#06B6D4",      # 청록
    "reviewing": "#F59E0B",      # 주황
    "needs_recheck": "#F97316",  # 진주황 (추가확인필요)
    "rejected": "#DC2626",       # 빨강 (반려)
    "closed": "#6B7280",         # 회색 (완료)
    # 레거시
    "done": "#10B981",
    "reopened": "#EF4444",
}

STATUS_LABELS: dict[str, str] = {
    "requested": "요청중",
    "in_progress": "개발중",
    "api_check": "API대기",
    "reviewing": "검토중",
    "needs_recheck": "추가확인필요",
    "rejected": "반려",
    "closed": "완료",
    # 레거시 — 새 흐름에서는 안 만들어짐
    "done": "작업완료",
    "reopened": "재요청",
}

# ---------------------------------------------------------------------------
# 배지 HTML 헬퍼
# ---------------------------------------------------------------------------


def _badge_span(text: str, color: str) -> str:
    """공통 배지 span. unsafe_allow_html=True 전제."""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{color};color:#fff;font-size:0.85em;font-weight:600;">'
        f"{text}</span>"
    )


def urgency_badge_html(urgency: str) -> str:
    """긴급도 배지 HTML."""
    color = URGENCY_COLORS.get(urgency, "#9CA3AF")
    label = URGENCY_LABELS.get(urgency, urgency)
    return _badge_span(label, color)


def status_badge_html(status: str) -> str:
    """상태 배지 HTML."""
    color = STATUS_COLORS.get(status, "#9CA3AF")
    label = STATUS_LABELS.get(status, status)
    return _badge_span(label, color)


__all__ = [
    "URGENCY_COLORS",
    "URGENCY_LABELS",
    "STATUS_COLORS",
    "STATUS_LABELS",
    "urgency_badge_html",
    "status_badge_html",
]
