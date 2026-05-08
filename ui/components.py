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


def _stripe_html(color: str) -> str:
    """카드 좌측 색상 띠 (긴급도 색)."""
    return (
        f'<div style="position:absolute;left:0;top:0;bottom:0;'
        f'width:4px;background:{color};border-radius:4px 0 0 4px;"></div>'
    )


def _placeholder_html(text: str = "썸네일 없음") -> str:
    """썸네일 placeholder."""
    return (
        f'<div style="width:100%;aspect-ratio:1/1;background:#E5E7EB;'
        f'border-radius:4px;display:flex;align-items:center;justify-content:center;'
        f'color:#9CA3AF;font-size:0.7em;text-align:center;">{text}</div>'
    )


def render_card(item: dict[str, Any], *, key_prefix: str = "card") -> bool:
    """요청목록 카드 렌더 (컴팩트). 클릭 시 True 반환.

    item은 IndexEntry 직렬화 dict. 누락 키는 안전 기본값 사용.

    레이아웃 (A 패턴): 좌측 작은 썸네일 (1) + 우측 정보 (2) 가로 분할.
    컴팩트 유지: 폰트/패딩 축소, 한 줄에 등록·담당·상태 모두 표시.
    썸네일은 ``thumb_path`` 가 있으면 사용, 없고 ``images_count > 0`` 이면
    placeholder, 0 이면 "사진 없음" 박스.
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

    # 썸네일 절대 경로 변환: first_image_thumb (item_dir 기준 상대) → 절대.
    # 옛 인덱스 호환을 위해 thumb_path 키도 fallback 으로 받음.
    thumb_path: str | None = item.get("thumb_path")
    thumb_rel = item.get("first_image_thumb")
    if not thumb_path and thumb_rel and item_id:
        try:
            from pathlib import Path

            from core import paths as _paths  # 지연 import (테스트 격리)

            thumb_path = str(_paths.item_dir(item_id) / Path(thumb_rel))
        except Exception:
            thumb_path = None

    # XSS 방지: HTML로 렌더되는 사용자 입력은 모두 escape.
    safe_title = html.escape(str(title))
    safe_author = html.escape(str(author))
    safe_assignee = html.escape(str(assignee))
    safe_desc = html.escape(str(item.get("description_preview") or ""))

    # 카드 좌측 색상 띠 — 긴급도 색
    stripe_color = URGENCY_COLORS.get(urgency, "#9CA3AF")
    stripe_w = 3

    # height 인자 제거: 고정 220px 는 짧은 카드는 빈 공간, 긴 카드는 스크롤이
    # 생기는 문제 — 같은 행에서 가장 긴 카드의 자연스러운 높이로 통일하기 위해
    # 높이는 콘텐츠가 결정. 같은 행의 카드들이 동일 높이로 stretch 되도록
    # 페이지 측 (app.py / pages/1) 에서 _grid_stretch_css() 를 1 회 주입한다.
    with st.container(border=True):
        # 좌측 작은 썸네일 + 우측 정보 (1:2 가로 분할)
        thumb_col, info_col = st.columns([1, 2], gap="small")

        with thumb_col:
            if thumb_path:
                try:
                    st.image(thumb_path, use_container_width=True)
                except Exception:
                    st.markdown(
                        _placeholder_html(), unsafe_allow_html=True
                    )
            elif images_count > 0:
                st.markdown(_placeholder_html(), unsafe_allow_html=True)
            else:
                st.markdown(
                    _placeholder_html("사진 없음"),
                    unsafe_allow_html=True,
                )

        with info_col:
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

            # 설명 미리보기 (2 줄 line-clamp)
            if safe_desc:
                st.markdown(
                    f'<div style="font-size:0.8em;color:#475569;line-height:1.4;'
                    f'margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;'
                    f'-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;">'
                    f"{safe_desc}</div>",
                    unsafe_allow_html=True,
                )

        # 버튼은 카드 폭 전체에
        clicked = st.button(
            "열기",
            key=f"{key_prefix}_{item_id}_detail",
            use_container_width=True,
        )
    return clicked


# ---------------------------------------------------------------------------
# CSS 헬퍼 — 페이지 1 회 주입으로 같은 행 카드들이 같은 높이로 stretch 되게
# ---------------------------------------------------------------------------


def render_card_grid_css() -> None:
    """카드 그리드를 그리는 페이지에서 1 회 호출.

    같은 행 카드들이 가장 긴 카드 높이로 stretch 되도록 두 단계로 보강:

    1) **CSS flex stretch** — Streamlit columns DOM 의 모든 중간 div 를
       flex column 으로 만들고 height:100% / flex:1 적용.
    2) **JS ResizeObserver fallback** — CSS 가 Streamlit DOM 깊이를 따라
       잡지 못하는 경우를 대비, JS 가 같은 행 카드들의 offsetHeight 를 측정
       해 max 로 통일. ResizeObserver 로 콘텐츠 크기 변동에 자동 재계산.

    fragile 한 selector 들은 본 함수 한 곳에 모아둠. Streamlit 버전이
    바뀌어 selector 가 깨지면 여기만 수정.
    """
    st.markdown(
        """
        <style>
        /* 같은 행의 columns 가 stretch (가장 긴 카드 높이에 맞춤) */
        div[data-testid="stHorizontalBlock"] {
            align-items: stretch !important;
        }
        /* 컬럼 자체 + 안쪽 모든 div 를 height:100% 로 채우게 */
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div,
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div > div {
            height: 100% !important;
            display: flex;
            flex-direction: column;
        }
        /* st.container(border=True) 의 wrapper 도 flex column */
        div[data-testid="stHorizontalBlock"]
            div[data-testid="stVerticalBlockBorderWrapper"] {
            flex: 1 1 auto !important;
            height: 100% !important;
            display: flex;
            flex-direction: column;
        }
        div[data-testid="stHorizontalBlock"]
            div[data-testid="stVerticalBlockBorderWrapper"] > div {
            flex: 1 1 auto;
            display: flex;
            flex-direction: column;
        }
        </style>

        <script>
        (function() {
            // CSS 만으로 stretch 가 안 잡히는 케이스 대비. 같은 행 카드
            // (stVerticalBlockBorderWrapper) 의 max offsetHeight 로 통일.
            // ResizeObserver 로 이미지 로드/콘텐츠 변동 감지 → 재계산.
            function equalize() {
                const rows = document.querySelectorAll(
                    'div[data-testid="stHorizontalBlock"]'
                );
                rows.forEach(function(row) {
                    const cards = row.querySelectorAll(
                        'div[data-testid="stVerticalBlockBorderWrapper"]'
                    );
                    if (cards.length < 2) return;
                    cards.forEach(function(c) { c.style.minHeight = ''; });
                    let maxH = 0;
                    cards.forEach(function(c) {
                        if (c.offsetHeight > maxH) maxH = c.offsetHeight;
                    });
                    if (maxH > 0) {
                        cards.forEach(function(c) {
                            c.style.minHeight = maxH + 'px';
                        });
                    }
                });
            }
            // 초기 + 지연 + 변동 감지 — Streamlit rerun 시 DOM 재구성에도
            // 안전하게 다시 측정.
            equalize();
            setTimeout(equalize, 100);
            setTimeout(equalize, 400);
            setTimeout(equalize, 1000);
            try {
                const ro = new ResizeObserver(function() { equalize(); });
                ro.observe(document.body);
            } catch (e) { /* 구형 브라우저 fallback */ }
            window.addEventListener('load', equalize);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


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
    "render_card_grid_css",
    "render_badge",
    "render_count_metric",
    "humanize_dt",
    "STATUS_LABELS",
    "STATUS_COLORS",
]
