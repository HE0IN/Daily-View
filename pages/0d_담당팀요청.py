"""담당팀 요청 — 담당팀 단계 항목 모아보기 + PDF 출력 (개발사 요청과 동일 구조).

담당팀 단계 3가지(담당팀요청대기 / 담당팀확인중 / 담당팀회신확인중)를 섹션으로
나눠 보여주고, 카드를 선택해 PDF 로 뽑아 담당팀에 송부한다. 개발사 요청 페이지의
담당팀 버전이다.
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
    st.caption(f"{current_project} / 담당팀 요청")
st.title("담당팀 요청")
st.caption("담당팀 단계 항목을 모아 봅니다. 카드를 선택(체크)해 PDF 로 뽑아 송부하세요.")

_all = repository.list_issues(project=current_project, include_closed=False)
_wait = [e for e in _all if e.status == Status.team_wait]
_req = [e for e in _all if e.status == Status.team_request]
_reply = [e for e in _all if e.status == Status.team_reply]
_team_all = _wait + _req + _reply

# 6번: 상세보기 [다음 →] 이 이 목록(대기→확인중→회신확인중) 순서대로 이동하도록.
st.session_state["_detail_nav_ids"] = [e.id for e in _team_all]

# ---------------------------------------------------------------------------
# PDF 출력 (선택 / 전체) — 담당팀 송부용. A4 페이지당 항목 1개.
# ---------------------------------------------------------------------------
_sel_ids = [e.id for e in _team_all if st.session_state.get(f"tsel_{e.id}")]
with st.container(border=True):
    _pc1, _pc2, _pc3 = st.columns([2, 2, 2])
    with _pc1:
        st.markdown(f"**📄 PDF 출력** · 선택 {len(_sel_ids)}건")
    with _pc2:
        if st.button(
            "선택 PDF 만들기",
            key="team_sel_pdf",
            disabled=not _sel_ids,
            width="stretch",
        ):
            from core import pdf_export

            _iss = [repository.get_issue(_i) for _i in _sel_ids]
            st.session_state["_team_pdf"] = pdf_export.build_issues_pdf(_iss)
            st.toast(f"{len(_iss)}건 PDF 생성 완료", icon="📄")
    with _pc3:
        if st.button(
            f"전체 PDF ({len(_team_all)}건)",
            key="team_all_pdf",
            disabled=not _team_all,
            width="stretch",
        ):
            from core import pdf_export

            _iss = [repository.get_issue(e.id) for e in _team_all]
            st.session_state["_team_pdf"] = pdf_export.build_issues_pdf(_iss)
            st.toast(f"{len(_iss)}건 PDF 생성 완료", icon="📄")
    if st.session_state.get("_team_pdf"):
        st.download_button(
            "⬇ PDF 다운로드 (담당팀요청)",
            data=st.session_state["_team_pdf"],
            file_name="담당팀요청.pdf",
            mime="application/pdf",
            key="team_pdf_dl",
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
                    checkbox=("선택", f"tsel_{entry.id}"),
                )
                if _res["open"]:
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/0d_담당팀요청.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")


st.divider()
_render_section("📤 담당팀요청대기", _wait, "tw")
st.divider()
_render_section("🔄 담당팀확인중", _req, "tr")
st.divider()
_render_section("📥 담당팀회신확인중", _reply, "tp")
