"""재사용 카드/배지/카운트 컴포넌트.

docs/03_ui_design.md 3.4(요청 목록 카드) + 3.5(상세 페이지) 참고.
HTML은 모두 ``unsafe_allow_html=True`` 로 렌더되는 것을 전제로 한다.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import streamlit as st

from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_COLORS,
    is_sla_violated,
    is_sla_warning,
    status_badge_html,
    urgency_badge_html,
)


def render_badge(text: str, color: str) -> str:
    """간단한 색상 배지 span HTML."""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{color};color:#fff;font-size:0.85em;font-weight:600;">'
        f"{text}</span>"
    )


def humanize_dt(dt_str: str | datetime) -> str:
    """상대 시간 한국어 표기. core.clock.humanize 의 wrapper.

    core 미설치/오류 시 ISO 문자열 또는 strftime fallback.
    """
    try:
        from core.clock import from_iso, humanize  # type: ignore[import-not-found]

        dt = from_iso(dt_str) if isinstance(dt_str, str) else dt_str
        return humanize(dt)
    except Exception:
        if isinstance(dt_str, datetime):
            return dt_str.strftime("%Y-%m-%d %H:%M")
        return str(dt_str)


def _stripe_html(color: str, *, thick: bool = False) -> str:
    """카드 좌측 색상 띠. ``thick`` 이면 SLA 위반 강조."""
    width = 8 if thick else 4
    return (
        f'<div style="position:absolute;left:0;top:0;bottom:0;'
        f'width:{width}px;background:{color};border-radius:4px 0 0 4px;"></div>'
    )


def _placeholder_html() -> str:
    """썸네일 placeholder."""
    return (
        '<div style="width:100%;aspect-ratio:16/9;background:#E5E7EB;'
        'border-radius:4px;display:flex;align-items:center;justify-content:center;'
        'color:#9CA3AF;font-size:0.85em;">썸네일 없음</div>'
    )


def render_card(item: dict[str, Any], *, key_prefix: str = "card") -> bool:
    """요청목록 카드 렌더. 클릭 시 True 반환.

    item은 IndexEntry 직렬화 dict. 누락 키는 안전 기본값 사용.
    """
    item_id = item.get("id", "")
    title = item.get("title", "(제목 없음)")
    urgency = item.get("urgency", "normal")
    status = item.get("status", "requested")
    author = item.get("author", "-")
    assignee = item.get("assignee") or "-"
    created_at = item.get("created_at", "")
    comments_count = int(item.get("comments_count", 0) or 0)
    images_count = int(item.get("images_count", 0) or 0)
    thumb_path = item.get("thumb_path")

    # XSS 방지: HTML로 렌더되는 사용자 입력은 모두 escape.
    safe_title = html.escape(str(title))
    safe_author = html.escape(str(author))
    safe_assignee = html.escape(str(assignee))
    safe_item_id = html.escape(str(item_id))

    # SLA 판정 — 좌측 띠 굵기 결정
    violated = bool(created_at) and is_sla_violated(urgency, created_at, status)
    warning = bool(created_at) and is_sla_warning(urgency, created_at, status)
    stripe_color = (
        "#DC2626" if violated else URGENCY_COLORS.get(urgency, "#9CA3AF")
    )

    with st.container(border=True):
        # 좌측 색상 띠 (위치 잡기 위해 wrapper에 position:relative)
        st.markdown(
            f'<div style="position:relative;padding-left:12px;">'
            f"{_stripe_html(stripe_color, thick=violated or warning)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 썸네일
        if thumb_path:
            try:
                st.image(thumb_path, use_container_width=True)
            except Exception:
                st.markdown(_placeholder_html(), unsafe_allow_html=True)
        else:
            st.markdown(_placeholder_html(), unsafe_allow_html=True)

        # 배지 + ID
        st.markdown(
            f"{urgency_badge_html(urgency)} &nbsp; "
            f'<span style="color:#6B7280;font-size:0.8em;">#{safe_item_id}</span>',
            unsafe_allow_html=True,
        )

        # 제목 — markdown 렌더가 아닌 평문 표시(굵기만 유지)
        st.markdown(
            f'<div style="font-weight:700;font-size:1.05em;">{safe_title}</div>',
            unsafe_allow_html=True,
        )

        # 메타: 등록/담당/상태
        st.markdown(
            f'<div style="font-size:0.85em;color:#374151;">'
            f"등록: {safe_author} · 담당: {safe_assignee}<br/>"
            f"상태: {status_badge_html(status)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 카운트 + 시간
        st.markdown(
            f'<div style="font-size:0.8em;color:#6B7280;margin-top:4px;">'
            f"코멘트 {comments_count} · 이미지 {images_count} · "
            f"{humanize_dt(created_at) if created_at else '-'}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # SLA 경고 라벨
        if violated:
            st.markdown(
                render_badge("SLA 위반", "#DC2626"),
                unsafe_allow_html=True,
            )
        elif warning:
            st.markdown(
                render_badge("SLA 임박", "#F59E0B"),
                unsafe_allow_html=True,
            )

        clicked = st.button(
            "상세보기",
            key=f"{key_prefix}_{item_id}_detail",
            use_container_width=True,
        )
    return clicked


def render_count_metric(
    label: str, count: int, color: str | None = None
) -> None:
    """대시보드용 숫자 카드. color가 있으면 좌측 띠로 색상 표시."""
    if color:
        st.markdown(
            f'<div style="position:relative;padding:8px 12px 8px 16px;'
            f'border-radius:6px;border:1px solid #E5E7EB;">'
            f'<div style="position:absolute;left:0;top:0;bottom:0;width:4px;'
            f'background:{color};border-radius:6px 0 0 6px;"></div>'
            f'<div style="font-size:0.8em;color:#6B7280;">{label}</div>'
            f'<div style="font-size:1.5em;font-weight:700;color:#111827;">{count}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.metric(label=label, value=count)


# 상태/긴급도 라벨도 외부에서 재사용 가능하도록 노출
__all__ = [
    "render_card",
    "render_badge",
    "render_count_metric",
    "humanize_dt",
    "STATUS_LABELS",
    "STATUS_COLORS",
]
