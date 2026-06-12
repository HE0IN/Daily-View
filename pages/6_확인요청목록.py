"""확인요청목록 — 확인 요청(kind=unimplemented)으로 등록된 항목들의 카드 목록.

각 항목에서 두 갈래로 보낼 수 있다:
  ① 새 요청 등록 (개발목록으로 승격) — promote_id 로 새요청등록을 prefill
  ② 확인목록 (프로젝트 기준으로 이동) — promote_to_criteria 로 kind 변경

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

if current_project:
    st.caption(f"{current_project} / 확인요청목록")
st.title("확인요청목록")
st.caption(
    "확인 요청으로 등록된 항목들입니다. 개발이 필요하면 **[개발 요청]**, "
    "확정 보류면 **[Temp로]** 보내세요."
)

# 5번: 확인요청(확인대기) 항목은 담당자가 없어야 한다 — 남아 있으면 해제.
# 1번: 확인대기가 아닌(담당자확인요청 등으로 보내졌으나 kind 가 안 바뀐) 옛 항목은
#      개발목록(dev)으로 정규화해 확인요청목록에서 빠지게 한다.
for _e in repository.list_issues(
    kind="unimplemented",
    project=current_project,
    include_closed=True,
    include_archived=False,
):
    try:
        if _e.status != Status.pending_check:
            repository.send_pending_to_dev(_e.id, name)
        elif _e.assignee:
            repository.clear_assignee(_e.id, name)
    except Exception:  # noqa: BLE001
        pass

items = repository.list_issues(
    kind="unimplemented",
    project=current_project,
    include_closed=True,
    include_archived=False,
)
st.subheader(f"확인요청 ({len(items)})")

if not items:
    st.caption("확인요청 항목이 없습니다. '확인 요청' 메뉴에서 등록하세요.")
else:
    # 4번: 개발목록처럼 썸네일 카드(render_card)로 — 높이 통일 + 이미지 표시.
    components.render_card_grid_css()
    COLS_PER_ROW = 4
    for row_start in range(0, len(items), COLS_PER_ROW):
        row = items[row_start : row_start + COLS_PER_ROW]
        col_objs = st.columns(COLS_PER_ROW)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                # 2번: [개발 요청]/[확인목록으로] 버튼을 카드 안으로.
                _res = components.render_card(
                    _item,
                    key_prefix=f"cr_{row_start}",
                    extra_buttons=[("개발 요청", "dev"), ("Temp로", "temp")],
                    buttons_inline=True,
                )
                if _res["open"]:
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/6_확인요청목록.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")
                if _res["actions"].get("dev"):
                    st.session_state["promote_id"] = entry.id
                    st.switch_page("pages/2_새요청등록.py")
                if _res["actions"].get("temp"):
                    try:
                        repository.promote_to_criteria(entry.id, name)
                        st.toast("Temp 로 이동했습니다", icon="✅")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"이동 실패: {exc}")
