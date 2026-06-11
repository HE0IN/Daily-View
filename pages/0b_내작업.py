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
# 개발사 단계(vendor_*)는 '내 작업'에서 제외 — 별도 '개발사 요청' 페이지에서 관리.
_ASSIGNEE_TURN = {
    Status.assignee_request,
    Status.assignee_reviewing,
    Status.assignee_reviewed,
    Status.assignee_developing,
    Status.assignee_fixing,
}
_AUTHOR_TURN = {Status.author_request, Status.author_reviewing}

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
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")


st.subheader(f"📋 담당자 처리 목록 ({len(_assignee_items)})")
st.caption("내가 담당자이고, 지금 내가 처리할 차례인 항목")
_render_my(_assignee_items, "mywork_asg")

st.divider()

st.subheader(f"✅ 등록자 확인 목록 ({len(_author_items)})")
st.caption("내가 등록자이고, 지금 내가 확인할 차례인 항목")
_render_my(_author_items, "mywork_auth")
