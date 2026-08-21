"""대시보드 — 전체 현황 (역할 무관 공통 화면).

상태별 섹션:
    전체 개발 목록 / 담당자 처리 / 개발사 / 등록자 확인 / 완료 / 삭제

공통 처리(부트스트랩·사용자식별·프로젝트선택)는 진입점 app.py(라우터)가 수행하고,
이 페이지는 session_state 의 user / _current_project 를 읽어 사용한다.
"""

from __future__ import annotations

import streamlit as st

from core import repository
from core.models import Status, Urgency
from ui import components
from ui.theme import STATUS_LABELS, URGENCY_LABELS

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
                    # 6번: 클릭한 섹션의 순서대로 상세보기 [다음 →] 이동.
                    st.session_state["_detail_nav_ids"] = [
                        it.get("id") for it in items
                    ]
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _repo_kwargs() -> dict:
    """상단 필터 → repository.list_issues 인자 (서버측에서 거를 수 있는 것만)."""
    kw: dict = {"project": current_project}
    if urgency_choice != "(전체)":
        kw["urgency"] = urgency_choice
    # '(미할당)' 은 list_issues 가 assignee=None 을 '필터 없음' 으로 보므로 후처리.
    if assignee_choice not in ("(전체)", "(미할당)"):
        kw["assignee"] = assignee_choice
    if search_query.strip():
        kw["search"] = search_query.strip()
    return kw


def _post_filter(entries: list) -> list:
    """list_issues 가 못 거르는 조건(미할당·등록자·카테고리)을 뒤에서 적용."""
    out = entries
    if assignee_choice == "(미할당)":
        out = [e for e in out if not e.assignee]
    if author_choice != "(전체)":
        out = [e for e in out if e.author == author_choice]
    if category_l1_choice != "(전체)":
        out = [e for e in out if (e.category_l1 or "") == category_l1_choice]
    return out


def _by_status(statuses: list, *, include_closed: bool = False) -> list[dict]:
    out: list = []
    for s in statuses:
        out.extend(
            repository.list_issues(
                status=s,
                include_deleted=False,
                include_closed=include_closed,
                **_repo_kwargs(),
            )
        )
    out = _post_filter(out)
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


# ---------------------------------------------------------------------------
# 필터 — 개발목록과 같은 구성. 모든 섹션에 공통 적용된다.
#   상태(단계)는 섹션 자체가 그 역할을 하므로 여기서는 제외.
# ---------------------------------------------------------------------------

_FILTER_DEFAULTS = {
    "dash_urgency": "(전체)",
    "dash_assignee": "(전체)",
    "dash_author": "(전체)",
    "dash_search": "",
    "dash_category_l1": "(전체)",
}

# [초기화] 는 플래그만 세우고 rerun 한다. 실제 값 복원은 위젯이 만들어지기 '전'인
# 여기서 처리 — 위젯 생성 후에 그 key 를 건드리면 Streamlit 이 예외를 던진다.
if st.session_state.pop("_dash_filter_reset", False):
    for _k, _v in _FILTER_DEFAULTS.items():
        st.session_state[_k] = _v

# 옵션 후보 — 현재 프로젝트에 실제로 등장한 값만 (삭제 항목까지 포함해서 수집:
# '삭제' 섹션도 필터 대상이라 그쪽 담당자/등록자가 빠지면 안 된다).
_opt_entries = repository.list_issues(
    include_deleted=True, include_closed=True, project=current_project, kind=None
)
_assignee_options = ["(전체)", "(미할당)"] + sorted(
    {e.assignee for e in _opt_entries if e.assignee}
)
_author_options = ["(전체)"] + sorted({e.author for e in _opt_entries if e.author})
try:
    _cat_tree = repository.list_categories(project=current_project)
except Exception:  # noqa: BLE001 - 카테고리 조회 실패가 대시보드를 막지 않게
    _cat_tree = {}
_category_options = ["(전체)"] + sorted(_cat_tree.keys())
# 프로젝트를 바꿔 선택지가 사라졌으면 (전체)로 되돌린다 (stale 선택 방지).
for _key, _opts in (
    ("dash_assignee", _assignee_options),
    ("dash_author", _author_options),
    ("dash_category_l1", _category_options),
):
    if st.session_state.get(_key) and st.session_state[_key] not in _opts:
        st.session_state[_key] = "(전체)"

_f1, _f2, _f3, _f4, _f5, _f6 = st.columns([1, 1.2, 1.2, 1.6, 1.3, 0.8])
with _f1:
    urgency_choice = st.selectbox(
        "긴급도",
        options=["(전체)"] + [u.value for u in Urgency],
        format_func=lambda v: "전체" if v == "(전체)" else URGENCY_LABELS.get(v, v),
        key="dash_urgency",
    )
with _f2:
    assignee_choice = st.selectbox("담당자", options=_assignee_options, key="dash_assignee")
with _f3:
    author_choice = st.selectbox("등록자", options=_author_options, key="dash_author")
with _f4:
    search_query = st.text_input("검색", placeholder="제목/태그", key="dash_search")
with _f5:
    category_l1_choice = st.selectbox(
        "카테고리", options=_category_options, key="dash_category_l1"
    )
with _f6:
    st.write("")  # selectbox 라벨 높이만큼 내려 버튼을 같은 줄에 맞춘다
    if st.button("초기화", width="stretch", help="필터를 모두 (전체)로"):
        st.session_state["_dash_filter_reset"] = True
        st.rerun()

# 필터가 걸려 있으면 눈에 띄게 알린다 — 섹션이 비어 보이는 이유를 바로 알 수 있게.
_active_filters = [
    f"{_label}: {_val}"
    for _label, _val in (
        ("긴급도", URGENCY_LABELS.get(urgency_choice, urgency_choice)),
        ("담당자", assignee_choice),
        ("등록자", author_choice),
        ("카테고리", category_l1_choice),
    )
    if _val != "(전체)"
] + ([f"검색: {search_query.strip()}"] if search_query.strip() else [])
if _active_filters:
    st.info("필터 적용 중 — " + " · ".join(_active_filters))

st.divider()


# ---------------------------------------------------------------------------
# 상태별 섹션
# ---------------------------------------------------------------------------

# 1) 전체 개발 목록 — 완료까지 포함한 전체 개발 항목 (삭제 표시된 것만 제외, 4번)
all_active_entries = _post_filter(
    repository.list_issues(
        include_deleted=False, include_closed=True, **_repo_kwargs()
    )
)
all_active = _to_dicts(all_active_entries)
st.subheader(f"전체 개발 목록 ({len(all_active)})")
st.caption("완료 포함 전체 개발 항목 (삭제 표시된 항목만 제외)")
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
vendor_items = _by_status(
    [Status.vendor_wait, Status.vendor_request, Status.vendor_reply]
)
st.subheader(f"개발사 ({len(vendor_items)})")
st.caption("개발사요청대기 · 개발사확인중 · 개발사회신확인중")
_grid(vendor_items, key_prefix="dash_vendor")

st.divider()

# 3-2) 담당팀 (개발사와 동일 구조의 병렬 단계)
team_items = _by_status(
    [Status.team_wait, Status.team_request, Status.team_reply]
)
st.subheader(f"담당팀 ({len(team_items)})")
st.caption("담당팀요청대기 · 담당팀확인중 · 담당팀회신확인중")
_grid(team_items, key_prefix="dash_team")

st.divider()

# 4) 등록자 확인
author_items = _by_status([Status.author_request, Status.author_reviewing])
st.subheader(f"등록자 확인 ({len(author_items)})")
st.caption("등록자확인요청 · 등록자검토중")
_grid(author_items, key_prefix="dash_author")

st.divider()

# 5) 완료 — 상태가 '완료(closed)' 인 항목 전부. 기간·보관과 무관하게 항상 집계된다.
#    (삭제 표시를 한 항목만 빠진다 — include_deleted=False)
done = _by_status([Status.closed], include_closed=True)
st.subheader(f"완료 ({len(done)})")
st.caption("등록자가 최종 완료한 항목 전체 (오래돼도 계속 집계)")
_grid(done, key_prefix="dash_done")

st.divider()

# 6) 삭제 — 삭제 태그(deleted)가 붙은 항목만. 상태·종류 무관.
#    kind=None 으로 확인요청·Temp 삭제 항목도 포함.
_deleted_entries = _post_filter(
    repository.list_issues(
        include_deleted=True, include_closed=True, kind=None, **_repo_kwargs()
    )
)
deleted_items = _to_dicts([e for e in _deleted_entries if e.deleted])
st.subheader(f"삭제 ({len(deleted_items)})")
st.caption("삭제 표시한 항목 (개발·확인요청·Temp 모두) — 상세보기에서 복구 가능")
_grid(deleted_items, key_prefix="dash_arch")


# ---------------------------------------------------------------------------
# 사이드바 — 상태 바로가기
# ---------------------------------------------------------------------------

STATUS_NAV_KEYS = [
    "assignee_request",
    "assignee_reviewing",
    "assignee_reviewed",
    "assignee_developing",
    "assignee_fixing",
    "vendor_wait",
    "vendor_request",
    "vendor_reply",
    "team_wait",
    "team_request",
    "team_reply",
    "author_request",
    "author_reviewing",
]

with st.sidebar:
    st.divider()
    st.markdown("**상태 바로가기**")
    active_only = _post_filter(
        repository.list_issues(
            include_deleted=False, include_closed=False, **_repo_kwargs()
        )
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
