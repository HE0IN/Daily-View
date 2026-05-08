"""요청 목록 페이지 — docs/03_ui_design.md 3.4 절.

필터(긴급도/상태/담당자/검색/정렬/카테고리) + 카드 그리드(4×4 = 16) 페이지네이션.
session_state 로 현재 페이지 추적, 필터 변경 시 1페이지로 리셋.
"""

from __future__ import annotations

import os

import pandas as pd
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

name: str = user["name"]
role: str = user.get("role", "reviewer")

# 프로젝트 선택기는 사용자 이름을 받아서 그 사람이 참여한 프로젝트만 노출
current_project: str | None = render_project_selector(user_name=name)


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

# 카테고리 대분류 옵션 (현재 프로젝트로 좁힘).
# repository.list_categories 의 시그니처가 project 인자를 받도록 갱신될 예정 —
# 구버전(인자 없음)에서도 동작하도록 try/except 로 폴백.
try:
    cat_tree = repository.list_categories(project=current_project)
except TypeError:
    cat_tree = repository.list_categories()
except Exception:  # noqa: BLE001
    cat_tree = {}
category_l1_options = ["(전체)"] + sorted(cat_tree.keys())

f6, f7 = st.columns([1.5, 4.5])
with f6:
    # 직전에 선택된 값이 옵션에서 사라졌으면(프로젝트 전환 등) 기본값으로 복귀.
    if (
        st.session_state.get("list_category_l1")
        and st.session_state["list_category_l1"] not in category_l1_options
    ):
        st.session_state["list_category_l1"] = "(전체)"
    category_l1_choice = st.selectbox(
        "카테고리(대분류)",
        options=category_l1_options,
        key="list_category_l1",
    )
with f7:
    pass  # 향후 다른 필터용 여유 공간

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

# 보기 모드 토글 — 카드/테이블
view_mode = st.radio(
    "보기",
    options=["카드", "테이블"],
    horizontal=True,
    key="list_view_mode",
)

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
    category_l1_choice,
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
    # 카테고리 대분류 필터 (list_issues 가 카테고리 인자를 받지 않으므로 후처리).
    if category_l1_choice and category_l1_choice != "(전체)":
        entries = [
            e for e in entries if (e.category_l1 or "") == category_l1_choice
        ]

    items = [e.model_dump(mode="json") for e in entries]

    # 정렬
    if sort_choice == "긴급도순":
        # 4 단계: critical(긴급) > high(상) > normal(중) > low(하).
        urgency_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
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

def _render_card_view(page_items_local: list[dict], current_page_local: int) -> None:
    """카드 그리드 (4열) 렌더링."""
    # 같은 행 카드들이 가장 긴 카드 높이로 stretch — 한 번만 주입.
    components.render_card_grid_css()
    cols_per_row = 4  # 카드를 컴팩트하게 줄였으니 한 행에 더 많이.
    for row_start in range(0, len(page_items_local), cols_per_row):
        row = page_items_local[row_start : row_start + cols_per_row]
        col_objs = st.columns(cols_per_row)
        for col, item in zip(col_objs, row):
            with col:
                # 삭제(보관) 처리된 항목임을 카드 위에 표시
                if item.get("archived"):
                    st.caption("🗑 삭제됨")
                clicked = components.render_card(
                    item,
                    key_prefix=f"list_p{current_page_local}_r{row_start}",
                )
                if clicked:
                    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
                    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
                    _iid = item.get("id", "")
                    st.session_state["_detail_item_id"] = _iid
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _render_table_view(page_items_local: list[dict]) -> None:
    """st.dataframe 으로 테이블 표시 + 항목 선택 → 상세보기 이동."""
    rows = []
    for item in page_items_local:
        urgency = item.get("urgency", "normal")
        urgency_label = URGENCY_LABELS.get(urgency, urgency)
        status_label = STATUS_LABELS.get(item.get("status", ""), "")
        desc_preview = (item.get("description_preview") or "")[:80]
        rows.append({
            "긴급도": urgency_label,
            "제목": item.get("title", ""),
            "담당자": item.get("assignee") or "(미배정)",
            "상태": status_label,
            "비고": desc_preview,
            "등록": components.humanize_dt(item.get("created_at", "")),
            "ID": item.get("id", ""),
        })
    df = pd.DataFrame(rows)

    # 긴급도별 row 배경색 (Styler.apply 로 행 단위 적용).
    def _row_style(row: pd.Series) -> list[str]:
        urg_label = row.get("긴급도", "")
        bg = ""
        if urg_label == "긴급":
            bg = "background-color: #FEE2E2;"  # 빨강 옅음
        elif urg_label == "상":
            bg = "background-color: #FEF3C7;"  # 주황 옅음
        elif urg_label == "하":
            bg = "background-color: #DCFCE7;"  # 초록 옅음
        return [bg] * len(row)

    styler = df.style.apply(_row_style, axis=1)
    st.dataframe(styler, width="stretch", hide_index=True)

    # 항목 열기 — selectbox + 버튼 (st.dataframe 자체는 클릭 셀 불가).
    open_col1, open_col2 = st.columns([4, 1])
    with open_col1:
        target_id = st.selectbox(
            "열어볼 항목",
            options=[item.get("id") for item in page_items_local],
            format_func=lambda i: next(
                (it.get("title", i) for it in page_items_local if it.get("id") == i),
                i,
            ),
            key="list_table_open_target",
        )
    with open_col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)  # 라벨 높이 맞추기
        if st.button("상세보기", key="list_table_open_btn", width="stretch"):
            st.session_state["_detail_item_id"] = target_id
            st.query_params["id"] = target_id
            st.switch_page("pages/3_상세보기.py")


if total == 0:
    st.info("조건에 맞는 항목이 없습니다.")
elif view_mode == "테이블":
    _render_table_view(page_items)
else:
    _render_card_view(page_items, current_page)

# 페이지 컨트롤
if total > 0:
    st.divider()
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        prev_disabled = current_page <= 1
        if st.button(
            "← 이전", disabled=prev_disabled, key="list_prev", width="stretch"
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
            "다음 →", disabled=next_disabled, key="list_next", width="stretch"
        ):
            st.session_state["list_page"] = current_page + 1
            st.rerun()
