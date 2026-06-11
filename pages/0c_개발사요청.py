"""개발사 요청 — 개발사 단계 항목 모아보기 + PDF 출력 (개발목록에서 이관).

개발사 단계 3가지(개발사요청대기 / 개발사확인중 / 개발사회신확인중)를 섹션으로
나눠 보여주고, 카드를 선택해 PDF 로 뽑아 개발사에 송부한다. PDF 출력은 이 페이지
에서만 한다 (개발목록은 단계 전환 전용).
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

# 비(非)상세 페이지 진입 = 상세보기 편집모드 정리.
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

if current_project:
    st.caption(f"{current_project} / 개발사 요청")
st.title("개발사 요청")
st.caption("개발사 단계 항목을 모아 봅니다. 카드를 선택(체크)해 PDF 로 뽑아 송부하세요.")

_all = repository.list_issues(project=current_project, include_closed=False)
_wait = [e for e in _all if e.status == Status.vendor_wait]
_req = [e for e in _all if e.status == Status.vendor_request]
_reply = [e for e in _all if e.status == Status.vendor_reply]
_vendor_all = _wait + _req + _reply

# ---------------------------------------------------------------------------
# PDF 출력 (선택 / 전체) — 개발사 API 요청 송부용. A4 페이지당 항목 1개.
# ---------------------------------------------------------------------------
_sel_ids = [e.id for e in _vendor_all if st.session_state.get(f"vsel_{e.id}")]
with st.container(border=True):
    _pc1, _pc2, _pc3 = st.columns([2, 2, 2])
    with _pc1:
        st.markdown(f"**📄 PDF 출력** · 선택 {len(_sel_ids)}건")
    with _pc2:
        if st.button(
            "선택 PDF 만들기",
            key="vendor_sel_pdf",
            disabled=not _sel_ids,
            width="stretch",
        ):
            from core import pdf_export

            _iss = [repository.get_issue(_i) for _i in _sel_ids]
            st.session_state["_vendor_pdf"] = pdf_export.build_issues_pdf(_iss)
            st.toast(f"{len(_iss)}건 PDF 생성 완료", icon="📄")
    with _pc3:
        if st.button(
            f"전체 PDF ({len(_vendor_all)}건)",
            key="vendor_all_pdf",
            disabled=not _vendor_all,
            width="stretch",
        ):
            from core import pdf_export

            _iss = [repository.get_issue(e.id) for e in _vendor_all]
            st.session_state["_vendor_pdf"] = pdf_export.build_issues_pdf(_iss)
            st.toast(f"{len(_iss)}건 PDF 생성 완료", icon="📄")
    if st.session_state.get("_vendor_pdf"):
        st.download_button(
            "⬇ PDF 다운로드 (개발사요청)",
            data=st.session_state["_vendor_pdf"],
            file_name="개발사요청.pdf",
            mime="application/pdf",
            key="vendor_pdf_dl",
            width="stretch",
        )


def _render_section(title: str, items: list, prefix: str) -> None:
    st.subheader(f"{title} ({len(items)})")
    if not items:
        st.caption("항목이 없습니다.")
        return
    components.render_card_grid_css()
    cols_per_row = 4
    for row_start in range(0, len(items), cols_per_row):
        row = items[row_start : row_start + cols_per_row]
        col_objs = st.columns(cols_per_row)
        for col, entry in zip(col_objs, row):
            with col:
                _item = entry.model_dump(mode="json")
                _res = components.render_card(
                    _item,
                    key_prefix=f"{prefix}_{row_start}",
                    checkbox=("선택", f"vsel_{entry.id}"),
                )
                if _res["open"]:
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/0c_개발사요청.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")


st.divider()
_render_section("📤 개발사요청대기", _wait, "vw")
st.divider()
_render_section("🔄 개발사확인중", _req, "vr")
st.divider()
_render_section("📥 개발사회신확인중", _reply, "vp")
