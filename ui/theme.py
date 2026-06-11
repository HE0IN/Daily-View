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
    "assignee_request": "#3B82F6",      # 파랑 (담당자확인요청)
    "assignee_reviewing": "#6366F1",    # 인디고 (담당자검토중)
    "assignee_reviewed": "#8B5CF6",     # 보라 (담당자검토완료)
    "assignee_developing": "#A855F7",   # 자주 (담당자신규개발중)
    "assignee_fixing": "#C026D3",       # 자홍 (담당자코드수정중)
    "vendor_wait": "#67E8F9",           # 연청록 (개발사요청대기)
    "vendor_request": "#06B6D4",        # 청록 (개발사확인중)
    "vendor_reply": "#0891B2",          # 진청록 (개발사회신확인중)
    "author_request": "#F59E0B",        # 주황 (등록자확인요청)
    "author_reviewing": "#F97316",      # 진주황 (등록자검토중)
    "closed": "#6B7280",                # 회색 (완료)
    "pending_check": "#0D9488",         # 청록 (확인대기 — 확인요청 항목)
    "temp": "#8B5CF6",                  # 보라 (Temp — 확정 보류)
}

STATUS_LABELS: dict[str, str] = {
    "assignee_request": "담당자확인요청",
    "assignee_reviewing": "담당자검토중",
    "assignee_reviewed": "담당자검토완료",
    "assignee_developing": "담당자신규개발중",
    "assignee_fixing": "담당자코드수정중",
    "vendor_wait": "개발사요청대기",
    "vendor_request": "개발사확인중",
    "vendor_reply": "개발사회신확인중",
    "author_request": "등록자확인요청",
    "author_reviewing": "등록자검토중",
    "closed": "완료",
    "pending_check": "확인대기",
    "temp": "Temp",
}

# ---------------------------------------------------------------------------
# 이미지 구분 (요청 AS-IS / 개발 TO-BE)
# ---------------------------------------------------------------------------

IMAGE_KIND_LABELS: dict[str, str] = {
    "request": "요청(AS-IS)",
    "dev": "개발(TO-BE)",
}
IMAGE_KIND_COLORS: dict[str, str] = {
    "request": "#3B82F6",  # 파랑 (요청·현황)
    "dev": "#10B981",      # 초록 (개발·결과)
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
    "IMAGE_KIND_LABELS",
    "IMAGE_KIND_COLORS",
    "urgency_badge_html",
    "status_badge_html",
]
