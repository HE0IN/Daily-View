"""확인목록 — 프로젝트의 기준이 되는 항목들 (kind=criteria).

확인요청목록에서 [확인목록으로] 보낸 항목들이 모인다. 자체 등록폼은 없고,
개발목록처럼 카드로 확인한다. (10번)
"""

from __future__ import annotations

import streamlit as st

from core import repository
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
    # 6번: 개발목록처럼 썸네일 카드(render_card)로 — 높이 통일 + 이미지 표시.
    components.render_card_grid_css()
    COLS_PER_ROW = 4
    for row_start in range(0, len(items), COLS_PER_ROW):
        row = items[row_start : row_start + COLS_PER_ROW]
        col_objs = st.columns(COLS_PER_ROW)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                # 1번: 확인목록 → 확인요청목록 되돌리기 버튼을 카드 안에.
                _res = components.render_card(
                    _item,
                    key_prefix=f"crit_{row_start}",
                    extra_buttons=[("확인요청목록으로", "revert")],
                )
                if _res["open"]:
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/7_확인목록.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")
                if _res["actions"].get("revert"):
                    try:
                        repository.revert_criteria_to_request(entry.id, name)
                        st.toast("확인요청목록으로 되돌렸습니다", icon="↩️")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"되돌리기 실패: {exc}")
