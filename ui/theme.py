"""색상/라벨/SLA 상수와 배지 HTML 헬퍼.

docs/03_ui_design.md 3.8 절(색상 매핑) 및 docs/04_workflow.md 4.4 절(SLA) 참고.
순수 상수 + 문자열 가공만 담당하므로 streamlit 의존성 없음.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 긴급도 (Urgency) 매핑 — 빨강/주황/초록 (3.8절)
# ---------------------------------------------------------------------------

URGENCY_COLORS: dict[str, str] = {
    "high": "#E53935",
    "normal": "#FB8C00",
    "low": "#43A047",
}

URGENCY_LABELS: dict[str, str] = {
    "high": "긴급",
    "normal": "보통",
    "low": "낮음",
}

# ---------------------------------------------------------------------------
# 상태 (Status) 매핑 — 무채색/한색 계열 (3.8절)
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, str] = {
    "requested": "#3B82F6",
    "in_progress": "#8B5CF6",
    "api_check": "#06B6D4",
    "done": "#10B981",
    "reviewing": "#F59E0B",
    "reopened": "#EF4444",
    "closed": "#6B7280",
}

STATUS_LABELS: dict[str, str] = {
    "requested": "요청중",
    "in_progress": "작업중",
    "api_check": "API대기",
    "done": "작업완료",  # 레거시 — 새 흐름에서는 안 만들어짐
    "reviewing": "검토중",
    "reopened": "재요청",
    "closed": "완료",
}

# ---------------------------------------------------------------------------
# SLA 정책 (docs/04_workflow.md 4.4)
# 1영업일은 8시간으로 근사, 3영업일은 24시간으로 근사.
# low의 처리 완료는 "협의" → None.
# ---------------------------------------------------------------------------

SLA_FIRST_RESPONSE: dict[str, timedelta] = {
    "high": timedelta(hours=2),
    "normal": timedelta(hours=8),
    "low": timedelta(hours=24) * 3,
}

SLA_RESOLUTION: dict[str, timedelta | None] = {
    "high": timedelta(hours=24),
    "normal": timedelta(hours=72),
    "low": None,
}

# 첫 응답 SLA가 의미 있는 상태(아직 개발자가 잡지 않은 상태)
_PENDING_FIRST_RESPONSE = {"requested", "reopened"}


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


# ---------------------------------------------------------------------------
# SLA 판정
# ---------------------------------------------------------------------------


def _coerce_dt(value: datetime | str) -> datetime:
    """str/datetime을 datetime으로 정규화. 둘 다 tz-aware 가정."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _now_kst() -> datetime:
    """기본 now — core.clock가 있으면 활용, 없으면 OS UTC."""
    try:
        from core.clock import now as _now  # type: ignore[import-not-found]

        return _now()
    except Exception:  # pragma: no cover - core 미설치 환경 fallback
        from datetime import timezone

        return datetime.now(timezone.utc)


def is_sla_violated(
    urgency: str,
    created_at: datetime | str,
    status: str,
    *,
    now: datetime | None = None,
) -> bool:
    """첫 응답 SLA 위반 여부.

    아직 개발자가 잡지 않은 상태(``requested`` / ``reopened``)에서
    ``urgency`` 의 첫 응답 한도를 초과했으면 True.
    """
    if status not in _PENDING_FIRST_RESPONSE:
        return False
    limit = SLA_FIRST_RESPONSE.get(urgency)
    if limit is None:
        return False
    base = now if now is not None else _now_kst()
    elapsed = base - _coerce_dt(created_at)
    return elapsed >= limit


def is_sla_warning(
    urgency: str,
    created_at: datetime | str,
    status: str,
    *,
    now: datetime | None = None,
) -> bool:
    """첫 응답 SLA 임박(50% 이상 경과) 여부. 위반 상태이면 False(이미 위반)."""
    if status not in _PENDING_FIRST_RESPONSE:
        return False
    limit = SLA_FIRST_RESPONSE.get(urgency)
    if limit is None:
        return False
    base = now if now is not None else _now_kst()
    elapsed = base - _coerce_dt(created_at)
    if elapsed >= limit:
        return False
    return elapsed >= (limit / 2)


__all__ = [
    "URGENCY_COLORS",
    "URGENCY_LABELS",
    "STATUS_COLORS",
    "STATUS_LABELS",
    "SLA_FIRST_RESPONSE",
    "SLA_RESOLUTION",
    "urgency_badge_html",
    "status_badge_html",
    "is_sla_violated",
    "is_sla_warning",
]
