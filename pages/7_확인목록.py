"""확인목록 — 프로젝트의 기준이 되는 항목들 (kind=criteria).

확인요청목록에서 [확인목록으로] 보낸 항목들이 모인다. 자체 등록폼은 없고,
개발목록처럼 카드로 확인한다. (10번)
"""

from __future__ import annotations

import streamlit as st

from core import repository

user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

# 비(非)상세 페이지 진입 = 상세보기 편집모드 정리 (stale 방지).
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

if current_project:
    st.caption(f"{current_project} / 확인목록")
st.title("확인목록")
st.caption(
    "프로젝트의 기준이 되는 항목들입니다. "
    "확인요청목록에서 **[확인목록으로]** 보낸 항목이 모입니다."
)

items = repository.list_issues(
    kind="criteria",
    project=current_project,
    include_closed=True,
    include_archived=False,
)
st.subheader(f"기준 항목 ({len(items)})")

if not items:
    st.caption("확인목록 항목이 없습니다. 확인요청목록에서 [확인목록으로] 보내세요.")
else:
    COLS_PER_ROW = 4
    for row_start in range(0, len(items), COLS_PER_ROW):
        row = items[row_start : row_start + COLS_PER_ROW]
        col_objs = st.columns(COLS_PER_ROW)
        for col, entry in zip(col_objs, row):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{entry.title}**")
                    if entry.description_preview:
                        st.caption(entry.description_preview[:100])
                    _created = str(entry.created_at)[:10]
                    st.caption(
                        f"👤 {entry.author} · 📷 {entry.images_count}장 · {_created}"
                    )
                    if st.button(
                        "열기", key=f"crit_open_{entry.id}", width="stretch"
                    ):
                        st.session_state["_detail_item_id"] = entry.id
                        st.session_state["_detail_origin"] = "pages/7_확인목록.py"
                        st.query_params["id"] = entry.id
                        st.switch_page("pages/3_상세보기.py")
