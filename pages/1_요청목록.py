"""요청 목록 페이지 — docs/03_ui_design.md 3.4 절.

필터(긴급도/상태/담당자/검색/정렬) + 카드 그리드(3×4 = 12) 페이지네이션.
session_state 로 현재 페이지 추적, 필터 변경 시 1페이지로 리셋.
"""

from __future__ import annotations

import os

import streamlit as st

from core import paths, repository
from core.models import Status, Urgency
from ui import components
from ui.auth import get_or_init_user, render_project_selector, require_user
from ui.theme import STATUS_LABELS, URGENCY_LABELS

# 자동 새로고침 (M3). 미설치/0 이면 비활성.
try:  # pragma: no cover - 환경 의존
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
except Exception:  # noqa: BLE001
    _st_autorefresh = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 페이지 설정 + 부트스트랩
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="요청목록 — Daily View",
    layout="wide",
    initial_sidebar_state="expanded",
)

paths.ensure_data_dirs()

# 자동 새로고침 (다른 사용자 변경 반영용; 환경변수 0 이면 비활성)
if _st_autorefresh is not None:
    try:
        _refresh_sec = int(os.environ.get("AUTO_REFRESH_SEC", "30"))
    except ValueError:
        _refresh_sec = 30
    if _refresh_sec > 0:
        _st_autorefresh(interval=_refresh_sec * 1000, key="list_auto_refresh")

# 사이드바 사용자 위젯 + 가드
get_or_init_user()
user = require_user()
current_project: str | None = render_project_selector()

name: str = user["name"]
role: str = user.get("role", "reviewer")


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

if current_project:
    st.title(f"요청목록 — {current_project}")
else:
    st.title("요청목록")


# ---------------------------------------------------------------------------
# 필터 옵션 준비 (담당자 후보 = 인덱스 전체에서 unique)
# ---------------------------------------------------------------------------

# 한 번 전체 로드해서 담당자 옵션 추출 (필터링은 아래에서 다시).
# 현재 프로젝트가 선택돼 있으면 그 프로젝트에 등장한 담당자만 후보로 노출.
all_entries_for_options = repository.list_issues(
    include_archived=True, project=current_project
)
assignee_set: set[str] = {
    e.assignee for e in all_entries_for_options if e.assignee
}
assignee_options = ["(전체)", "(미할당)"] + sorted(assignee_set)

# 역할별 기본 담당자 (개발자는 자기 자신, 검토자는 전체).
default_assignee = "(전체)"
# 대시보드 [내 큐 전체 보기] CTA 에서 넘긴 값이 있으면 우선.
preset_assignee = st.session_state.pop("list_default_assignee", None)
if preset_assignee and preset_assignee in assignee_options:
    default_assignee = preset_assignee
elif role == "developer" and name in assignee_set:
    default_assignee = name

# 필터 변경 시 페이지를 1로 리셋하기 위해 직전 값과 비교.
prev_filter_key = st.session_state.get("list_prev_filter_key")


# ---------------------------------------------------------------------------
# 필터 UI
# ---------------------------------------------------------------------------

f1, f2, f3, f4, f5 = st.columns([1, 2, 1.4, 2.4, 1.2])

with f1:
    urgency_choice = st.selectbox(
        "긴급도",
        options=["(전체)"] + [u.value for u in Urgency],
        format_func=lambda v: "전체" if v == "(전체)" else URGENCY_LABELS.get(v, v),
        key="list_urgency",
    )

with f2:
    status_choice: list[str] = st.multiselect(
        "상태 (다중 선택)",
        options=[s.value for s in Status],
        format_func=lambda v: STATUS_LABELS.get(v, v),
        key="list_status",
        help="비어 있으면 전체",
    )

with f3:
    assignee_choice = st.selectbox(
        "담당자",
        options=assignee_options,
        index=assignee_options.index(default_assignee)
        if default_assignee in assignee_options
        else 0,
        key="list_assignee",
    )

with f4:
    search_query = st.text_input(
        "검색", placeholder="제목 또는 태그", key="list_search"
    )

with f5:
    sort_choice = st.selectbox(
        "정렬",
        options=["최신순", "긴급도순", "상태순"],
        key="list_sort",
    )

opt_col1, opt_col2 = st.columns([1, 1])
with opt_col1:
    include_closed = st.checkbox(
        "완료된 작업 포함",
        value=False,
        key="list_inc_closed",
        help="검토완료(closed) 처리된 항목까지 함께 표시합니다.",
    )
with opt_col2:
    include_archived = st.checkbox(
        "삭제(보관)된 항목 포함",
        value=False,
        key="list_inc_archived",
        help="삭제 처리한 항목입니다.",
    )
    st.caption("삭제 처리한 항목입니다")

# 페이지네이션 리셋: 필터 키가 바뀌면 page=1
filter_key = (
    urgency_choice,
    tuple(status_choice),
    assignee_choice,
    search_query,
    sort_choice,
    include_closed,
    include_archived,
    current_project,
)
if prev_filter_key is not None and prev_filter_key != filter_key:
    st.session_state["list_page"] = 1
st.session_state["list_prev_filter_key"] = filter_key


# ---------------------------------------------------------------------------
# 데이터 조회 (서버측 필터 가능한 항목만 repository 에 위임,
# 나머지는 클라이언트측에서 추가 처리)
# ---------------------------------------------------------------------------


def _fetch_entries() -> list[dict]:
    """필터 조건에 따라 list_issues 를 호출하고 dict 리스트로 반환."""
    repo_kwargs: dict = {
        "include_archived": include_archived,
        "include_closed": include_closed,
        "search": search_query.strip() or None,
        "project": current_project,
    }

    # 긴급도
    if urgency_choice != "(전체)":
        repo_kwargs["urgency"] = urgency_choice

    # 담당자: repository.list_issues 는 assignee=None 을 "필터 없음"으로 해석하므로
    # 미할당 전용 필터는 후처리에서 적용한다.
    if assignee_choice == "(미할당)":
        unassigned_only = True
    elif assignee_choice == "(전체)":
        unassigned_only = False
    else:
        repo_kwargs["assignee"] = assignee_choice
        unassigned_only = False

    # 상태: 단일이면 repository 인자, 다중이면 후처리.
    status_filter_post: set[str] | None = None
    if len(status_choice) == 1:
        repo_kwargs["status"] = status_choice[0]
    elif len(status_choice) > 1:
        status_filter_post = set(status_choice)

    entries = repository.list_issues(**repo_kwargs)

    # 후처리 필터
    if unassigned_only:
        entries = [e for e in entries if not e.assignee]
    if status_filter_post is not None:
        entries = [
            e
            for e in entries
            if (e.status.value if hasattr(e.status, "value") else str(e.status))
            in status_filter_post
        ]

    items = [e.model_dump(mode="json") for e in entries]

    # 정렬
    if sort_choice == "긴급도순":
        urgency_order = {"high": 0, "normal": 1, "low": 2}
        items.sort(
            key=lambda d: (
                urgency_order.get(d.get("urgency", ""), 9),
                d.get("updated_at") or "",
            )
        )
    elif sort_choice == "상태순":
        status_order = {
            "requested": 0,
            "reopened": 1,
            "in_progress": 2,
            "api_check": 3,
            "done": 4,
            "reviewing": 5,
            "closed": 6,
        }
        items.sort(
            key=lambda d: (
                status_order.get(d.get("status", ""), 9),
                d.get("updated_at") or "",
            )
        )
    # 기본(최신순)은 list_issues 가 이미 updated_at desc 정렬.
    return items


items = _fetch_entries()
total = len(items)


# ---------------------------------------------------------------------------
# 페이지네이션
# ---------------------------------------------------------------------------

PAGE_SIZE = 16  # 4 columns × 4 rows
total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
st.session_state.setdefault("list_page", 1)
current_page = min(max(1, int(st.session_state["list_page"])), total_pages)
st.session_state["list_page"] = current_page

start = (current_page - 1) * PAGE_SIZE
end = start + PAGE_SIZE
page_items = items[start:end]


# ---------------------------------------------------------------------------
# 결과 카운트 + 본문
# ---------------------------------------------------------------------------

st.caption(f"총 {total}건 · {current_page}/{total_pages} 페이지")

if total == 0:
    st.info("조건에 맞는 항목이 없습니다.")
else:
    cols_per_row = 4  # 카드를 컴팩트하게 줄였으니 한 행에 더 많이.
    for row_start in range(0, len(page_items), cols_per_row):
        row = page_items[row_start : row_start + cols_per_row]
        col_objs = st.columns(cols_per_row)
        for col, item in zip(col_objs, row):
            with col:
                # 삭제(보관) 처리된 항목임을 카드 위에 표시
                if item.get("archived"):
                    st.caption("🗑 삭제됨")
                clicked = components.render_card(
                    item,
                    key_prefix=f"list_p{current_page}_r{row_start}",
                )
                if clicked:
                    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
                    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
                    _iid = item.get("id", "")
                    st.session_state["_detail_item_id"] = _iid
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")

# 페이지 컨트롤
if total > 0:
    st.divider()
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        prev_disabled = current_page <= 1
        if st.button(
            "← 이전", disabled=prev_disabled, key="list_prev", use_container_width=True
        ):
            st.session_state["list_page"] = current_page - 1
            st.rerun()
    with pc2:
        st.markdown(
            f"<div style='text-align:center;color:#6B7280;'>"
            f"{current_page} / {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with pc3:
        next_disabled = current_page >= total_pages
        if st.button(
            "다음 →", disabled=next_disabled, key="list_next", use_container_width=True
        ):
            st.session_state["list_page"] = current_page + 1
            st.rerun()
