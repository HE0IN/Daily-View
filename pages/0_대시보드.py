"""대시보드 페이지 (st.navigation 라우팅).

역할(검토자/개발자)에 따라 카드 섹션과 메인 CTA가 달라진다.
공통 처리(부트스트랩·자동새로고침·사용자식별·프로젝트선택)는 진입점 app.py(라우터)가
수행하고, 이 페이지는 session_state 의 user / _current_project 를 읽어 사용한다.
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.logger import tail_audit
from core.models import Status
from ui import components
from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_COLORS,
    URGENCY_LABELS,
)

# 라우터가 보장하지만 방어적으로 — user 없으면 정지.
user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
role: str = user.get("role", "reviewer")
role_label = "검토자" if role == "reviewer" else "개발자"
current_project: str | None = st.session_state.get("_current_project")

# 카드 그리드 CSS — 같은 행 카드들이 가장 긴 카드 높이로 stretch
components.render_card_grid_css()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _entries_to_dicts(entries) -> list[dict]:
    """IndexEntry 리스트를 dict 리스트로 직렬화."""
    return [e.model_dump(mode="json") for e in entries]


def _render_card_grid(items: list[dict], *, key_prefix: str, cols: int = 4) -> None:
    """카드 그리드 렌더. 클릭 시 상세보기로 이동."""
    if not items:
        st.info("해당 항목이 없습니다.")
        return

    for row_start in range(0, len(items), cols):
        row = items[row_start : row_start + cols]
        col_objs = st.columns(cols)
        for col, item in zip(col_objs, row):
            with col:
                clicked = components.render_card(
                    item, key_prefix=f"{key_prefix}_{row_start}"
                )
                if clicked:
                    _iid = item.get("id", "")
                    st.session_state["_detail_item_id"] = _iid
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _count_by(entries, attr: str) -> dict[str, int]:
    """긴급도/상태별 카운트."""
    counts: dict[str, int] = {}
    for e in entries:
        value = getattr(e, attr, None)
        key = value.value if hasattr(value, "value") else (value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

if current_project:
    st.caption(f"{current_project} / 대시보드")
st.title("대시보드")
st.write(f"안녕하세요, **{name}**님 ({role_label})")


# ---------------------------------------------------------------------------
# 데이터 로드 (전체 활성 + 보관함 제외)
# ---------------------------------------------------------------------------

all_active = repository.list_issues(
    include_archived=False, include_closed=True, project=current_project
)
active_only = repository.list_issues(
    include_archived=False, include_closed=False, project=current_project
)

# 상태별 카운트 — 사이드바 '상태 바로가기' + (검토자) 전체 현황 공용.
status_counts = _count_by(active_only, "status")
STATUS_NAV_KEYS = [
    "requested",
    "in_progress",
    "api_check",
    "reviewing",
    "needs_recheck",
    "rejected",
]


# ---------------------------------------------------------------------------
# 역할별 본문
# ---------------------------------------------------------------------------

if role == "reviewer":
    # ── 검토자 화면 ───────────────────────────────────────────────────────
    cta_col, _ = st.columns([1, 4])
    with cta_col:
        if st.button("+ 새 개발 등록", type="primary", width="stretch"):
            st.switch_page("pages/2_새요청등록.py")

    st.divider()

    review_queue_entries = [
        e
        for e in all_active
        if e.author == name and e.status in (Status.reviewing, Status.done)
    ]
    review_queue = _entries_to_dicts(review_queue_entries)

    st.subheader(f"검토 대기 ({len(review_queue)})")
    st.caption("개발자가 작업을 끝내 검토를 기다리는 항목")
    _render_card_grid(review_queue, key_prefix="reviewer_queue")

    st.divider()

    my_open_entries = repository.list_issues(
        author=name,
        include_closed=False,
        include_archived=False,
        project=current_project,
    )
    my_open = _entries_to_dicts(my_open_entries)
    st.subheader(f"개발대기목록 ({len(my_open)})")
    _render_card_grid(my_open[:9], key_prefix="reviewer_open")
    if len(my_open) > 9:
        st.caption(f"… 외 {len(my_open) - 9}건은 [개발목록]에서 확인")

    st.divider()

    # 전체 현황 (활성 항목 기준)
    st.subheader("전체 현황 (활성)")
    urgency_counts = _count_by(active_only, "urgency")

    st.markdown("**긴급도별**")
    u_cols = st.columns(3)
    for col, key in zip(u_cols, ["high", "normal", "low"]):
        with col:
            components.render_count_metric(
                URGENCY_LABELS[key],
                urgency_counts.get(key, 0),
                color=URGENCY_COLORS[key],
            )

    st.markdown("**상태별** ([보기]를 누르면 해당 목록으로 이동)")
    s_cols = st.columns(len(STATUS_NAV_KEYS))
    for col, key in zip(s_cols, STATUS_NAV_KEYS):
        with col:
            components.render_count_metric(
                STATUS_LABELS[key],
                status_counts.get(key, 0),
                color=STATUS_COLORS[key],
            )
            if st.button("보기", key=f"dash_status_{key}", width="stretch"):
                st.session_state["list_preset_status"] = key
                st.switch_page("pages/1_요청목록.py")

    sidebar_count = len(review_queue_entries)
    sidebar_label = f"검토 대기 {sidebar_count}건"

else:
    # ── 개발자 화면 ──────────────────────────────────────────────────────
    cta_col, _ = st.columns([1, 4])
    with cta_col:
        if st.button("내 큐 전체 보기", type="primary", width="stretch"):
            st.session_state["list_default_assignee"] = name
            st.switch_page("pages/1_요청목록.py")

    st.divider()

    # 개발중 — 내가 지금 작업 중인 항목 (가장 위에 우선 표시)
    in_progress_entries = repository.list_issues(
        status=Status.in_progress,
        include_archived=False,
        project=current_project,
    )
    in_progress_items = _entries_to_dicts(in_progress_entries)
    st.subheader(f"개발중 ({len(in_progress_items)})")
    st.caption("현재 작업 중인 항목")
    _render_card_grid(in_progress_items, key_prefix="dev_inprogress")

    st.divider()

    # 처리 큐 — 요청됨 + 추가확인필요 + 반려 (+ 레거시 재요청)
    _dev_queue_statuses = [
        Status.requested,
        Status.needs_recheck,
        Status.rejected,
        Status.reopened,  # 레거시 호환
    ]
    queue_entries: list = []
    for _s in _dev_queue_statuses:
        queue_entries.extend(
            repository.list_issues(
                status=_s,
                include_archived=False,
                project=current_project,
            )
        )
    queue_entries.sort(
        key=lambda e: e.model_dump(mode="json").get("updated_at") or "",
        reverse=True,
    )
    queue = _entries_to_dicts(queue_entries)

    st.subheader(f"처리 큐 ({len(queue)})")
    st.caption("요청됨 · 추가확인필요 · 반려 상태의 활성 항목")
    _render_card_grid(queue, key_prefix="dev_queue")

    st.divider()

    # 외부 대기 중
    api_entries = repository.list_issues(
        status=Status.api_check,
        include_archived=False,
        project=current_project,
    )
    api_check = _entries_to_dicts(api_entries)
    st.subheader(f"외부 대기 중 ({len(api_check)})")
    st.caption("외부 API 답변 대기 중인 항목")
    _render_card_grid(api_check, key_prefix="dev_api")

    st.divider()

    # 최근 내 활동 (audit.log)
    st.subheader("최근 내 활동")
    log_lines = tail_audit(50)
    my_lines = [line for line in log_lines if line.get("actor") == name][-5:]
    if not my_lines:
        st.info("아직 활동 기록이 없습니다.")
    else:
        for line in reversed(my_lines):
            ts = line.get("ts", "")
            action = line.get("action", "")
            item_id = line.get("item_id") or ""
            st.markdown(
                f"- **{components.humanize_dt(ts)}** · `{action}` · `#{item_id}`"
            )

    sidebar_count = len(queue_entries)
    sidebar_label = f"처리 대기 {sidebar_count}건"


# ---------------------------------------------------------------------------
# 사이드바 액션 큐 카운트 + 상태 바로가기
# ---------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    st.markdown(f"**내 액션 큐**: {sidebar_label}")

    st.divider()
    st.markdown("**상태 바로가기**")
    for _k in STATUS_NAV_KEYS:
        _cnt = status_counts.get(_k, 0)
        if st.button(
            f"{STATUS_LABELS[_k]} ({_cnt})",
            key=f"side_status_{_k}",
            width="stretch",
        ):
            st.session_state["list_preset_status"] = _k
            st.switch_page("pages/1_요청목록.py")
