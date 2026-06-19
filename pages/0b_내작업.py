"""내 작업 — '내 차례'인 항목만 모아 보는 개인 화면 (B 방식).

  - 담당자 처리 목록: 내가 담당자(assignee)이고 지금 '담당자가 처리할 상태'인 항목
  - 등록자 확인 목록: 내가 등록자(author)이고 지금 '등록자가 확인할 상태'인 항목

list_issues 로 dev 항목(미완료)만 가져와 상태로 후처리한다. 완료(closed)는 제외.
공통 처리(부트스트랩·사용자식별·프로젝트선택)는 app.py(라우터)가 수행한다.
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.models import Status
from ui import components

user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

# 비(非)상세 페이지 진입 = 상세보기 편집모드 정리 (stale 방지).
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

# '내 차례' 상태 집합 — 담당자(developer) / 등록자(reviewer) 가 행동할 단계.
# 개발사·담당팀 단계(vendor_*/team_*)는 '내 작업'에서 제외 — 각각 '개발사 요청'·
# '담당팀 요청' 페이지에서 관리한다.
_ASSIGNEE_TURN = {
    Status.assignee_request,
    Status.assignee_reviewing,
    Status.assignee_reviewed,
    Status.assignee_developing,
    Status.assignee_fixing,
}
_AUTHOR_TURN = {Status.author_request, Status.author_reviewing}

# '목록순' 정렬용 — 담당자 프로세스 단계 순서(확인요청→검토중→검토완료→개발→수정).
_PROCESS_ORDER = {
    Status.assignee_request: 0,
    Status.assignee_reviewing: 1,
    Status.assignee_reviewed: 2,
    Status.assignee_developing: 3,
    Status.assignee_fixing: 4,
}

if current_project:
    st.caption(f"{current_project} / 내 작업")
st.title("내 작업")
st.caption("내가 지금 **처리·확인해야 하는** 항목만 모았습니다.")

_all = repository.list_issues(project=current_project, include_closed=False)
_assignee_items = [
    e for e in _all if e.assignee == name and e.status in _ASSIGNEE_TURN
]
_author_items = [e for e in _all if e.author == name and e.status in _AUTHOR_TURN]


def _render_my(items: list, prefix: str) -> None:
    if not items:
        st.caption("지금 처리할 항목이 없습니다. 👍")
        return
    components.render_card_grid_css()
    cols_per_row = 4
    for row_start in range(0, len(items), cols_per_row):
        row = items[row_start : row_start + cols_per_row]
        col_objs = st.columns(cols_per_row)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                if components.render_card(
                    _item, key_prefix=f"{prefix}_{row_start}"
                ):
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/0b_내작업.py"
                    # 3번: 상세보기 [다음]이 '내 작업'의 이 목록 순서대로 이동하도록.
                    st.session_state["_detail_nav_ids"] = [e.id for e in items]
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")


_ah1, _ah2 = st.columns([3, 1], vertical_alignment="bottom")
with _ah1:
    st.subheader(f"📋 담당자 처리 목록 ({len(_assignee_items)})")
with _ah2:
    # 정렬을 헤더 같은 행 오른쪽 끝에.
    _asg_sort = st.selectbox(
        "정렬",
        ["최신순", "오래된순", "목록순"],
        key="mywork_asg_sort",
        label_visibility="collapsed",
    )
st.caption("내가 담당자이고, 지금 내가 처리할 차례인 항목 · 목록순 = 프로세스 단계 순서")

if _asg_sort == "최신순":
    _assignee_items.sort(key=lambda e: e.updated_at, reverse=True)
elif _asg_sort == "오래된순":
    _assignee_items.sort(key=lambda e: e.updated_at)
else:  # 목록순 — 프로세스 단계 순서대로
    _assignee_items.sort(key=lambda e: _PROCESS_ORDER.get(e.status, 99))
_render_my(_assignee_items, "mywork_asg")

st.divider()

st.subheader(f"✅ 등록자 확인 목록 ({len(_author_items)})")
st.caption("내가 등록자이고, 지금 내가 확인할 차례인 항목")
_render_my(_author_items, "mywork_auth")
