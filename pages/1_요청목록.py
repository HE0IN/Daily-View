"""요청 목록 페이지 — docs/03_ui_design.md 3.4 절.

필터(긴급도/상태/담당자/검색/정렬/카테고리) + 카드 그리드(4×4 = 16) 페이지네이션.
session_state 로 현재 페이지 추적, 필터 변경 시 1페이지로 리셋.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from core import paths, repository
from core.models import Role, Status, Urgency
from core.workflow import allowed_transitions, can_transition
from ui import components
from ui.auth import get_or_init_user, render_project_selector, require_user
from ui.theme import STATUS_LABELS, URGENCY_LABELS

# 자동 새로고침 (M3). 미설치/0 이면 비활성.
try:  # pragma: no cover - 환경 의존
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
except Exception:  # noqa: BLE001
    _st_autorefresh = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 페이지 설정 + 부트스트랩
# ---------------------------------------------------------------------------

# 공통 처리(set_page_config·부트스트랩·자동새로고침·사용자식별·프로젝트선택)는
# 진입점 app.py(라우터)가 수행한다. 이 페이지는 session_state 만 읽는다.
user = st.session_state.get("user")
if not user:
    st.stop()

# 상세보기 인라인 편집모드 stale 정리 (비상세 페이지 진입 = 편집 종료).
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

if current_project:
    st.title(f"개발목록 — {current_project}")
else:
    st.title("개발목록")


# ---------------------------------------------------------------------------
# 필터 옵션 준비 (담당자 후보 = 인덱스 전체에서 unique)
# ---------------------------------------------------------------------------

# 한 번 전체 로드해서 담당자 옵션 추출 (필터링은 아래에서 다시).
# 현재 프로젝트가 선택돼 있으면 그 프로젝트에 등장한 담당자만 후보로 노출.
all_entries_for_options = repository.list_issues(
    include_archived=True, project=current_project
)
assignee_set: set[str] = {
    e.assignee for e in all_entries_for_options if e.assignee
}
assignee_options = ["(전체)", "(미할당)"] + sorted(assignee_set)

# 1번: 담당자 기본값은 무조건 '(전체)' — 자기 이름이 자동 선택되지 않게 한다.
default_assignee = "(전체)"
# 대시보드 [내 큐 전체 보기] CTA 에서 넘긴 값이 있으면 그것만 우선.
preset_assignee = st.session_state.pop("list_default_assignee", None)
if preset_assignee and preset_assignee in assignee_options:
    default_assignee = preset_assignee

# ---------------------------------------------------------------------------
# 필터 UI
# ---------------------------------------------------------------------------

# 대시보드/사이드바 '상태 바로가기' 에서 넘어온 프리셋 — status multiselect
# 기본값 주입. 위젯 인스턴스화 전에 session_state[key] 를 세팅해야 초기값 반영.
_preset_status = st.session_state.pop("list_preset_status", None)
if _preset_status:
    st.session_state["list_status"] = [_preset_status]
    # 완료(closed)는 기본 숨김이므로, 완료로 필터 진입 시 '완료 포함'도 자동 ON.
    if _preset_status == "closed":
        st.session_state["list_inc_closed"] = True

# 복수 상태 preset (통계 핵심지표 '진행 중'/'정체' 등에서 여러 상태로 진입).
_preset_statuses = st.session_state.pop("list_preset_statuses", None)
if _preset_statuses:
    st.session_state["list_status"] = list(_preset_statuses)
    if "closed" in _preset_statuses:
        st.session_state["list_inc_closed"] = True

# 9번: 통계 '보기' 로 진입하면 기존 담당자 선택을 제거 → 위의 default((전체))가
# 적용되게 한다. (session_state 와 selectbox default 동시 지정 경고 방지)
if _preset_status or _preset_statuses:
    st.session_state.pop("list_assignee", None)

# 정렬 preset (예: 정체 → 오래된순).
_preset_sort = st.session_state.pop("list_preset_sort", None)
if _preset_sort:
    st.session_state["list_sort"] = _preset_sort

# 카테고리 대분류 옵션 (현재 프로젝트로 좁힘) — 필터 한 줄에 포함하기 위해 먼저 계산.
try:
    cat_tree = repository.list_categories(project=current_project)
except TypeError:
    cat_tree = repository.list_categories()
except Exception:  # noqa: BLE001
    cat_tree = {}
category_l1_options = ["(전체)"] + sorted(cat_tree.keys())
if (
    st.session_state.get("list_category_l1")
    and st.session_state["list_category_l1"] not in category_l1_options
):
    st.session_state["list_category_l1"] = "(전체)"

# 9번: 필터 셀렉트박스를 모두 한 줄에 (긴급도/상태/담당자/검색/정렬/카테고리).
f1, f2, f3, f4, f5, f6 = st.columns([1, 1.8, 1.3, 1.8, 1.2, 1.5])

with f1:
    urgency_choice = st.selectbox(
        "긴급도",
        options=["(전체)"] + [u.value for u in Urgency],
        format_func=lambda v: "전체" if v == "(전체)" else URGENCY_LABELS.get(v, v),
        key="list_urgency",
    )
with f2:
    status_choice: list[str] = st.multiselect(
        "상태 (다중)",
        options=[s.value for s in Status],
        format_func=lambda v: STATUS_LABELS.get(v, v),
        key="list_status",
        help="비어 있으면 전체",
    )
with f3:
    assignee_choice = st.selectbox(
        "담당자",
        options=assignee_options,
        index=assignee_options.index(default_assignee)
        if default_assignee in assignee_options
        else 0,
        key="list_assignee",
    )
with f4:
    search_query = st.text_input(
        "검색", placeholder="제목/태그", key="list_search"
    )
with f5:
    sort_choice = st.selectbox(
        "정렬",
        options=["최신순", "오래된순", "긴급도순", "상태순"],
        key="list_sort",
    )
with f6:
    category_l1_choice = st.selectbox(
        "카테고리",
        options=category_l1_options,
        key="list_category_l1",
    )

# 2번: 완료포함 · 삭제(보관) · 보기(카드/테이블)를 한 줄에.
opt_col1, opt_col2, opt_col3 = st.columns([1, 1.2, 1])
with opt_col1:
    include_closed = st.checkbox(
        "완료된 작업 포함",
        value=False,
        key="list_inc_closed",
        help="검토완료(closed) 처리된 항목까지 함께 표시합니다.",
    )
with opt_col2:
    archive_view = st.radio(
        "삭제(보관) 항목",
        options=["제외", "포함", "삭제만"],
        horizontal=True,
        key="list_archive_view",
        help="'삭제만' = 삭제(보관)된 항목만 모아보기.",
    )
# 라디오 → 내부 플래그 (제외=숨김 / 포함=같이 / 삭제만=아카이브만)
include_archived = archive_view != "제외"

# 보기 모드 토글 — 카드/테이블
with opt_col3:
    view_mode = st.radio(
        "보기",
        options=["카드", "테이블"],
        horizontal=True,
        key="list_view_mode",
    )

# ---------------------------------------------------------------------------
# 데이터 조회 (서버측 필터 가능한 항목만 repository 에 위임,
# 나머지는 클라이언트측에서 추가 처리)
# ---------------------------------------------------------------------------


def _fetch_entries() -> list[dict]:
    """필터 조건에 따라 list_issues 를 호출하고 dict 리스트로 반환."""
    repo_kwargs: dict = {
        "include_archived": include_archived,
        "include_closed": include_closed,
        "search": search_query.strip() or None,
        "project": current_project,
    }

    # 긴급도
    if urgency_choice != "(전체)":
        repo_kwargs["urgency"] = urgency_choice

    # 담당자: repository.list_issues 는 assignee=None 을 "필터 없음"으로 해석하므로
    # 미할당 전용 필터는 후처리에서 적용한다.
    if assignee_choice == "(미할당)":
        unassigned_only = True
    elif assignee_choice == "(전체)":
        unassigned_only = False
    else:
        repo_kwargs["assignee"] = assignee_choice
        unassigned_only = False

    # 상태: 단일이면 repository 인자, 다중이면 후처리.
    status_filter_post: set[str] | None = None
    if len(status_choice) == 1:
        repo_kwargs["status"] = status_choice[0]
    elif len(status_choice) > 1:
        status_filter_post = set(status_choice)

    entries = repository.list_issues(**repo_kwargs)

    # 후처리 필터
    if unassigned_only:
        entries = [e for e in entries if not e.assignee]
    if status_filter_post is not None:
        entries = [
            e
            for e in entries
            if (e.status.value if hasattr(e.status, "value") else str(e.status))
            in status_filter_post
        ]
    # 카테고리 대분류 필터 (list_issues 가 카테고리 인자를 받지 않으므로 후처리).
    if category_l1_choice and category_l1_choice != "(전체)":
        entries = [
            e for e in entries if (e.category_l1 or "") == category_l1_choice
        ]

    items = [e.model_dump(mode="json") for e in entries]

    # 정렬
    if sort_choice == "오래된순":
        items.sort(key=lambda d: d.get("updated_at") or "")
    elif sort_choice == "긴급도순":
        # 4 단계: critical(긴급) > high(상) > normal(중) > low(하).
        urgency_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        items.sort(
            key=lambda d: (
                urgency_order.get(d.get("urgency", ""), 9),
                d.get("updated_at") or "",
            )
        )
    elif sort_choice == "상태순":
        status_order = {
            "assignee_request": 0,
            "assignee_reviewing": 1,
            "assignee_reviewed": 2,
            "assignee_developing": 3,
            "assignee_fixing": 4,
            "vendor_request": 5,
            "vendor_reply": 6,
            "author_request": 7,
            "author_reviewing": 8,
            "closed": 9,
        }
        items.sort(
            key=lambda d: (
                status_order.get(d.get("status", ""), 9),
                d.get("updated_at") or "",
            )
        )
    # 기본(최신순)은 list_issues 가 이미 updated_at desc 정렬.
    return items


items = _fetch_entries()
if archive_view == "삭제만":
    items = [i for i in items if i.get("archived")]
total = len(items)


# ---------------------------------------------------------------------------
# 결과 카운트 + 본문 (페이지네이션 없이 전체 표시)
# ---------------------------------------------------------------------------

st.caption(f"총 {total}건")

# 개발목록 전체 PDF (개발사 API 요청 송부용) — A4 페이지당 항목 1개(제목/설명/사진).
# [만들기] 로 생성(세션 저장) → [다운로드]. 매 렌더 재생성을 피하려 2단계로 나눔.
if items:
    _pdf_c1, _pdf_c2 = st.columns([1, 3])
    with _pdf_c1:
        if st.button("📄 전체 PDF 만들기", key="dev_pdf_build", width="stretch"):
            from core import pdf_export

            _issues_for_pdf = [
                repository.get_issue(it["id"]) for it in items if it.get("id")
            ]
            st.session_state["_dev_list_pdf"] = pdf_export.build_issues_pdf(
                _issues_for_pdf
            )
            st.toast(f"{len(_issues_for_pdf)}건 PDF 생성 완료", icon="📄")
    if st.session_state.get("_dev_list_pdf"):
        with _pdf_c2:
            st.download_button(
                "⬇ PDF 다운로드 (개발목록)",
                data=st.session_state["_dev_list_pdf"],
                file_name="개발목록.pdf",
                mime="application/pdf",
                key="dev_pdf_dl",
                width="stretch",
            )

# 5번: 카드의 체크박스로 선택한 항목들을 한 번에 다음 단계로 — 코멘트 필수.
#   카드뷰에서 각 카드를 체크하면 (같은 상태끼리) 아래 일괄 전환 UI 가 나타난다.
#   각 항목의 권한(담당자/등록자)을 개별 판단해 가능한 건만 전환하고 나머지는 보고.
_bulk_sel_ids = [
    it["id"] for it in items if st.session_state.get(f"bulksel_{it['id']}")
]
if _bulk_sel_ids:
    _sel_items = [it for it in items if it["id"] in _bulk_sel_ids]
    _sel_statuses = {it["status"] for it in _sel_items}
    with st.container(border=True):
        st.markdown(f"**☑ 선택한 {len(_bulk_sel_ids)}건 일괄 전환**")
        if len(_sel_statuses) > 1:
            st.warning(
                "같은 상태(단계)끼리만 일괄 전환할 수 있습니다 — "
                "선택 항목의 상태가 섞여 있어요."
            )
        else:
            _sval = next(iter(_sel_statuses))
            # 이 상태에서 담당자/등록자가 갈 수 있는 다음 단계(중복 제거).
            # 확인대기는 확인요청 전용이라 개발목록 일괄전환에서는 제외한다.
            _next_uniq: list[Status] = []
            for _r in (Role.developer, Role.reviewer):
                for _ns in allowed_transitions(Status(_sval), _r):
                    if _ns == Status.pending_check or _ns in _next_uniq:
                        continue
                    _next_uniq.append(_ns)
            if not _next_uniq:
                st.caption(
                    f"'{STATUS_LABELS.get(_sval, _sval)}' 단계는 "
                    f"넘어갈 다음 단계가 없습니다."
                )
            else:
                _nbc1, _nbc2 = st.columns([2, 3])
                with _nbc1:
                    _next_labels = [
                        STATUS_LABELS.get(s.value, s.value) for s in _next_uniq
                    ]
                    _next_sel = st.selectbox(
                        "다음 단계", _next_labels, key="bulk_next"
                    )
                    _next_status = _next_uniq[_next_labels.index(_next_sel)]
                with _nbc2:
                    _bulk_comment = st.text_input(
                        "코멘트 (필수)",
                        key="bulk_comment",
                        placeholder="일괄 전환 사유",
                    )
                if st.button(
                    f"⏩ {len(_bulk_sel_ids)}건 → {_next_sel}",
                    type="primary",
                    key="bulk_apply",
                ):
                    if not _bulk_comment.strip():
                        st.error("코멘트는 필수입니다.")
                    else:
                        _ok, _skip = 0, []
                        for _iid in _bulk_sel_ids:
                            _iss = repository.get_issue(_iid)
                            _role = None
                            if _iss.assignee == name and can_transition(
                                _iss.status, Role.developer, _next_status
                            ):
                                _role = Role.developer
                            elif _iss.author == name and can_transition(
                                _iss.status, Role.reviewer, _next_status
                            ):
                                _role = Role.reviewer
                            if _role is not None:
                                repository.add_comment(
                                    _iid,
                                    name,
                                    _role,
                                    f"[일괄 전환] {_bulk_comment.strip()}",
                                )
                                repository.update_status(
                                    _iid, _next_status, name, _role
                                )
                                _ok += 1
                            else:
                                _skip.append(_iss.title)
                        if _ok:
                            st.success(
                                f"{_ok}건을 '{_next_sel}'(으)로 전환했습니다."
                            )
                        if _skip:
                            st.warning(
                                f"권한이 없어 제외 {len(_skip)}건: "
                                f"{', '.join(_skip[:5])}"
                            )
                        for _iid in _bulk_sel_ids:
                            st.session_state.pop(f"bulksel_{_iid}", None)
                        st.rerun()


def _render_card_view(items_local: list[dict]) -> None:
    """카드 그리드 (4열) — 전체 항목을 한 번에 표시."""
    # 같은 행 카드들이 가장 긴 카드 높이로 stretch — 한 번만 주입.
    components.render_card_grid_css()
    cols_per_row = 4  # 카드를 컴팩트하게 줄였으니 한 행에 더 많이.
    for row_start in range(0, len(items_local), cols_per_row):
        row = items_local[row_start : row_start + cols_per_row]
        col_objs = st.columns(cols_per_row)
        for col, item in zip(col_objs, row):
            with col:
                # 삭제(보관) 처리된 항목임을 카드 위에 표시
                if item.get("archived"):
                    st.caption("🗑 삭제됨")
                _iid = item.get("id", "")
                # 5번: 카드에 선택 체크박스 → 상단 일괄 전환 UI 에서 한 번에 처리.
                _res = components.render_card(
                    item,
                    key_prefix=f"list_r{row_start}",
                    checkbox=("선택", f"bulksel_{_iid}"),
                )
                if _res["open"]:
                    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
                    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
                    st.session_state["_detail_item_id"] = _iid
                    st.session_state["_detail_origin"] = "pages/1_요청목록.py"
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")


def _render_table_view(page_items_local: list[dict]) -> None:
    """st.dataframe 표시 — 행을 클릭하면 그 항목 상세보기로 바로 이동.

    열 순서: 카테고리(대>중>소) · 제목 · 비고(설명) · 상태 · 담당자 · 등록.
    ID 열은 숨기고, 행 선택 위치(index)로 page_items_local 의 항목을 매핑한다.
    긴급도는 행 배경색용으로만 두고(열 숨김) 표에는 노출하지 않는다.
    """
    rows = []
    for item in page_items_local:
        urgency = item.get("urgency", "normal")
        urgency_label = URGENCY_LABELS.get(urgency, urgency)
        status_label = STATUS_LABELS.get(item.get("status", ""), "")
        desc_preview = (item.get("description_preview") or "")[:80]
        _cats = [
            item.get("category_l1"),
            item.get("category_l2"),
            item.get("category_l3"),
        ]
        cat_path = " > ".join(c for c in _cats if c) or "(미분류)"
        rows.append({
            "카테고리": cat_path,
            "제목": item.get("title", ""),
            "비고": desc_preview,
            "상태": status_label,
            "담당자": item.get("assignee") or "(미배정)",
            "등록": components.humanize_dt(item.get("created_at", "")),
            "_긴급도": urgency_label,  # 배경색 전용 — column_order 로 숨김
        })
    df = pd.DataFrame(rows)

    # 긴급도별 row 배경색 (Styler.apply 로 행 단위 적용).
    def _row_style(row: pd.Series) -> list[str]:
        urg_label = row.get("_긴급도", "")
        bg = ""
        if urg_label == "긴급":
            bg = "background-color: #FEE2E2;"  # 빨강 옅음
        elif urg_label == "상":
            bg = "background-color: #FEF3C7;"  # 주황 옅음
        elif urg_label == "하":
            bg = "background-color: #DCFCE7;"  # 초록 옅음
        return [bg] * len(row)

    styler = df.style.apply(_row_style, axis=1)

    st.caption("행을 클릭하면 상세보기로 이동합니다.")
    event = st.dataframe(
        styler,
        width="stretch",
        hide_index=True,
        column_order=["카테고리", "제목", "비고", "상태", "담당자", "등록"],
        on_select="rerun",
        selection_mode="single-row",
        key="list_table_df",
    )

    # 행 선택 → 그 항목 상세보기로 즉시 이동.
    _sel = getattr(event, "selection", None)
    _rows_sel = (_sel.get("rows") if isinstance(_sel, dict) else getattr(_sel, "rows", None)) or []
    if _rows_sel:
        _idx = int(_rows_sel[0])
        if 0 <= _idx < len(page_items_local):
            _id = page_items_local[_idx].get("id")
            st.session_state["_detail_item_id"] = _id
            st.session_state["_detail_origin"] = "pages/1_요청목록.py"
            st.session_state["_table_return_target"] = _id
            st.query_params["id"] = _id
            st.switch_page("pages/3_상세보기.py")


if total == 0:
    st.info("조건에 맞는 항목이 없습니다.")
elif view_mode == "테이블":
    _render_table_view(items)
else:
    _render_card_view(items)
