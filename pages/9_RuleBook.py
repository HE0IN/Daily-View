"""RuleBook — 확정된 규칙(rule_status=confirmed) 항목들의 카테고리별 뷰.

Temp(criteria) 항목 중 '✅ 확정규칙'으로 표시된 것들을 카테고리(대분류)별로
묶어 보여준다. 항목은 Temp 에 그대로 있고 여기서는 '비춰지기만' 한다
(이동/복사 없음 — docs/09 D3). 성격 라벨을 되돌리면 여기서도 사라진다.
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
    st.caption(f"{current_project} / RuleBook")
st.title("RuleBook")
st.caption(
    "확정된 규칙(✅ 확정규칙)을 카테고리별로 모아 봅니다. **Temp** 에서 항목의 "
    "성격을 '확정규칙'으로 바꾸면 여기에 나타납니다. (항목은 Temp 에 그대로 있습니다.)"
)

items = [
    e
    for e in repository.list_issues(
        kind="criteria",
        project=current_project,
        include_closed=True,
        include_archived=False,
    )
    if (getattr(e, "rule_status", "unsorted") or "unsorted") == "confirmed"
]

st.subheader(f"확정규칙 ({len(items)})")

# 상세보기 [다음 →] 용 — 이 목록 순서대로 이동.
st.session_state["_detail_nav_ids"] = [e.id for e in items]

if not items:
    st.info(
        "아직 확정규칙이 없습니다. **Temp** 에서 항목을 열어 성격을 "
        "'✅ 확정규칙'으로 바꾸면 여기에 모입니다."
    )
    st.stop()

# 카테고리(대분류)별 그룹핑. 없으면 맨 뒤 '(카테고리 없음)'.
_NONE = "(카테고리 없음)"
groups: dict[str, list] = {}
for e in items:
    groups.setdefault(e.category_l1 or _NONE, []).append(e)

components.render_card_grid_css()
COLS_PER_ROW = 4

for cat in sorted(groups, key=lambda k: (k == _NONE, k)):
    grp = groups[cat]
    st.markdown(f"#### {cat} ({len(grp)})")
    for row_start in range(0, len(grp), COLS_PER_ROW):
        row = grp[row_start : row_start + COLS_PER_ROW]
        col_objs = st.columns(COLS_PER_ROW)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                if components.render_card(_item, key_prefix=f"rb_{cat}_{row_start}"):
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/9_RuleBook.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")
