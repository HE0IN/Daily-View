"""시간 단일 출처 모듈.

모든 자동 시간 기록은 이 모듈의 :func:`now` 만 사용한다.
시간대는 한국 표준시(KST, UTC+9) 로 고정되며, 직렬화는 ISO 8601(오프셋 포함) 형식.

자세한 정책은 docs/02_storage.md 2.10 절 참고.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now() -> datetime:
    """현재 시각을 KST timezone-aware datetime으로 반환.

    모든 자동 기록(생성/수정/상태 전이/코멘트 등)은 이 함수만 사용해야 한다.
    """
    return datetime.now(KST)


def to_iso(dt: datetime) -> str:
    """datetime을 ISO 8601 문자열로 직렬화 (오프셋 포함)."""
    if dt.tzinfo is None:
        # naive datetime은 KST로 간주하여 보정
        dt = dt.replace(tzinfo=KST)
    return dt.isoformat(timespec="seconds")


def from_iso(s: str) -> datetime:
    """ISO 8601 문자열을 KST 기준 timezone-aware datetime으로 복원."""
    if not isinstance(s, str) or not s:
        raise ValueError(f"빈 ISO 문자열은 파싱할 수 없습니다: {s!r}")
    # Python 3.12에서는 'Z' 접미사도 fromisoformat으로 처리 가능
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # 오프셋이 없으면 KST로 간주
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def humanize(dt: datetime, *, ref: datetime | None = None) -> str:
    """상대 시간을 한국어 문자열로 표현.

    예: "방금", "5분 전", "어제 13:20", "2일 전", "2026-04-01"
    `ref`가 None이면 :func:`now` 를 기준으로 한다.
    """
    base = ref if ref is not None else now()

    # 비교를 위해 양쪽 모두 timezone-aware로 보정
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    if base.tzinfo is None:
        base = base.replace(tzinfo=KST)

    delta = base - dt
    seconds = int(delta.total_seconds())

    # 미래 시각 방어 (시계 어긋남 등)
    if seconds < 0:
        return "잠시 후"

    if seconds < 60:
        return "방금"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400 and base.date() == dt.date():
        return f"{seconds // 3600}시간 전"

    # 날짜 경계를 넘어가면 "어제 / N일 전 / 절대 날짜"
    days = (base.date() - dt.date()).days
    if days == 1:
        return f"어제 {dt.strftime('%H:%M')}"
    if days < 7:
        return f"{days}일 전"
    if days < 30:
        return f"{days // 7}주 전"
    # 한 달 이상은 절대 날짜로
    return dt.strftime("%Y-%m-%d")


__all__ = ["KST", "now", "to_iso", "from_iso", "humanize"]
