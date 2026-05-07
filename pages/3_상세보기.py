"""상세보기 페이지.

docs/03_ui_design.md 3.5 절을 따른다.
``?id=...`` query param 으로 진입한다.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import streamlit as st

from core import paths, repository
from core.clock import from_iso, humanize
from core.images import ALLOWED_EXT, MAX_FILE_MB, MAX_IMAGES_PER_ITEM
from core.models import Comment, Issue, Role, Status
from core.workflow import (
    STATUS_LABELS_KO,
    URGENCY_LABELS_KO,
    WorkflowError,
    allowed_transitions,
)
from ui.auth import get_or_init_user, require_user
from ui.components import humanize_dt
from ui.theme import (
    is_sla_violated,
    is_sla_warning,
    status_badge_html,
    urgency_badge_html,
)

# streamlit-paste-button 은 옵션 (HTTP 환경에서는 동작 안 할 수 있음)
try:
    from streamlit_paste_button import paste_image_button as _paste_image_button
except Exception:  # pragma: no cover - 라이브러리 미설치 시
    _paste_image_button = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 페이지 셋업
# ---------------------------------------------------------------------------

st.set_page_config(page_title="상세 — Daily View", layout="wide")
paths.ensure_data_dirs()
get_or_init_user()
user = require_user()

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
    st.page_link("pages/1_요청목록.py", label="요청목록으로 →")
    st.stop()

try:
    issue: Issue = repository.get_issue(item_id)
except paths.InvalidItemIdError:
    # path traversal 페이로드 등 형식이 어긋난 ID — 디스크 접근 자체가 차단됨
    st.error("잘못된 항목 ID 형식입니다.")
    st.page_link("pages/1_요청목록.py", label="요청목록으로 →")
    st.stop()
except FileNotFoundError:
    st.error(f"항목을 찾을 수 없습니다: #{html.escape(item_id)}")
    st.page_link("pages/1_요청목록.py", label="요청목록으로 →")
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
#   4행: SLA 배너 (있을 때만)
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

# --- 2행: 제목 + 긴급도 배지 / 상태 배지 ----------------------------------
# XSS 방지: 모든 사용자 입력은 escape 후 HTML 으로 렌더
title_col, status_col = st.columns([5, 2])
with title_col:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
        f"{urgency_badge_html(issue.urgency.value)}"
        f'<h2 style="margin:0;line-height:1.3;">{html.escape(issue.title)}</h2>'
        f"</div>",
        unsafe_allow_html=True,
    )
with status_col:
    st.markdown(
        f'<div style="text-align:right;margin-top:6px;font-size:0.95em;">'
        f"상태: {status_badge_html(issue.status.value)}</div>",
        unsafe_allow_html=True,
    )

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

# 4 개 메타 컬럼:
#   c1 = 등록자 + 담당자 + [변경] (한 그룹 — 붙어 있어야 함)
#   c2 = 프로젝트 + [변경]
#   c3 = 카테고리 + [수정]
#   c4 = [→ 완료] 버튼 (우측 끝, 짧게)
meta_c1, meta_c2, meta_c3, meta_c4 = st.columns([4, 2, 2, 1], gap="medium")

with meta_c1:
    sub_l, sub_r = st.columns([5, 1])
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
        with st.popover("변경", use_container_width=True):
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
    sub_l, sub_r = st.columns([3, 2])
    with sub_l:
        st.markdown(
            f'<div style="font-size:0.9em;color:#374151;padding-top:6px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" '
            f'title="{html.escape(_project_raw or "(미지정)")}">'
            f"프로젝트: {_proj_display_html}</div>",
            unsafe_allow_html=True,
        )
    with sub_r:
        with st.popover("변경", use_container_width=True):
            _all_projects = repository.list_projects()
            _NONE_PROJ = "(선택 안 함)"
            proj_options_d = [_NONE_PROJ] + _all_projects
            current_idx = (
                proj_options_d.index(issue.project)
                if issue.project and issue.project in proj_options_d
                else 0
            )
            sel = st.selectbox(
                "기존",
                options=proj_options_d,
                index=current_idx,
                key=f"detail_proj_sel_{item_id}",
            )
            new_text = st.text_input(
                "새로 입력",
                value=issue.project if issue.project and issue.project not in _all_projects else "",
                key=f"detail_proj_text_{item_id}",
                placeholder="비우면 위 선택값 사용",
            )
            if st.button(
                "저장",
                key=f"detail_proj_save_{item_id}",
                type="primary",
            ):
                if new_text.strip():
                    new_proj = new_text.strip()
                elif sel == _NONE_PROJ:
                    new_proj = None
                else:
                    new_proj = sel
                try:
                    repository.update_project(item_id, new_proj, user["name"])
                    st.toast("프로젝트가 변경되었습니다", icon="✅")
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"변경 실패: {exc}")

with meta_c3:
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
        with st.popover("수정", use_container_width=True):
            _cat_tree_detail = repository.list_categories()
            _NONE_C = "(없음)"

            # 평면 카테고리 옵션: 대분류 종속 없이 모든 unique 값을 노출.
            _all_l1, _all_l2, _all_l3 = repository.flat_categories(_cat_tree_detail)

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

with meta_c4:
    # 우측 끝 [→ 완료] 버튼: closed 전이 가능한 사용자에게만 노출.
    # "### 상태 변경" 섹션의 closed 버튼은 중복 노출 혼란 방지로 제거됨.
    if Status.closed in allowed_transitions(issue.status, user_role):
        # 라벨 위 빈 줄로 메타 텍스트 baseline 과 시각적 정렬.
        st.markdown(
            '<div style="height:0.25em;"></div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "→ 완료",
            key="finish_btn",
            type="primary",
            use_container_width=True,
        ):
            try:
                repository.update_status(
                    item_id, Status.closed, user["name"], user_role
                )
                st.toast("완료 처리되었습니다", icon="✅")
                st.rerun()
            except WorkflowError as exc:
                st.error(f"완료 처리 실패: {exc}")
            except Exception as exc:  # pragma: no cover - 방어적
                st.error(f"완료 처리 실패: {exc}")

# --- 4행: SLA 배너 (있을 때만) ---------------------------------------------
if is_sla_violated(issue.urgency.value, issue.created_at, issue.status.value):
    st.error("⚠ SLA 위반: 첫 응답 시간이 초과되었습니다.")
elif is_sla_warning(issue.urgency.value, issue.created_at, issue.status.value):
    st.warning("⏳ SLA 임박: 첫 응답 시간 절반이 경과했습니다.")


# ---------------------------------------------------------------------------
# 상태 변경 영역 (권한 기반) — 가로 한 줄 배치
#   주의: closed 전이는 헤더 우측 [→ 완료] 버튼으로 분리 노출되므로
#         이 섹션에서는 closed 만 제외한다 (중복 노출 방지).
# ---------------------------------------------------------------------------

allowed = [s for s in allowed_transitions(issue.status, user_role) if s != Status.closed]
if allowed:
    cols = st.columns(min(len(allowed), 4))
    for idx, next_status in enumerate(allowed):
        next_label = STATUS_LABELS_KO.get(next_status, next_status.value)
        btn_label = f"→ {next_label}"
        with cols[idx % len(cols)]:
            if st.button(
                btn_label,
                key=f"transition_{next_status.value}",
                use_container_width=True,
                type="secondary",
            ):
                try:
                    repository.update_status(
                        item_id, next_status, user["name"], user_role
                    )
                    st.toast(f"상태가 '{next_label}'로 변경되었습니다", icon="✅")
                    st.rerun()
                except WorkflowError as exc:
                    st.error(f"상태 변경 실패: {exc}")
                except Exception as exc:  # pragma: no cover - 방어적
                    st.error(f"상태 변경 실패: {exc}")


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
        st.image(str(abs_path), caption=filename, use_container_width=True)
    else:
        st.error(f"파일을 찾을 수 없습니다: {rel_path}")


gallery_col, body_col = st.columns([1, 2], gap="large")

# ---- 좌측: 스크린샷 + 이미지 추가 ------------------------------------------
with gallery_col:
    st.markdown(f"### 스크린샷 ({len(issue.images)})")
    if issue.images:
        # 좁은 컬럼이라 1열 세로 나열 — 원본을 컬럼 폭에 맞춰 자연스럽게 축소.
        for idx, img_ref in enumerate(issue.images):
            display_rel = img_ref.file
            display_abs = _abs_image_path(display_rel)
            if not display_abs.exists() and img_ref.thumb:
                display_rel = img_ref.thumb
                display_abs = _abs_image_path(display_rel)
            if display_abs.exists():
                st.image(str(display_abs), use_container_width=True)
            else:
                st.caption("(이미지 파일 없음)")
            filename = Path(img_ref.file).name
            st.caption(filename)
            if st.button("원본 보기", key=f"view_img_{idx}", use_container_width=True):
                _show_image_dialog(img_ref.file, filename)
            st.markdown("")  # 이미지 사이 간격
    else:
        st.caption("첨부된 이미지가 없습니다.")

    # 이미지 추가 expander
    remaining = MAX_IMAGES_PER_ITEM - len(issue.images)
    with st.expander(
        f"이미지 추가 (남은 슬롯: {remaining}/{MAX_IMAGES_PER_ITEM})",
        expanded=False,
    ):
        if remaining <= 0:
            st.warning(f"이미지 한도({MAX_IMAGES_PER_ITEM}장)에 도달했습니다.")
        else:
            upload_nonce = st.session_state.setdefault(f"upload_nonce_{item_id}", 0)
            ext_list = sorted(e.lstrip(".") for e in ALLOWED_EXT)

            uploaded = st.file_uploader(
                f"파일 업로드 (최대 {MAX_FILE_MB}MB, {','.join(ext_list)})",
                accept_multiple_files=True,
                type=ext_list,
                key=f"detail_upload_{item_id}_{upload_nonce}",
            )
            if uploaded and st.button(
                "업로드",
                key=f"detail_upload_btn_{item_id}_{upload_nonce}",
                type="primary",
                use_container_width=True,
            ):
                added = 0
                for uf in uploaded[:remaining]:
                    try:
                        data = uf.getbuffer().tobytes()
                        repository.add_image_from_bytes(
                            item_id, data, uf.name, user["name"]
                        )
                        added += 1
                    except ValueError as exc:
                        st.error(f"{uf.name}: {exc}")
                    except Exception as exc:  # pragma: no cover
                        st.error(f"{uf.name}: 업로드 실패 — {exc}")
                if added:
                    st.toast(f"{added}장 추가되었습니다", icon="✅")
                    st.session_state[f"upload_nonce_{item_id}"] = upload_nonce + 1
                    st.rerun()

            if _paste_image_button is not None:
                paste_result = _paste_image_button(
                    label="클립보드 붙여넣기",
                    key=f"detail_paste_{item_id}_{upload_nonce}",
                    background_color="#3B82F6",
                    errors="ignore",
                )
                if paste_result is not None and getattr(paste_result, "image_data", None) is not None:
                    try:
                        repository.add_image_from_pil(
                            item_id,
                            paste_result.image_data,
                            "pasted.png",
                            user["name"],
                        )
                        st.toast("붙여넣기 이미지가 추가되었습니다", icon="✅")
                        st.session_state[f"upload_nonce_{item_id}"] = upload_nonce + 1
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # pragma: no cover
                        st.error(f"붙여넣기 실패: {exc}")
            else:
                st.caption(
                    "(붙여넣기 라이브러리 미설치 — 파일 업로드만 가능)"
                )


# ---- 우측: 설명 + 타임라인 + 코멘트 작성 -----------------------------------
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


# ---------------------------------------------------------------------------
# 추가 액션 — 삭제(보관)
#   - 권한: 등록자(author == user.name) 또는 검토자(role == reviewer)
#   - 두 번 클릭(확인) 패턴: 첫 번째 클릭 시 confirm 플래그를 세우고
#     [삭제 확인] / [취소] 버튼을 노출. 두 번째 클릭 시 실제 archive 호출.
# ---------------------------------------------------------------------------

_can_delete = (issue.author == user["name"]) or (user_role == Role.reviewer)

if issue.archived:
    st.markdown("---")
    st.info("🗑 이 항목은 삭제(보관)되었습니다.")
elif _can_delete:
    st.markdown("---")
    st.markdown("### 추가 액션")

    _confirm_key = f"_confirm_delete_{item_id}"
    _confirming = bool(st.session_state.get(_confirm_key))

    if not _confirming:
        if st.button(
            "🗑 삭제(보관)",
            key="archive_btn",
        ):
            st.session_state[_confirm_key] = True
            st.rerun()
    else:
        st.warning("이 요청을 삭제(보관)하시겠습니까?")
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            if st.button(
                "확인 (삭제)",
                key="archive_confirm_btn",
                type="primary",
                use_container_width=True,
            ):
                try:
                    repository.archive_issue(item_id, user["name"])
                    st.session_state.pop(_confirm_key, None)
                    st.toast("삭제(보관)되었습니다", icon="🗑")
                    st.switch_page("pages/1_요청목록.py")
                except Exception as exc:  # pragma: no cover
                    st.session_state.pop(_confirm_key, None)
                    st.error(f"삭제 실패: {exc}")
        with cc2:
            if st.button(
                "취소",
                key="archive_cancel_btn",
                use_container_width=True,
            ):
                st.session_state.pop(_confirm_key, None)
                st.rerun()
