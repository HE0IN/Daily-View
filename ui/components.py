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
    """요청목록 카드 렌더 (컴팩트). 클릭 시 True 반환.

    item은 IndexEntry 직렬화 dict. 누락 키는 안전 기본값 사용.

    컴팩트 변경: 썸네일 제거(상세보기에서 보면 충분), 폰트/패딩 축소,
    한 줄에 등록·담당·상태 모두 표시 → 한 화면에 더 많은 카드.
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

    # XSS 방지: HTML로 렌더되는 사용자 입력은 모두 escape.
    safe_title = html.escape(str(title))
    safe_author = html.escape(str(author))
    safe_assignee = html.escape(str(assignee))

    # SLA 판정 — 카드 좌측 색상 띠
    violated = bool(created_at) and is_sla_violated(urgency, created_at, status)
    warning = bool(created_at) and is_sla_warning(urgency, created_at, status)
    stripe_color = (
        "#DC2626" if violated else URGENCY_COLORS.get(urgency, "#9CA3AF")
    )
    stripe_w = 6 if (violated or warning) else 3

    with st.container(border=True):
        # 좌측 색상 띠 + 1줄 헤더(긴급도 배지 + 상태 배지 + 시간)
        st.markdown(
            f'<div style="position:relative;padding:2px 0 2px 10px;">'
            f'<div style="position:absolute;left:0;top:0;bottom:0;width:{stripe_w}px;'
            f'background:{stripe_color};border-radius:2px;"></div>'
            f"{urgency_badge_html(urgency)} {status_badge_html(status)} "
            f'<span style="color:#9CA3AF;font-size:0.75em;float:right;">'
            f"{humanize_dt(created_at) if created_at else ''}"
            f"</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 제목 (작게)
        st.markdown(
            f'<div style="font-weight:600;font-size:0.95em;line-height:1.3;'
            f'margin:4px 0 2px 0;">{safe_title}</div>',
            unsafe_allow_html=True,
        )

        # 한 줄 메타: 등록 · 담당 · 코멘트 N · 이미지 N
        st.markdown(
            f'<div style="font-size:0.75em;color:#6B7280;line-height:1.4;">'
            f"{safe_author} → {safe_assignee} · 💬 {comments_count} · 📷 {images_count}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # SLA 경고 라벨 (위반·임박만)
        if violated:
            st.markdown(
                f'<div style="margin-top:2px;">{render_badge("SLA 위반", "#DC2626")}</div>',
                unsafe_allow_html=True,
            )
        elif warning:
            st.markdown(
                f'<div style="margin-top:2px;">{render_badge("SLA 임박", "#F59E0B")}</div>',
                unsafe_allow_html=True,
            )

        clicked = st.button(
            "열기",
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
