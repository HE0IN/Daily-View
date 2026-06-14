"""상세보기 페이지.

docs/03_ui_design.md 3.5 절을 따른다.
``?id=...`` query param 으로 진입한다.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import streamlit as st

from components.paste_clipboard import paste_clipboard
from core import paths, project_settings as ps_mod, repository
from core.clock import from_iso, humanize
from core.images import (
    ALLOWED_EXT,
    MAX_FILE_MB,
    MAX_IMAGES_PER_ITEM,
    decode_image_data_url,
)
from core.models import Comment, Issue, Role, Status, Urgency
from core.workflow import (
    STATUS_LABELS_KO,
    URGENCY_LABELS_KO,
    WorkflowError,
    allowed_transitions,
)
from ui.auth import get_or_init_user, require_user
from ui.components import humanize_dt
from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    status_badge_html,
    urgency_badge_html,
)


# ---------------------------------------------------------------------------
# 페이지 셋업
# ---------------------------------------------------------------------------

# 공통 처리(set_page_config·부트스트랩·사용자식별)는 진입점 app.py(라우터)가 수행.
user = st.session_state.get("user")
if not user:
    st.stop()

# 항목 ID 추출 — 두 경로 모두 지원:
#  1) query_params["id"]  (직접 URL 입력 / 북마크 / 새로고침 후)
#  2) session_state["_detail_item_id"]  (목록·등록 페이지에서 st.switch_page 로 전달.
#     Streamlit 의 switch_page 가 직전에 세팅한 query_params 를 유실하는 케이스가
#     있어 session_state 로 함께 전달하고 여기서 둘 다 시도한다.)
_qp_id = st.query_params.get("id")
if isinstance(_qp_id, list):  # 옛 streamlit 호환
    _qp_id = _qp_id[0] if _qp_id else None
item_id: str | None = _qp_id or st.session_state.get("_detail_item_id")

# session_state 로 도착했다면 query_params 에도 반영 — 사용자가 새로고침해도 유지.
if item_id and not _qp_id:
    st.query_params["id"] = item_id
# 한 번 사용한 session_state 슬롯은 정리 (다른 항목으로 이동 시 stale 방지).
st.session_state.pop("_detail_item_id", None)
# 3번: 목록 테이블뷰로 '뒤로' 돌아갈 때 이 항목이 selectbox 에 유지되도록 기억.
if item_id:
    st.session_state["_table_return_target"] = item_id

if not item_id:
    st.warning("항목 ID가 지정되지 않았습니다. 요청 목록에서 항목을 선택해주세요.")
    st.page_link("pages/1_요청목록.py", label="개발목록으로 →")
    st.stop()

try:
    issue: Issue = repository.get_issue(item_id)
except paths.InvalidItemIdError:
    # path traversal 페이로드 등 형식이 어긋난 ID — 디스크 접근 자체가 차단됨
    st.error("잘못된 항목 ID 형식입니다.")
    st.page_link("pages/1_요청목록.py", label="개발목록으로 →")
    st.stop()
except FileNotFoundError:
    st.error(f"항목을 찾을 수 없습니다: #{html.escape(item_id)}")
    st.page_link("pages/1_요청목록.py", label="개발목록으로 →")
    st.stop()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _abs_image_path(rel: str) -> Path:
    """meta.json 에 저장된 항목 상대경로(`images/...`)를 절대경로로."""
    return paths.item_dir(item_id) / rel


def _abs_tooltip_dt(dt: datetime | str) -> str:
    """절대시간 문자열 (툴팁용 초까지)."""
    try:
        d = from_iso(dt) if isinstance(dt, str) else dt
        return d.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


def _role_label(role: str | Role) -> str:
    value = role.value if isinstance(role, Role) else str(role)
    if value == "reviewer":
        return "등록자"
    if value == "developer":
        return "담당자"
    if value == "system":
        return "시스템"
    return value


def _role_color(role: str | Role) -> str:
    value = role.value if isinstance(role, Role) else str(role)
    if value == "reviewer":
        return "#3B82F6"
    if value == "developer":
        return "#8B5CF6"
    return "#6B7280"


# ---------------------------------------------------------------------------
# 상단 헤더: 가로 컴팩트 레이아웃
#   1행: [← 목록으로]                                              #ID
#   2행: 제목(긴급도 배지) ............................. 상태 배지
#   3행: [등록자·담당자·변경] | [프로젝트·변경] | [카테고리·수정] | [→ 완료]
#        - meta_c1 (4): 등록자/시간/담당자(붙어) + 담당자 변경 popover (붙어)
#        - meta_c2 (2): 프로젝트 표시 + 변경 popover
#        - meta_c3 (2): 카테고리 표시 + 수정 popover
#        - meta_c4 (1): 우측 끝 [→ 완료] 버튼 (closed 전이 가능 시)
#   4행: (제거됨 — SLA 표시 없음)
#   5행: 상태 변경 버튼 (closed 제외, 가로 한 줄)
# ---------------------------------------------------------------------------

# 상태 변경 등 popover 팝업을 옆으로 넓게 — 전이 옵션 + 코멘트 입력이 들어가
# 기본 폭으로는 좁다. (selector 는 Streamlit 버전에 따라 달라질 수 있어 둘 다 지정)
st.markdown(
    """
    <style>
    [data-testid="stPopoverBody"],
    div[data-baseweb="popover"] [data-testid="stPopoverBody"] {
        min-width: 480px !important;
        max-width: 95vw !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 1행: 목록 / 뒤로(이전) / 다음 + ID -------------------------------------
# 7번: [목록]=목록으로, [뒤로]=이전 항목, [다음]=다음 항목. 같은 너비로 왼쪽 정렬,
#      텍스트보다 약간 큰 정도. 목록 순서는 들어온 화면이 _detail_nav_ids 로 넘겨준다.
_back_target = st.session_state.get("_detail_origin", "pages/1_요청목록.py")
_nav_ids = [i for i in (st.session_state.get("_detail_nav_ids") or []) if i]
_cur_idx = _nav_ids.index(item_id) if item_id in _nav_ids else -1
_has_prev = _cur_idx > 0
_has_next = 0 <= _cur_idx < len(_nav_ids) - 1


def _go_to(_target_id: str) -> None:
    st.session_state["_detail_item_id"] = _target_id
    st.query_params["id"] = _target_id
    st.rerun()


# 텍스트보다 약간 큰 고정 너비(px)로 3개 동일하게 — 왼쪽 정렬.
_BTN_W = 84
_c_list, _c_prev, _c_next, _c_sp = st.columns([1, 1, 1, 9])
with _c_list:
    if st.button("목록", key="detail_list_btn", width=_BTN_W, help="목록으로 돌아가기"):
        st.switch_page(_back_target)
with _c_prev:
    if st.button(
        "뒤로", key="detail_prev_btn", width=_BTN_W,
        disabled=not _has_prev, help="목록의 이전 항목",
    ):
        _go_to(_nav_ids[_cur_idx - 1])
with _c_next:
    if st.button(
        "다음", key="detail_next_btn", width=_BTN_W,
        disabled=not _has_next, help="목록의 다음 항목",
    ):
        _go_to(_nav_ids[_cur_idx + 1])
with _c_sp:
    _pos = f"{_cur_idx + 1}/{len(_nav_ids)} · " if _cur_idx >= 0 else ""
    st.markdown(
        f'<div style="text-align:right;color:#6B7280;font-size:0.85em;'
        f'line-height:2.4;">{_pos}#{item_id}</div>',
        unsafe_allow_html=True,
    )

# --- 1.5행: 확인요청(확인대기) 항목 — 개발 요청 / Temp로 (확인요청목록과 동일, 6번) ---
if issue.kind == "unimplemented":
    _pr1, _pr2, _pr_sp = st.columns([1.4, 1.4, 5])
    with _pr1:
        if st.button(
            "개발 요청", key="detail_promote_dev", type="primary", width="stretch",
            help="담당자·긴급도를 지정해 개발목록으로 승격",
        ):
            st.session_state["promote_id"] = item_id
            st.switch_page("pages/2_새요청등록.py")
    with _pr2:
        if st.button(
            "Temp로", key="detail_promote_temp", width="stretch",
            help="확정 보류 — Temp 목록으로 이동",
        ):
            try:
                repository.promote_to_criteria(item_id, user["name"])
                st.toast("Temp 로 이동했습니다", icon="✅")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"이동 실패: {exc}")

# --- 2행: 제목(또는 편집 입력) + 편집/삭제/완전삭제 버튼 ------------------
# 편집 모드 토글 — True 면 제목/설명이 입력칸으로 바뀌고 버튼이 [완료] 가 된다.
_edit_mode = bool(st.session_state.get(f"_edit_mode_{item_id}", False))
if _edit_mode:
    st.warning(
        "✏️ 편집 중입니다 — 상단 **[완료]** 를 누르지 않고 다른 페이지로 이동하면 "
        "변경 내용이 저장되지 않고 취소됩니다."
    )

title_col, title_edit_col, title_del_col, title_purge_col = st.columns(
    [7, 1, 0.7, 0.8]
)
with title_col:
    if _edit_mode:
        st.text_input(
            "제목",
            value=issue.title,
            max_chars=120,
            key=f"edit_title_{item_id}",
            label_visibility="collapsed",
        )
    else:
        # XSS 방지: 사용자 입력은 escape 후 HTML 으로 렌더
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
            f"{urgency_badge_html(issue.urgency.value)}"
            f'<h2 style="margin:0;line-height:1.3;">{html.escape(issue.title)}</h2>'
            f"</div>",
            unsafe_allow_html=True,
        )
with title_edit_col:
    # 인라인 편집 토글 — 편집모드면 [완료](저장), 아니면 [편집]. 누구나 가능.
    if _edit_mode:
        if st.button("완료", type="primary", key="edit_done_btn", width="stretch"):
            try:
                repository.update_issue_content(
                    item_id,
                    st.session_state.get(f"edit_title_{item_id}", issue.title),
                    st.session_state.get(f"edit_desc_{item_id}", issue.description),
                    user["name"],
                )
                st.session_state[f"_edit_mode_{item_id}"] = False
                st.toast("수정되었습니다", icon="✅")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:  # pragma: no cover
                st.error(f"수정 실패: {exc}")
    elif not issue.archived:
        if st.button("편집", key="edit_start_btn", width="stretch"):
            st.session_state[f"_edit_mode_{item_id}"] = True
            st.rerun()
with title_del_col:
    if issue.archived:
        st.caption("🗑")
    else:
        with st.popover("🗑", width="stretch", help="삭제(보관)"):
            st.warning("이 요청을 삭제(보관)하시겠습니까?")
            if st.button("삭제 확인", type="primary", key="del_confirm_title"):
                try:
                    repository.archive_issue(item_id, user["name"])
                    st.toast("삭제(보관)되었습니다", icon="🗑")
                    st.switch_page("pages/1_요청목록.py")
                except Exception as exc:  # pragma: no cover
                    st.error(f"삭제 실패: {exc}")
with title_purge_col:
    with st.popover("🔥", width="stretch", help="완전삭제 (복구 불가)"):
        st.error(
            "⚠ 이 항목의 폴더(이미지·코멘트·메타 전체)를 디스크에서 완전히 "
            "삭제합니다. 되돌릴 수 없습니다."
        )
        if st.button(
            "완전삭제 확인", type="primary", key="purge_confirm_title"
        ):
            try:
                repository.delete_issue_permanently(item_id, user["name"])
                st.toast("완전히 삭제되었습니다", icon="🔥")
                st.switch_page("pages/1_요청목록.py")
            except Exception as exc:  # pragma: no cover
                st.error(f"완전삭제 실패: {exc}")

# --- 3행: 메타 정보 (등록 / 담당 / 카테고리) 가로 배치 ---------------------
created_human = humanize_dt(issue.created_at)
created_abs = _abs_tooltip_dt(issue.created_at)
safe_author = html.escape(str(issue.author))
safe_assignee = html.escape(str(issue.assignee)) if issue.assignee else "미배정"

_cat_path_parts = [
    p for p in (issue.category_l1, issue.category_l2, issue.category_l3) if p
]
_cat_display = (
    " > ".join(html.escape(p) for p in _cat_path_parts)
    if _cat_path_parts
    else "(없음)"
)

# 프로젝트 표시 — 미지정이면 회색 "(미지정)"
_project_raw = issue.project if issue.project else None
if _project_raw:
    _proj_display_html = f"<b>{html.escape(_project_raw)}</b>"
else:
    _proj_display_html = '<span style="color:#9CA3AF;">(미지정)</span>'

# 권한 — 항목별 위치로 결정.
#   등록자(issue.author == 나) → Role.reviewer 권한
#   담당자(issue.assignee == 나) → Role.developer 권한
_user_name = user["name"]
is_author = issue.author == _user_name
is_assignee = issue.assignee == _user_name

# 페이지 상단에 프로젝트 정보 (변경은 사이드바에서만 — 메타 영역에서 제거)
if _project_raw:
    st.caption(f"프로젝트: **{_project_raw}**")

# 4 개 메타 컬럼:
#   c1 = 등록자 + 담당자 + [변경] (sub_columns 비율 [3,1] 로 [변경]을 텍스트
#        끝에 가깝게 — 사용자 요구: "변경 버튼이 너무 멀다")
#   c2 = 긴급도 + [수정]  (NEW — 프로젝트 변경은 사이드바에서만)
#   c3 = 카테고리 + [수정]
#   c4 = [→ 완료] 버튼 (우측 끝, 짧게)
# 상단 메타 — 각 항목(상태 / 등록·담당 / 긴급도 / 카테고리)을 개별 카드로 묶음.
# 각 컬럼 안에서 st.container(border=True) 로 감싸 4 개의 독립 카드처럼 보이게 한다.
meta_c0, meta_c1, meta_c2, meta_c3 = st.columns([1.7, 3, 1.6, 2.2], gap="small")

with meta_c0:
    _st_color = STATUS_COLORS.get(issue.status.value, "#9CA3AF")
    _st_label = STATUS_LABELS.get(issue.status.value, issue.status.value)
    _card0 = st.container(border=True)
    with _card0:
        s_l, s_r = st.columns([2, 1])
    with s_l:
        st.markdown(
            f'<div style="line-height:1.9;">'
            f'<span style="font-size:0.85em;color:#6B7280;">상태 : </span>'
            f'<span style="display:inline-block;padding:3px 12px;'
            f"border-radius:6px;background:{_st_color};color:#fff;"
            f'font-size:1.0em;font-weight:700;">{_st_label}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
    with s_r:
        with st.popover("변경", width="stretch"):
            # 등록자/담당자 위치별 가능한 전이 수집 (target, role)
            _options: list = []
            if is_assignee:
                for _ns in allowed_transitions(issue.status, Role.developer):
                    _options.append((_ns, Role.developer))
            if is_author:
                for _ns in allowed_transitions(issue.status, Role.reviewer):
                    # 확인대기는 등록자(author)만, 담당자확인요청 단계에서 노출.
                    # (확인요청/개발/Temp 어느 kind 든 담당자확인요청 ↔ 확인대기 가능 —
                    #  kind 는 전환 시 함께 바뀌어 목록 사이를 이동한다, 1·3번.)
                    _options.append((_ns, Role.reviewer))
            # R1/R2: 확인대기 ↔ Temp 도 상태변경에서 가능 (확인요청목록의 [Temp로],
            #   Temp 목록의 [확인대기로] 카드 버튼과 동일 동작). 담당자 없는 행정 이동.
            if issue.kind == "unimplemented" and issue.status == Status.pending_check:
                if not any(_t == Status.temp for (_t, _r) in _options):
                    _options.append((Status.temp, Role.reviewer))
            elif issue.kind == "criteria" and issue.status == Status.temp:
                if not any(_t == Status.pending_check for (_t, _r) in _options):
                    _options.append((Status.pending_check, Role.reviewer))
            if not _options:
                # 2번: 이 단계를 '실제로' 바꿀 수 있는 역할+사람만 정확히 안내.
                _who = []
                if allowed_transitions(issue.status, Role.developer):
                    _who.append(f"담당자({issue.assignee or '미지정'})")
                if allowed_transitions(issue.status, Role.reviewer):
                    _who.append(f"등록자({issue.author})")
                if _who:
                    st.caption(
                        f"이 단계는 {' / '.join(_who)} 만 상태를 변경할 수 있습니다."
                    )
                else:
                    st.caption("이 단계에서는 변경할 수 있는 상태가 없습니다.")
            else:
                # 코멘트(사유) 규칙 — 기본 필수, 단 아래는 생략 가능:
                #  · 어떤 단계에서든 '검토중'(담당자검토중·등록자검토중) 또는
                #    '검토완료'로 넘어갈 때 (4번)
                #  · 확인대기 ↔ 담당자확인요청 토글 (3번)
                _REVIEW_TARGETS = (
                    Status.assignee_reviewing,
                    Status.author_reviewing,
                    Status.assignee_reviewed,
                )

                def _is_comment_optional(cur: Status, nxt: Status) -> bool:
                    if nxt in _REVIEW_TARGETS:
                        return True
                    # 확인대기 ↔ 담당자확인요청 / 확인대기 ↔ Temp 토글은 생략 가능.
                    _toggles = {
                        (Status.pending_check, Status.assignee_request),
                        (Status.assignee_request, Status.pending_check),
                        (Status.pending_check, Status.temp),
                        (Status.temp, Status.pending_check),
                    }
                    return (cur, nxt) in _toggles

                # 라벨 힌트 — 가능한 전이 전부 생략 가능이면 (생략 가능),
                # 일부만이면 (검토중·검토완료 전환은 생략 가능), 전무면 (필수).
                _opt_flags = [
                    _is_comment_optional(issue.status, _t) for (_t, _r) in _options
                ]
                if _opt_flags and all(_opt_flags):
                    _label_hint = " (생략 가능)"
                elif any(_opt_flags):
                    _label_hint = " (검토중·검토완료 전환은 생략 가능)"
                else:
                    _label_hint = " (필수)"
                _chg_comment = st.text_area(
                    "변경 사유" + _label_hint,
                    key=f"status_change_comment_{item_id}",
                    placeholder=(
                        "예: 검토 결과 개발사 확인이 필요하여 메일 송부하였습니다."
                    ),
                    height=80,
                )

                # R5: 확인대기 → 담당자확인요청 은 담당자 지정이 필수 → 입력칸 노출.
                _pending_to_dev_avail = (
                    issue.kind == "unimplemented"
                    and issue.status == Status.pending_check
                    and any(_t == Status.assignee_request for (_t, _r) in _options)
                )
                if _pending_to_dev_avail:
                    st.text_input(
                        "담당자 (담당자확인요청 시 필수)",
                        value=issue.assignee or "",
                        placeholder="담당자 이름",
                        key=f"pending_dev_assignee_{item_id}",
                    )

                for _ns, _role in _options:
                    _nl = STATUS_LABELS_KO.get(_ns, _ns.value)
                    if st.button(
                        f"→ {_nl}",
                        key=f"detail_status_change_{_ns.value}",
                        width="stretch",
                    ):
                        _comment_optional = _is_comment_optional(issue.status, _ns)
                        _c = _chg_comment.strip()
                        # 확인대기 → 담당자확인요청: 담당자 필수 (5번).
                        _to_dev = (
                            _ns == Status.assignee_request
                            and issue.status == Status.pending_check
                            and issue.kind == "unimplemented"
                        )
                        _dev_assignee = (
                            (
                                st.session_state.get(
                                    f"pending_dev_assignee_{item_id}"
                                )
                                or ""
                            ).strip()
                            if _to_dev
                            else None
                        )
                        if not _c and not _comment_optional:
                            st.error("상태 변경 시 코멘트(사유)는 필수입니다.")
                        elif _to_dev and not _dev_assignee:
                            st.error(
                                "담당자확인요청으로 보내려면 담당자를 지정해야 합니다."
                            )
                        else:
                            try:
                                if _c:
                                    repository.add_comment(
                                        item_id, _user_name, _role, _c
                                    )
                                # 확인대기↔담당자확인요청 / 확인대기↔Temp 는 kind 도
                                # 함께 바꿔 목록 사이를 이동시킨다 (1·3·5번).
                                if _to_dev:
                                    repository.send_pending_to_dev(
                                        item_id, _user_name, assignee=_dev_assignee
                                    )
                                elif (
                                    _ns == Status.temp
                                    and issue.kind == "unimplemented"
                                ):
                                    repository.promote_to_criteria(
                                        item_id, _user_name
                                    )
                                elif (
                                    _ns == Status.pending_check
                                    and issue.kind == "dev"
                                ):
                                    repository.send_dev_to_pending(
                                        item_id, _user_name
                                    )
                                elif (
                                    _ns == Status.pending_check
                                    and issue.kind == "criteria"
                                ):
                                    repository.revert_criteria_to_request(
                                        item_id, _user_name
                                    )
                                else:
                                    repository.update_status(
                                        item_id, _ns, _user_name, _role
                                    )
                                st.toast(
                                    f"상태가 '{_nl}'로 변경되었습니다", icon="✅"
                                )
                                st.rerun()
                            except WorkflowError as exc:
                                st.error(f"상태 변경 실패: {exc}")
                            except Exception as exc:  # pragma: no cover
                                st.error(f"상태 변경 실패: {exc}")

with meta_c1:
    _card1 = st.container(border=True)
    with _card1:
        sub_l, sub_r = st.columns([3, 1])
    with sub_l:
        st.markdown(
            f'<div style="font-size:0.9em;color:#374151;line-height:1.9;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f"등록: <b>{safe_author}</b> ({_role_label(issue.author_role)}) · "
            f'<span title="{html.escape(created_abs)}">{created_human}</span> · '
            f"담당: <b>{safe_assignee}</b></div>",
            unsafe_allow_html=True,
        )
    with sub_r:
        # 담당자 변경은 등록자(author)가 관리 (담당자 지정/재지정)
        if is_author:
            with st.popover("변경", width="stretch"):
                new_assignee = st.text_input(
                    "담당자 이름",
                    value=issue.assignee or "",
                    placeholder="담당자는 필수입니다",
                    key="assignee_input",
                )
                if st.button("저장", key="assignee_save_btn", type="primary"):
                    # 담당자 필수: 빈 입력은 거부
                    cleaned_assignee = (new_assignee or "").strip()
                    if not cleaned_assignee:
                        st.error("담당자는 필수입니다.")
                        st.stop()
                    try:
                        repository.update_assignee(
                            item_id,
                            cleaned_assignee,
                            user["name"],
                        )
                        st.toast("담당자가 변경되었습니다", icon="✅")
                        st.rerun()
                    except Exception as exc:  # pragma: no cover - 방어적
                        st.error(f"변경 실패: {exc}")
        else:
            # 1번: 등록자가 아니면 비활성 [변경] 버튼으로 자리를 채워 다른 메타
            # 카드(상태/긴급도/카테고리)와 높이를 맞춘다. (담당자 변경은 등록자만)
            st.button(
                "변경",
                key=f"assignee_change_disabled_{item_id}",
                disabled=True,
                width="stretch",
                help="담당자는 등록자만 변경할 수 있습니다.",
            )

with meta_c2:
    # 긴급도 표시 + 변경 popover (프로젝트 변경 자리를 대체)
    from ui.theme import URGENCY_LABELS as _URG_LABELS
    _card2 = st.container(border=True)
    with _card2:
        sub_l, sub_r = st.columns([2, 1])
    with sub_l:
        _urg_label = _URG_LABELS.get(issue.urgency.value, issue.urgency.value)
        st.markdown(
            f'<div style="font-size:0.9em;color:#374151;line-height:1.9;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f"긴급도: {urgency_badge_html(issue.urgency.value)}</div>",
            unsafe_allow_html=True,
        )
    with sub_r:
        with st.popover("수정", width="stretch"):
            _urg_options = [u.value for u in Urgency]
            _urg_default_idx = (
                _urg_options.index(issue.urgency.value)
                if issue.urgency.value in _urg_options
                else 0
            )
            new_urg = st.radio(
                "긴급도",
                options=_urg_options,
                format_func=lambda v: _URG_LABELS.get(v, v),
                index=_urg_default_idx,
                key=f"detail_urg_radio_{item_id}",
                horizontal=True,
            )
            if st.button(
                "저장",
                key=f"detail_urg_save_{item_id}",
                type="primary",
            ):
                try:
                    repository.update_urgency(item_id, new_urg, user["name"])
                    st.toast("긴급도가 변경되었습니다", icon="✅")
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"변경 실패: {exc}")

with meta_c3:
    _card3 = st.container(border=True)
    with _card3:
        sub_l, sub_r = st.columns([3, 2])
    with sub_l:
        st.markdown(
            f'<div style="font-size:0.9em;color:#374151;line-height:1.9;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" '
            f'title="{_cat_display}">'
            f"카테고리: <b>{_cat_display}</b></div>",
            unsafe_allow_html=True,
        )
    with sub_r:
        with st.popover("수정", width="stretch"):
            _NONE_C = "(없음)"

            # 프로젝트별 카테고리 풀: 사이드바 [⚙ 설정] 에서 명시 등록된 항목만 노출.
            # 직접 입력은 그대로 허용.
            if issue.project:
                _cats = ps_mod.list_project_categories(issue.project)
                _all_l1 = _cats.get("l1", [])
                _all_l2 = _cats.get("l2", [])
                _all_l3 = _cats.get("l3", [])
            else:
                _all_l1 = _all_l2 = _all_l3 = []

            # 단순화: 각 단계마다 [기존 selectbox] + [직접 입력 text_input] 항상 노출.
            # text_input 에 값이 있으면 그 값 우선, 없으면 selectbox 값.
            st.caption("기존에서 고르거나 직접 입력하세요. 직접 입력값이 우선합니다.")

            # L1
            l1_opts = [_NONE_C] + _all_l1
            l1_default = (
                l1_opts.index(issue.category_l1)
                if issue.category_l1 and issue.category_l1 in l1_opts
                else 0
            )
            c1a, c1b = st.columns(2)
            with c1a:
                l1_pick = st.selectbox(
                    "대분류 (기존)",
                    options=l1_opts,
                    index=l1_default,
                    key="cat_edit_l1",
                )
            with c1b:
                l1_typed = st.text_input(
                    "대분류 (직접 입력)",
                    value="",
                    key="cat_edit_l1_typed",
                    placeholder="비우면 위 선택값 사용",
                )
            new_l1 = (
                l1_typed.strip()
                or (None if l1_pick == _NONE_C else l1_pick)
            ) or None

            # L2 — 평면 옵션 (대분류와 무관하게 모든 unique 중분류)
            l2_opts = [_NONE_C] + _all_l2
            l2_default = (
                l2_opts.index(issue.category_l2)
                if issue.category_l2 and issue.category_l2 in l2_opts
                else 0
            )
            c2a, c2b = st.columns(2)
            with c2a:
                l2_pick = st.selectbox(
                    "중분류 (기존)",
                    options=l2_opts,
                    index=l2_default,
                    key="cat_edit_l2",
                )
            with c2b:
                l2_typed = st.text_input(
                    "중분류 (직접 입력)",
                    value="",
                    key="cat_edit_l2_typed",
                    placeholder="비우면 위 선택값 사용",
                )
            new_l2 = (
                l2_typed.strip()
                or (None if l2_pick == _NONE_C else l2_pick)
            ) or None

            # L3 — 평면 옵션 (대분류·중분류와 무관하게 모든 unique 소분류)
            l3_opts = [_NONE_C] + _all_l3
            l3_default = (
                l3_opts.index(issue.category_l3)
                if issue.category_l3 and issue.category_l3 in l3_opts
                else 0
            )
            c3a, c3b = st.columns(2)
            with c3a:
                l3_pick = st.selectbox(
                    "소분류 (기존)",
                    options=l3_opts,
                    index=l3_default,
                    key="cat_edit_l3",
                )
            with c3b:
                l3_typed = st.text_input(
                    "소분류 (직접 입력)",
                    value="",
                    key="cat_edit_l3_typed",
                    placeholder="비우면 위 선택값 사용",
                )
            new_l3 = (
                l3_typed.strip()
                or (None if l3_pick == _NONE_C else l3_pick)
            ) or None

            if st.button("카테고리 저장", key="cat_save_btn", type="primary"):
                try:
                    repository.update_categories(
                        item_id,
                        category_l1=new_l1,
                        category_l2=new_l2,
                        category_l3=new_l3,
                        actor=user["name"],
                    )
                    st.toast("카테고리가 저장되었습니다", icon="✅")
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"저장 실패: {exc}")

# --- (상태 변경은 위 '상태' 컬럼의 [변경] popover 로 일원화됨) -------------


# 태그 기능은 제거됨 — 카테고리(3 단계) 가 그 자리를 대체.
# 모델/저장소의 ``tags`` 필드는 옵션이라 그대로 둠 (옛 데이터 호환).


# ---------------------------------------------------------------------------
# 본문: 좌측 갤러리(1) + 우측 본문(2) 분할 레이아웃
# ---------------------------------------------------------------------------


@st.dialog("이미지 보기", width="large")
def _show_image_dialog(rel_path: str, filename: str) -> None:
    """원본 이미지 모달."""
    abs_path = _abs_image_path(rel_path)
    if abs_path.exists():
        st.image(str(abs_path), caption=filename, width="stretch")
    else:
        st.error(f"파일을 찾을 수 없습니다: {rel_path}")


# ---------------------------------------------------------------------------
# 본문: 3 분할 — [요청 AS-IS] | [설명·타임라인·코멘트] | [개발 TO-BE]
#   각 사이드 컬럼은 자기 구분(kind)의 사진만 보여주고, 그 컬럼에서 추가하면
#   자동으로 해당 kind 로 저장된다 (구분 선택 라디오 불필요).
# ---------------------------------------------------------------------------


def _render_image(idx: int, img_ref) -> None:
    """이미지/PDF 1장 렌더.

    - PDF: 미리보기 대신 다운로드 버튼.
    - 이미지: 표시 시도 → 실패(DRM 등)하면 안내. 어느 경우든 원본 다운로드 제공
      (DRM 으로 화면 표시가 막혀도 내려받아 확인할 수 있게 — 14번).
    """
    filename = Path(img_ref.file).name
    src_abs = _abs_image_path(img_ref.file)
    is_pdf = img_ref.file.lower().endswith(".pdf")

    if is_pdf:
        st.caption(f"📄 {filename} (PDF)")
        if src_abs.exists():
            st.download_button(
                "PDF 다운로드",
                data=src_abs.read_bytes(),
                file_name=filename,
                mime="application/pdf",
                key=f"dl_pdf_{idx}",
                width="stretch",
            )
        else:
            st.caption("(파일 없음)")
        with st.popover(
            "🗑 삭제", width="stretch", key=f"del_pdf_pop_{img_ref.file}"
        ):
            st.warning("이 PDF를 삭제할까요? 되돌릴 수 없습니다.")
            if st.button("삭제 확인", key=f"del_pdf_btn_{idx}", type="primary"):
                try:
                    repository.delete_image(item_id, idx, user["name"])
                    st.toast("삭제되었습니다", icon="🗑")
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"삭제 실패: {exc}")
        st.markdown("")
        return

    # 이미지 — 썸네일/원본 표시 (DRM 등으로 실패하면 안내).
    display_abs = src_abs
    if not display_abs.exists() and img_ref.thumb:
        display_abs = _abs_image_path(img_ref.thumb)
    shown = False
    if display_abs.exists():
        try:
            st.image(str(display_abs), width="stretch")
            shown = True
        except Exception:  # noqa: BLE001
            shown = False
    if not shown:
        st.caption("⚠ 이미지를 표시할 수 없습니다 (DRM 보호 등). 내려받아 확인하세요.")
    st.caption(filename)
    # 1번: 다운로드 / 원본 보기 / 삭제 를 한 행에 배치.
    _dlc, _viewc, _delc = st.columns(3)
    with _dlc:
        if src_abs.exists():
            st.download_button(
                "다운로드",
                data=src_abs.read_bytes(),
                file_name=filename,
                key=f"dl_img_{idx}",
                width="stretch",
            )
    with _viewc:
        if shown and st.button(
            "원본 보기", key=f"view_img_{idx}", width="stretch"
        ):
            _show_image_dialog(img_ref.file, filename)
    with _delc:
        # 잘못 첨부한 사진 삭제 (2단계 확인) — 요청/개발 공통.
        # 5번: 파일명으로 key 고정 → 삭제 후 인덱스가 밀려도 팝업이 다음 사진으로
        #      옮겨붙지 않고 함께 닫힘.
        with st.popover(
            "🗑 삭제", width="stretch", key=f"del_img_pop_{img_ref.file}"
        ):
            st.warning("이 사진을 삭제할까요? 되돌릴 수 없습니다.")
            if st.button(
                "삭제 확인", key=f"del_img_btn_{idx}", type="primary"
            ):
                try:
                    repository.delete_image(item_id, idx, user["name"])
                    st.toast("사진이 삭제되었습니다", icon="🗑")
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"삭제 실패: {exc}")
    st.markdown("")  # 이미지 사이 간격


def _images_of_kind(want_dev: bool) -> list[tuple[int, object]]:
    """want_dev=True → kind=='dev', False → 그 외(None/request, 옛 데이터 포함)."""
    out: list[tuple[int, object]] = []
    for _idx, _ref in enumerate(issue.images):
        if (getattr(_ref, "kind", None) == "dev") == want_dev:
            out.append((_idx, _ref))
    return out


def _render_uploader_for_kind(kind: str) -> None:
    """특정 구분(kind)의 이미지 업로더 (파일 + 클립보드). 한도·nonce 는 kind 별 독립."""
    remaining = MAX_IMAGES_PER_ITEM - len(issue.images)
    nonce_key = f"upload_nonce_{kind}_{item_id}"
    upload_nonce = st.session_state.setdefault(nonce_key, 0)
    label = "요청(AS-IS)" if kind == "request" else "개발(TO-BE)"
    # 5번 expander 제거 + 1번: 사진추가 헤더는 AS-IS/TO-BE 제목줄에 합침(여기선 생략).
    # 파일 업로더 dropzone 을 클립보드와 비슷한 높이로 (상세보기 한정).
    st.markdown(
        "<style>[data-testid='stFileUploaderDropzone']"
        "{min-height:80px !important;}</style>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        if remaining <= 0:
            st.warning(f"이미지 한도({MAX_IMAGES_PER_ITEM}장)에 도달했습니다.")
            return
        ext_list = sorted(e.lstrip(".") for e in ALLOWED_EXT)

        # 1번: 파일 업로드(좌) / 클립보드(우) 를 2 열로 나란히.
        _col_file, _col_paste = st.columns(2, gap="medium")

        with _col_file:
            uploaded = st.file_uploader(
                f"파일 업로드 (최대 {MAX_FILE_MB}MB, {','.join(ext_list)})",
                accept_multiple_files=True,
                type=ext_list,
                key=f"detail_upload_{kind}_{item_id}_{upload_nonce}",
            )
            if uploaded and st.button(
                "업로드",
                key=f"detail_upload_btn_{kind}_{item_id}_{upload_nonce}",
                type="primary",
                width="stretch",
            ):
                added = 0
                for uf in uploaded[:remaining]:
                    try:
                        data = uf.getbuffer().tobytes()
                        repository.add_image_from_bytes(
                            item_id, data, uf.name, user["name"], kind=kind
                        )
                        added += 1
                    except ValueError as exc:
                        st.error(f"{uf.name}: {exc}")
                    except Exception as exc:  # pragma: no cover
                        st.error(f"{uf.name}: 업로드 실패 — {exc}")
                if added:
                    st.toast(f"{added}장 추가되었습니다", icon="✅")
                    st.session_state[nonce_key] = upload_nonce + 1
                    st.rerun()

        with _col_paste:
            st.markdown("**클립보드 (Ctrl+V)** — 여러 번 가능")
            try:
                paste_data_url = paste_clipboard(
                    key=f"detail_paste_{kind}_{item_id}_{upload_nonce}",
                    height=80,
                )
            except Exception as exc:  # pragma: no cover - 컴포넌트 환경 의존
                paste_data_url = None
                st.caption(f"paste 컴포넌트 오류: {exc}")

            last_key = f"_detail_last_pasted_{kind}_{item_id}_{upload_nonce}"
            if paste_data_url and st.session_state.get(last_key) != paste_data_url:
                st.session_state[last_key] = paste_data_url
                try:
                    _img, _, _ = decode_image_data_url(paste_data_url)
                    repository.add_image_from_pil(
                        item_id, _img, "pasted.png", user["name"], kind=kind
                    )
                    st.toast("붙여넣기 이미지가 추가되었습니다", icon="✅")
                    st.session_state[nonce_key] = upload_nonce + 1
                    st.session_state.pop(last_key, None)
                    st.rerun()
                except ValueError as exc:
                    st.error(f"붙여넣기 실패: {exc}")
                except Exception as exc:  # pragma: no cover
                    st.error(f"붙여넣기 저장 실패: {exc}")


# 2번: 요청 / 설명 / 개발 3열 사이에 세로 디바이더(얇은 열 + 세로선).
asis_col, _dvA, body_col, _dvB, tobe_col = st.columns(
    [1, 0.04, 1.55, 0.04, 1], gap="small"
)
for _dv in (_dvA, _dvB):
    with _dv:
        st.markdown(
            '<div style="border-left:1px solid #D1D5DB;min-height:1280px;'
            'height:100%;width:0;margin:0 auto;"></div>',
            unsafe_allow_html=True,
        )

# ---- 좌측: 요청 (AS-IS) ----------------------------------------------------
with asis_col:
    _req_imgs = _images_of_kind(want_dev=False)
    st.markdown(
        f'<div style="margin-bottom:6px;padding:4px 10px;border-left:4px solid #3B82F6;'
        f'font-weight:700;color:#1E3A8A;">요청 (AS-IS) · {len(_req_imgs)}장'
        f'<span style="font-weight:400;font-size:0.8em;color:#6B7280;">'
        f" · 사진 추가 (남은 {MAX_IMAGES_PER_ITEM - len(issue.images)})</span></div>",
        unsafe_allow_html=True,
    )
    # 2번: 사진 추가를 이미지보다 위(요청 헤더 바로 아래)에 배치.
    _render_uploader_for_kind("request")
    if _req_imgs:
        for _idx, _ref in _req_imgs:
            _render_image(_idx, _ref)
    else:
        st.caption("요청(현황) 사진이 없습니다.")


# ---- 가운데: 설명 + 타임라인 + 코멘트 작성 ---------------------------------
with body_col:
    # 설명
    st.markdown("### 설명")
    if _edit_mode:
        # 편집 모드 — 설명을 원래 자리에서 바로 수정 (저장은 상단 [완료]).
        st.text_area(
            "설명",
            value=issue.description,
            height=220,
            key=f"edit_desc_{item_id}",
            label_visibility="collapsed",
        )
        st.caption("제목·설명을 수정한 뒤 상단의 [완료] 버튼을 누르면 저장됩니다.")
    elif issue.description.strip():
        with st.container(border=True):
            st.markdown(issue.description)
    else:
        st.caption("설명이 없습니다.")

    # 2번: 가장 최근 코멘트 1개를 설명과 코멘트작성 사이에 강조 표시.
    _recent = [
        c for c in repository.list_comments(item_id) if c.kind != "system"
    ]
    if _recent:
        _latest = max(_recent, key=lambda c: c.at)
        st.markdown(
            f'<div style="border-left:3px solid #6366F1;background:#EEF2FF;'
            f'padding:8px 12px;border-radius:6px;margin:10px 0;">'
            f'<div style="font-size:0.78em;color:#6B7280;margin-bottom:3px;">'
            f"💬 최근 코멘트 · {html.escape(str(_latest.author))}</div>"
            f'<div style="white-space:pre-wrap;font-size:1.0em;font-weight:500;'
            f'color:#1F2937;line-height:1.5;">{html.escape(_latest.body)}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    # 8번: 코멘트 작성을 타임라인 위로 배치
    st.markdown("### 코멘트 작성")
    comment_nonce = st.session_state.setdefault(f"comment_nonce_{item_id}", 0)
    with st.form(key=f"comment_form_{item_id}_{comment_nonce}", clear_on_submit=True):
        body = st.text_area(
            "내용 (마크다운 지원)",
            height=120,
            key=f"comment_body_{item_id}_{comment_nonce}",
            placeholder="작성 후 [등록] 버튼을 눌러주세요.",
        )
        submit_comment = st.form_submit_button("등록", type="primary")
        if submit_comment:
            if not body or not body.strip():
                st.error("코멘트 내용을 입력해주세요.")
            else:
                try:
                    _cmt_role = Role.developer if is_assignee else Role.reviewer
                    repository.add_comment(
                        item_id, _user_name, _cmt_role, body.strip()
                    )
                    st.toast("코멘트가 등록되었습니다", icon="✅")
                    st.session_state[f"comment_nonce_{item_id}"] = comment_nonce + 1
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:  # pragma: no cover
                    st.error(f"코멘트 등록 실패: {exc}")

    # 코멘트 타임라인 — 8번: 최신 코멘트가 위로(역순), 오래된 코멘트는 아래로.
    st.markdown("### 타임라인")
    comments: list[Comment] = repository.list_comments(item_id)
    comments.sort(key=lambda c: c.at, reverse=True)
    # 4번: 시스템 코멘트는 아래로 — 텍스트 코멘트를 먼저 보이게 (stable 정렬).
    comments.sort(key=lambda c: 1 if c.kind == "system" else 0)

    if not comments:
        st.caption("아직 코멘트가 없습니다.")
    else:
        for comment in comments:
            when = humanize(comment.at) if hasattr(comment.at, "year") else humanize_dt(comment.at)
            abs_when = _abs_tooltip_dt(comment.at)
            if comment.kind == "system":
                st.markdown(
                    f'<div style="border:1px dashed #9CA3AF;padding:8px 12px;'
                    f"background:#F9FAFB;border-radius:6px;margin:6px 0;"
                    f'color:#6B7280;font-size:0.9em;">'
                    f'<span title="{html.escape(abs_when)}">⚙ 시스템 · {html.escape(when)}</span>'
                    f" · {html.escape(comment.body)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                role_color = _role_color(comment.role)
                role_label = _role_label(comment.role)
                safe_comment_author = html.escape(str(comment.author))
                with st.container(border=True):
                    _ch, _ce, _cd = st.columns([6, 1, 1])
                    with _ch:
                        st.markdown(
                            f'<div style="font-size:0.9em;">'
                            f'<b style="color:{role_color};">{safe_comment_author}</b> '
                            f'<span style="color:#6B7280;">({role_label})</span> · '
                            f'<span style="color:#6B7280;" title="{html.escape(abs_when)}">{html.escape(when)}</span>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    with _ce:
                        # 코멘트 수정 (4번) — 본문을 고치면 '수정됨'으로 표시.
                        with st.popover(
                            "✏", help="코멘트 수정", key=f"edit_cmt_pop_{comment.id}"
                        ):
                            _new_body = st.text_area(
                                "내용 수정",
                                value=comment.body,
                                key=f"edit_cmt_ta_{comment.id}",
                                height=100,
                            )
                            if st.button(
                                "저장",
                                key=f"edit_cmt_btn_{comment.id}",
                                type="primary",
                            ):
                                try:
                                    repository.edit_comment(
                                        item_id, comment.id, _new_body, user["name"]
                                    )
                                    st.toast("코멘트가 수정되었습니다", icon="✏")
                                    st.rerun()
                                except Exception as exc:  # pragma: no cover
                                    st.error(f"수정 실패: {exc}")
                    with _cd:
                        # 코멘트 삭제 — 누구나, 2단계 확인 (audit 로그 기록).
                        # 5번: key 를 코멘트별로 고정 → 삭제 후 팝업이 다음 코멘트로
                        #      옮겨붙어 계속 떠 있는 현상 방지 (삭제와 함께 닫힘).
                        with st.popover(
                            "🗑", help="코멘트 삭제", key=f"del_cmt_pop_{comment.id}"
                        ):
                            st.warning("이 코멘트를 삭제할까요?")
                            if st.button(
                                "삭제 확인",
                                key=f"del_cmt_{comment.id}",
                                type="primary",
                            ):
                                try:
                                    repository.delete_comment(
                                        item_id, comment.id, user["name"]
                                    )
                                    st.toast("코멘트가 삭제되었습니다", icon="🗑")
                                    st.rerun()
                                except Exception as exc:  # pragma: no cover
                                    st.error(f"삭제 실패: {exc}")
                    # 3번: 줄바꿈(\n)을 그대로 보여준다 (markdown 은 줄바꿈 무시).
                    st.markdown(
                        f'<div style="white-space:pre-wrap;font-size:1.02em;'
                        f'font-weight:500;color:#1F2937;line-height:1.55;'
                        f'padding:2px 2px 10px;">'
                        f"{html.escape(comment.body)}</div>",
                        unsafe_allow_html=True,
                    )
                    if getattr(comment, "edited", False):
                        st.caption("✏ 수정됨")

    # 3번: 진행 단계 — 타임라인 아래로 이동 (이 항목이 거쳐온 상태 배지 체인).
    st.divider()
    st.markdown("#### 진행 단계")
    _hist = issue.status_history
    if _hist:
        _chips = []
        for _ev in _hist:
            _sv = _ev.status.value if hasattr(_ev.status, "value") else str(_ev.status)
            _chips.append(
                f'<span style="display:inline-block;background:'
                f'{STATUS_COLORS.get(_sv, "#9CA3AF")};color:#fff;padding:3px 10px;'
                f'border-radius:6px;font-size:0.85em;margin:2px 0;white-space:nowrap;">'
                f"{STATUS_LABELS.get(_sv, _sv)}</span>"
            )
        st.markdown(
            '<div style="line-height:2.4;">'
            + ' <span style="color:#9CA3AF;">→</span> '.join(_chips)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("진행 단계 기록이 없습니다.")


# ---- 우측: 개발 (TO-BE) ----------------------------------------------------
with tobe_col:
    _dev_imgs = _images_of_kind(want_dev=True)
    st.markdown(
        f'<div style="margin-bottom:6px;padding:4px 10px;border-left:4px solid #10B981;'
        f'font-weight:700;color:#065F46;">개발 (TO-BE) · {len(_dev_imgs)}장'
        f'<span style="font-weight:400;font-size:0.8em;color:#6B7280;">'
        f" · 사진 추가 (남은 {MAX_IMAGES_PER_ITEM - len(issue.images)})</span></div>",
        unsafe_allow_html=True,
    )
    # 2번: 사진 추가를 이미지보다 위(개발 헤더 바로 아래)에 배치.
    _render_uploader_for_kind("dev")
    if _dev_imgs:
        for _idx, _ref in _dev_imgs:
            _render_image(_idx, _ref)
    else:
        st.caption("개발(결과) 사진이 없습니다.")


# (삭제(보관)은 상단 우측 [🗑 삭제] popover 로 이동됨)
