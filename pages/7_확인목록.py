"""확인목록 — 프로젝트의 기준이 되는 항목들 (kind=criteria).

확인요청목록에서 [확인목록으로] 보낸 항목들이 모인다. 자체 등록폼은 없고,
개발목록처럼 카드로 확인한다. (10번)

각 항목은 성격(정리) 라벨(rule_status)을 가진다 (docs/09):
  ⬜ 미분류 / 🔍 확인필요 / ✅ 확정규칙.
확정규칙은 RuleBook 에도 노출되며, 여기서는 기본으로 숨긴다(정리 대상만 보임).
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.models import Status
from core.workflow import RULE_STATUS_COLORS, rule_status_label
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
    st.caption(f"{current_project} / Temp")
st.title("Temp")
st.caption(
    "확정 보류(Temp) 항목들입니다. 확인요청목록에서 **[Temp로]** 보낸 항목이 모입니다. "
    "각 항목의 **성격 라벨**(⬜ 미분류 · 🔍 확인필요 · ✅ 확정규칙)로 정리하며, "
    "**✅ 확정규칙**은 RuleBook 에 노출되고 여기선 기본으로 숨겨집니다."
)

# 옛 데이터 정리: 확인대기(pending_check) criteria 는 확인요청목록 소속이라
# 되돌리고, Temp 항목에 담당자가 남아 있으면 해제한다 (5번).
for _e in repository.list_issues(
    kind="criteria",
    project=current_project,
    include_closed=True,
    include_archived=False,
):
    try:
        if _e.status == Status.pending_check:
            repository.revert_criteria_to_request(_e.id, name)
        elif _e.assignee:
            repository.clear_assignee(_e.id, name)
    except Exception:  # noqa: BLE001
        pass

items = repository.list_issues(
    kind="criteria",
    project=current_project,
    include_closed=True,
    include_archived=False,
)


def _rs(entry) -> str:
    return getattr(entry, "rule_status", "unsorted") or "unsorted"


# 성격 라벨별 카운트 (정리 진행도).
_counts = {"unsorted": 0, "needs_check": 0, "confirmed": 0}
for _e in items:
    _counts[_rs(_e)] = _counts.get(_rs(_e), 0) + 1
_n_todo = _counts["unsorted"] + _counts["needs_check"]

# 성격 라벨 필터 — 기본 '정리 대상'(확정규칙 숨김).
_FILTERS = ["todo", "unsorted", "needs_check", "confirmed", "all"]
_FILTER_LABELS = {
    "todo": f"정리 대상 ({_n_todo})",
    "unsorted": f"⬜ 미분류 ({_counts['unsorted']})",
    "needs_check": f"🔍 확인필요 ({_counts['needs_check']})",
    "confirmed": f"✅ 확정규칙 ({_counts['confirmed']})",
    "all": f"전체 ({len(items)})",
}
_sel = st.radio(
    "보기",
    _FILTERS,
    index=0,
    horizontal=True,
    format_func=lambda k: _FILTER_LABELS[k],
    key="temp_rule_filter",
    label_visibility="collapsed",
)


def _match(rs: str) -> bool:
    if _sel == "all":
        return True
    if _sel == "todo":
        return rs != "confirmed"
    return rs == _sel


shown = [e for e in items if _match(_rs(e))]

st.subheader(f"기준 항목 ({len(shown)})")

# 6번: 상세보기 [다음 →] 용 — 현재 필터로 보이는 순서대로 이동.
st.session_state["_detail_nav_ids"] = [e.id for e in shown]

if not items:
    st.caption("Temp 항목이 없습니다. 확인요청목록에서 [Temp로] 보내세요.")
elif not shown:
    st.caption("이 필터에 해당하는 항목이 없습니다. 다른 보기를 선택하세요.")
else:
    # 6번: 개발목록처럼 썸네일 카드(render_card)로 — 높이 통일 + 이미지 표시.
    components.render_card_grid_css()
    COLS_PER_ROW = 4
    for row_start in range(0, len(shown), COLS_PER_ROW):
        row = shown[row_start : row_start + COLS_PER_ROW]
        col_objs = st.columns(COLS_PER_ROW)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                _rsv = _rs(entry)
                _badge = components.render_badge(
                    rule_status_label(_rsv, icon=False),
                    RULE_STATUS_COLORS.get(_rsv, "#9CA3AF"),
                )
                # R1: Temp → 확인대기(확인요청목록) 되돌리기. revert_criteria_to_request
                #     가 kind=unimplemented·status=확인대기 로 보내므로 라벨도 '확인대기로'.
                _res = components.render_card(
                    _item,
                    key_prefix=f"crit_{row_start}",
                    extra_buttons=[("확인대기로", "revert")],
                    top_badge_html=_badge,
                )
                if _res["open"]:
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/7_확인목록.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")
                if _res["actions"].get("revert"):
                    try:
                        repository.revert_criteria_to_request(entry.id, name)
                        st.toast("확인대기로 보냈습니다 (확인요청목록)", icon="↩️")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"되돌리기 실패: {exc}")
