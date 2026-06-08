"""대시보드 — 전체 현황 (역할 무관 공통 화면).

검토자/개발자 구분 없이 동일한 화면을 보여준다. 상태별 섹션을 순서대로 나열:
    전체 개발 목록 / 개발 / 검토 / 외부대기 / 완료 / 삭제

공통 처리(부트스트랩·사용자식별·프로젝트선택)는 진입점 app.py(라우터)가 수행하고,
이 페이지는 session_state 의 user / _current_project 를 읽어 사용한다.
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.models import Status
from ui import components
from ui.theme import STATUS_COLORS, STATUS_LABELS

# 라우터가 보장하지만 방어적으로 — user 없으면 정지.
user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

components.render_card_grid_css()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _to_dicts(entries) -> list[dict]:
    return [e.model_dump(mode="json") for e in entries]


def _grid(items: list[dict], *, key_prefix: str, cols: int = 4) -> None:
    """카드 그리드. 클릭 시 상세보기로 이동."""
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
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _by_status(statuses: list, *, include_closed: bool = False) -> list[dict]:
    """여러 상태의 활성 항목을 모아 updated_at desc 정렬."""
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
    if st.button("+ 새 개발 등록", type="primary", width="stretch"):
        st.switch_page("pages/2_새요청등록.py")

st.divider()


# ---------------------------------------------------------------------------
# 상태별 섹션 (순서대로)
# ---------------------------------------------------------------------------

# 1) 전체 개발 목록 — 개발자가 처리해야 할 큐
dev_wait = _by_status(
    [Status.requested, Status.needs_recheck, Status.rejected, Status.reopened]
)
st.subheader(f"전체 개발 목록 ({len(dev_wait)})")
st.caption("요청됨 · 추가확인필요 · 반려 — 개발자가 처리할 항목")
_grid(dev_wait, key_prefix="dash_wait")

st.divider()

# 2) 개발
dev = _by_status([Status.in_progress])
st.subheader(f"개발 ({len(dev)})")
st.caption("개발중인 항목")
_grid(dev, key_prefix="dash_dev")

st.divider()

# 3) 검토
review = _by_status([Status.reviewing])
st.subheader(f"검토 ({len(review)})")
st.caption("검토중인 항목")
_grid(review, key_prefix="dash_review")

st.divider()

# 4) 외부대기
api = _by_status([Status.api_check])
st.subheader(f"외부대기 ({len(api)})")
st.caption("외부 API 답변 대기 중")
_grid(api, key_prefix="dash_api")

st.divider()

# 5) 완료
done = _by_status([Status.closed], include_closed=True)
st.subheader(f"완료 ({len(done)})")
st.caption("검토완료된 항목")
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
    "requested",
    "in_progress",
    "api_check",
    "reviewing",
    "needs_recheck",
    "rejected",
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
