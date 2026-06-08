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
        return "검토자"
    if value == "developer":
        return "개발자"
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

# --- 1행: 목록으로 / ID ----------------------------------------------------
top_left, top_right = st.columns([4, 1])
with top_left:
    st.page_link("pages/1_요청목록.py", label="← 목록으로")
with top_right:
    st.markdown(
        f'<div style="text-align:right;color:#6B7280;font-size:0.85em;">'
        f"#{item_id}</div>",
        unsafe_allow_html=True,
    )

# --- 2행: 제목 + 긴급도 배지 / 우측 끝 삭제 버튼 ---------------------------
# XSS 방지: 모든 사용자 입력은 escape 후 HTML 으로 렌더
title_col, title_edit_col, title_del_col, title_purge_col = st.columns(
    [5.5, 1, 1, 1.3]
)
with title_col:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
        f"{urgency_badge_html(issue.urgency.value)}"
        f'<h2 style="margin:0;line-height:1.3;">{html.escape(issue.title)}</h2>'
        f"</div>",
        unsafe_allow_html=True,
    )
with title_edit_col:
    # 제목·설명 편집 — 누구나 가능(수정 기록은 audit 로그에 남음).
    if not issue.archived:
        with st.popover("✏ 편집", width="stretch"):
            _edit_title = st.text_input(
                "제목", value=issue.title, max_chars=120, key="edit_title_input"
            )
            _edit_desc = st.text_area(
                "설명 (마크다운)", value=issue.description, height=180,
                key="edit_desc_input",
            )
            if st.button("저장", type="primary", key="edit_save_btn"):
                try:
                    repository.update_issue_content(
                        item_id, _edit_title, _edit_desc, user["name"]
                    )
                    st.toast("수정되었습니다", icon="✅")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:  # pragma: no cover
                    st.error(f"수정 실패: {exc}")
with title_del_col:
    # 삭제(보관) — 제목 행 우측 끝. 누구나 가능(삭제 기록은 audit 로그에 남음).
    if issue.archived:
        st.caption("🗑 삭제됨")
    else:
        with st.popover("🗑 삭제", width="stretch"):
            st.warning("이 요청을 삭제(보관)하시겠습니까?")
            if st.button("삭제 확인", type="primary", key="del_confirm_title"):
                try:
                    repository.archive_issue(item_id, user["name"])
                    st.toast("삭제(보관)되었습니다", icon="🗑")
                    st.switch_page("pages/1_요청목록.py")
                except Exception as exc:  # pragma: no cover
                    st.error(f"삭제 실패: {exc}")
with title_purge_col:
    # 완전삭제 — 폴더 자체를 디스크에서 제거(복구 불가). 누구나, 2단계 확인.
    with st.popover("🔥 완전삭제", width="stretch"):
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

# 사용자 role 미리 계산 — meta_c4 의 [→ 완료] 버튼 노출 판정에 필요
try:
    user_role = Role(user["role"])
except Exception:
    user_role = Role.reviewer

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
            _allowed_all = allowed_transitions(issue.status, user_role)
            if not _allowed_all:
                st.caption("현재 상태에서 변경 가능한 항목이 없습니다.")
            for _ns in _allowed_all:
                _nl = STATUS_LABELS_KO.get(_ns, _ns.value)
                if st.button(
                    f"→ {_nl}",
                    key=f"detail_status_change_{_ns.value}",
                    width="stretch",
                ):
                    try:
                        repository.update_status(
                            item_id, _ns, user["name"], user_role
                        )
                        st.toast(f"상태가 '{_nl}'로 변경되었습니다", icon="✅")
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
            f'<div style="font-size:0.9em;color:#374151;padding-top:6px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f"등록: <b>{safe_author}</b> ({_role_label(issue.author_role)}) · "
            f'<span title="{html.escape(created_abs)}">{created_human}</span> · '
            f"담당: <b>{safe_assignee}</b></div>",
            unsafe_allow_html=True,
        )
    with sub_r:
        # 담당자 변경은 개발자만 (검토자에겐 표시만)
        if user_role == Role.developer:
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

with meta_c2:
    # 긴급도 표시 + 변경 popover (프로젝트 변경 자리를 대체)
    from ui.theme import URGENCY_LABELS as _URG_LABELS
    _card2 = st.container(border=True)
    with _card2:
        sub_l, sub_r = st.columns([2, 1])
    with sub_l:
        _urg_label = _URG_LABELS.get(issue.urgency.value, issue.urgency.value)
        st.markdown(
            f'<div style="font-size:0.9em;color:#374151;padding-top:6px;'
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
            f'<div style="font-size:0.9em;color:#374151;padding-top:6px;'
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
    """이미지 1장 렌더 (썸네일 우선, 원본 보기 버튼)."""
    display_rel = img_ref.file
    display_abs = _abs_image_path(display_rel)
    if not display_abs.exists() and img_ref.thumb:
        display_rel = img_ref.thumb
        display_abs = _abs_image_path(display_rel)
    if display_abs.exists():
        st.image(str(display_abs), width="stretch")
    else:
        st.caption("(이미지 파일 없음)")
    filename = Path(img_ref.file).name
    st.caption(filename)
    if st.button("원본 보기", key=f"view_img_{idx}", width="stretch"):
        _show_image_dialog(img_ref.file, filename)
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
    with st.expander(f"{label} 사진 추가 (남은 슬롯 {remaining})", expanded=False):
        if remaining <= 0:
            st.warning(f"이미지 한도({MAX_IMAGES_PER_ITEM}장)에 도달했습니다.")
            return
        ext_list = sorted(e.lstrip(".") for e in ALLOWED_EXT)

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

        st.markdown("**클립보드 (Ctrl+V)** — 여러 번 가능")
        try:
            paste_data_url = paste_clipboard(
                key=f"detail_paste_{kind}_{item_id}_{upload_nonce}"
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


asis_col, body_col, tobe_col = st.columns([1, 1.6, 1], gap="medium")

# ---- 좌측: 요청 (AS-IS) ----------------------------------------------------
with asis_col:
    _req_imgs = _images_of_kind(want_dev=False)
    st.markdown(
        f'<div style="margin-bottom:6px;padding:4px 10px;border-left:4px solid #3B82F6;'
        f'font-weight:700;color:#1E3A8A;">요청 (AS-IS) · {len(_req_imgs)}</div>',
        unsafe_allow_html=True,
    )
    if _req_imgs:
        for _idx, _ref in _req_imgs:
            _render_image(_idx, _ref)
    else:
        st.caption("요청(현황) 사진이 없습니다.")
    _render_uploader_for_kind("request")


# ---- 가운데: 설명 + 타임라인 + 코멘트 작성 ---------------------------------
with body_col:
    # 설명
    st.markdown("### 설명")
    if issue.description.strip():
        with st.container(border=True):
            st.markdown(issue.description)
    else:
        st.caption("설명이 없습니다.")

    # 코멘트 타임라인
    st.markdown("### 타임라인")

    comments: list[Comment] = repository.list_comments(item_id)
    comments.sort(key=lambda c: c.at)

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
                    st.markdown(
                        f'<div style="font-size:0.9em;">'
                        f'<b style="color:{role_color};">{safe_comment_author}</b> '
                        f'<span style="color:#6B7280;">({role_label})</span> · '
                        f'<span style="color:#6B7280;" title="{html.escape(abs_when)}">{html.escape(when)}</span>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(comment.body)

    # 코멘트 입력
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
                    repository.add_comment(
                        item_id, user["name"], user_role, body.strip()
                    )
                    st.toast("코멘트가 등록되었습니다", icon="✅")
                    st.session_state[f"comment_nonce_{item_id}"] = comment_nonce + 1
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:  # pragma: no cover
                    st.error(f"코멘트 등록 실패: {exc}")


# ---- 우측: 개발 (TO-BE) ----------------------------------------------------
with tobe_col:
    _dev_imgs = _images_of_kind(want_dev=True)
    st.markdown(
        f'<div style="margin-bottom:6px;padding:4px 10px;border-left:4px solid #10B981;'
        f'font-weight:700;color:#065F46;">개발 (TO-BE) · {len(_dev_imgs)}</div>',
        unsafe_allow_html=True,
    )
    if _dev_imgs:
        for _idx, _ref in _dev_imgs:
            _render_image(_idx, _ref)
    else:
        st.caption("개발(결과) 사진이 없습니다.")
    _render_uploader_for_kind("dev")


# (삭제(보관)은 상단 우측 [🗑 삭제] popover 로 이동됨)
