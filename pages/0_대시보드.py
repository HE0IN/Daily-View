"""대시보드 — 전체 현황 (역할 무관 공통 화면).

상태별 섹션:
    전체 개발 목록 / 담당자 처리 / 개발사 / 등록자 확인 / 완료 / 삭제

공통 처리(부트스트랩·사용자식별·프로젝트선택)는 진입점 app.py(라우터)가 수행하고,
이 페이지는 session_state 의 user / _current_project 를 읽어 사용한다.
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.models import Status
from ui import components
from ui.theme import STATUS_LABELS

user = st.session_state.get("user")
if not user:
    st.stop()

# 상세보기 인라인 편집모드 stale 정리 — 비(非)상세 페이지에 들어온 것은
# '편집을 끝냈거나 포기한 것'으로 간주해 모든 _edit_mode_* 를 끈다.
# (완료를 안 누르고 이동했다가 재진입 시 계속 편집중이던 문제 해결)
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

components.render_card_grid_css()


def _to_dicts(entries) -> list[dict]:
    return [e.model_dump(mode="json") for e in entries]


def _grid(items: list[dict], *, key_prefix: str, cols: int = 4) -> None:
    if not items:
        st.caption("해당 항목이 없습니다.")
        return
    for row_start in range(0, len(items), cols):
        row = items[row_start : row_start + cols]
        col_objs = st.columns(cols)
        for col, item in zip(col_objs, row):
            with col:
                if components.render_card(
                    item, key_prefix=f"{key_prefix}_{row_start}"
                ):
                    _iid = item.get("id", "")
                    st.session_state["_detail_item_id"] = _iid
                    st.session_state["_detail_origin"] = "pages/0_대시보드.py"
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _by_status(statuses: list, *, include_closed: bool = False) -> list[dict]:
    out: list = []
    for s in statuses:
        out.extend(
            repository.list_issues(
                status=s,
                include_archived=False,
                include_closed=include_closed,
                project=current_project,
            )
        )
    out.sort(
        key=lambda e: e.model_dump(mode="json").get("updated_at") or "",
        reverse=True,
    )
    return _to_dicts(out)


# ---------------------------------------------------------------------------
# 헤더 + CTA
# ---------------------------------------------------------------------------

if current_project:
    st.caption(f"{current_project} / 대시보드")
st.title("대시보드")
st.write(f"안녕하세요, **{name}**님")

cta_col, _ = st.columns([1, 4])
with cta_col:
    if st.button("+ 새 요청 등록", type="primary", width="stretch"):
        st.switch_page("pages/2_새요청등록.py")

st.divider()


# ---------------------------------------------------------------------------
# 상태별 섹션
# ---------------------------------------------------------------------------

# 1) 전체 개발 목록 — 완료·삭제 제외 모든 진행 항목
all_active_entries = repository.list_issues(
    include_archived=False, include_closed=False, project=current_project
)
all_active = _to_dicts(all_active_entries)
st.subheader(f"전체 개발 목록 ({len(all_active)})")
st.caption("완료·삭제를 제외한 모든 진행 항목")
_grid(all_active, key_prefix="dash_all")

st.divider()

# 2) 담당자 처리
assignee_items = _by_status(
    [
        Status.assignee_request,
        Status.assignee_reviewing,
        Status.assignee_reviewed,
        Status.assignee_developing,
        Status.assignee_fixing,
    ]
)
st.subheader(f"담당자 처리 ({len(assignee_items)})")
st.caption("담당자확인요청 · 검토중 · 검토완료 · 신규개발중 · 코드수정중")
_grid(assignee_items, key_prefix="dash_assignee")

st.divider()

# 3) 개발사
vendor_items = _by_status([Status.vendor_request, Status.vendor_reply])
st.subheader(f"개발사 ({len(vendor_items)})")
st.caption("개발사확인중 · 개발사회신확인중")
_grid(vendor_items, key_prefix="dash_vendor")

st.divider()

# 4) 등록자 확인
author_items = _by_status([Status.author_request, Status.author_reviewing])
st.subheader(f"등록자 확인 ({len(author_items)})")
st.caption("등록자확인요청 · 등록자검토중")
_grid(author_items, key_prefix="dash_author")

st.divider()

# 5) 완료
done = _by_status([Status.closed], include_closed=True)
st.subheader(f"완료 ({len(done)})")
st.caption("등록자가 최종 완료한 항목")
_grid(done, key_prefix="dash_done")

st.divider()

# 6) 삭제 — archived 항목 (상태 무관)
_archived_entries = repository.list_issues(
    include_archived=True, include_closed=True, project=current_project
)
archived = _to_dicts([e for e in _archived_entries if e.archived])
st.subheader(f"삭제 ({len(archived)})")
st.caption("삭제(보관) 처리된 항목")
_grid(archived, key_prefix="dash_arch")


# ---------------------------------------------------------------------------
# 사이드바 — 상태 바로가기
# ---------------------------------------------------------------------------

STATUS_NAV_KEYS = [
    "assignee_request",
    "assignee_reviewing",
    "assignee_reviewed",
    "assignee_developing",
    "assignee_fixing",
    "vendor_request",
    "vendor_reply",
    "author_request",
    "author_reviewing",
]

with st.sidebar:
    st.divider()
    st.markdown("**상태 바로가기**")
    active_only = repository.list_issues(
        include_archived=False, include_closed=False, project=current_project
    )
    _status_counts: dict[str, int] = {}
    for _e in active_only:
        _sv = _e.status.value if hasattr(_e.status, "value") else str(_e.status)
        _status_counts[_sv] = _status_counts.get(_sv, 0) + 1
    for _k in STATUS_NAV_KEYS:
        if st.button(
            f"{STATUS_LABELS[_k]} ({_status_counts.get(_k, 0)})",
            key=f"side_status_{_k}",
            width="stretch",
        ):
            st.session_state["list_preset_status"] = _k
            st.switch_page("pages/1_요청목록.py")
