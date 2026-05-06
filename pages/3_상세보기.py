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
# 상단: [목록으로] / 항목 ID
# ---------------------------------------------------------------------------

top_left, top_right = st.columns([4, 1])
with top_left:
    st.page_link("pages/1_요청목록.py", label="← 목록으로")
with top_right:
    st.markdown(
        f'<div style="text-align:right;color:#6B7280;font-size:0.85em;">'
        f"#{item_id}</div>",
        unsafe_allow_html=True,
    )

# 제목 + 긴급도 배지 — XSS 방지: 모든 사용자 입력은 escape 후 HTML 으로 렌더
title_col, badge_col = st.columns([5, 1])
with title_col:
    st.markdown(
        f'<h2 style="margin-bottom:0.2em;">{html.escape(issue.title)}</h2>',
        unsafe_allow_html=True,
    )
with badge_col:
    st.markdown(
        f'<div style="margin-top:18px;text-align:right;">'
        f"{urgency_badge_html(issue.urgency.value)}</div>",
        unsafe_allow_html=True,
    )

# 메타 정보 — XSS 방지: author / assignee 는 escape 후 보간
created_human = humanize_dt(issue.created_at)
created_abs = _abs_tooltip_dt(issue.created_at)
safe_author = html.escape(str(issue.author))
safe_assignee = html.escape(str(issue.assignee)) if issue.assignee else "미배정"
st.markdown(
    f'<div style="font-size:0.9em;color:#374151;">'
    f"등록: <b>{safe_author}</b> ({_role_label(issue.author_role)}) · "
    f'<span title="{html.escape(created_abs)}">{created_human}</span> · '
    f"담당: <b>{safe_assignee}</b>"
    f"</div>",
    unsafe_allow_html=True,
)

# 담당자 변경 expander
with st.expander("담당자 변경", expanded=False):
    with st.form(key="assignee_form", clear_on_submit=False):
        new_assignee = st.text_input(
            "담당자 이름",
            value=issue.assignee or "",
            placeholder="비워두면 미배정",
            key="assignee_input",
        )
        submit = st.form_submit_button("변경", type="primary")
        if submit:
            try:
                repository.update_assignee(
                    item_id,
                    new_assignee.strip() or None,
                    user["name"],
                )
                st.toast("담당자가 변경되었습니다", icon="✅")
                st.rerun()
            except Exception as exc:  # pragma: no cover - 방어적
                st.error(f"변경 실패: {exc}")

# 상태 배지 + SLA 배너
st.markdown(
    f'<div style="margin-top:8px;">상태: {status_badge_html(issue.status.value)}</div>',
    unsafe_allow_html=True,
)

# SLA 배너
if is_sla_violated(issue.urgency.value, issue.created_at, issue.status.value):
    st.error("⚠ SLA 위반: 첫 응답 시간이 초과되었습니다.")
elif is_sla_warning(issue.urgency.value, issue.created_at, issue.status.value):
    st.warning("⏳ SLA 임박: 첫 응답 시간 절반이 경과했습니다.")


# ---------------------------------------------------------------------------
# 상태 변경 영역 (권한 기반)
# ---------------------------------------------------------------------------

st.markdown("### 상태 변경")
try:
    user_role = Role(user["role"])
except Exception:
    user_role = Role.reviewer

allowed = allowed_transitions(issue.status, user_role)
if not allowed:
    st.caption("현재 상태에서 가능한 동작이 없습니다.")
else:
    cols = st.columns(min(len(allowed), 4))
    for idx, next_status in enumerate(allowed):
        next_label = STATUS_LABELS_KO.get(next_status, next_status.value)
        # closed 진입은 "검토 완료"로 라벨링 (검토자 전용 강조)
        btn_label = f"→ {next_label}"
        with cols[idx % len(cols)]:
            if st.button(
                btn_label,
                key=f"transition_{next_status.value}",
                use_container_width=True,
                type="primary" if next_status == Status.closed else "secondary",
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


# ---------------------------------------------------------------------------
# 태그
# ---------------------------------------------------------------------------

st.markdown("### 태그")
if issue.tags:
    # XSS 방지: 태그도 사용자 입력이므로 escape
    tag_html = " ".join(
        f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
        f'background:#E5E7EB;color:#374151;font-size:0.85em;margin-right:4px;">'
        f"#{html.escape(str(t))}</span>"
        for t in issue.tags
    )
    st.markdown(tag_html, unsafe_allow_html=True)
else:
    st.caption("태그 없음")

with st.expander("태그 수정", expanded=False):
    with st.form(key="tags_form", clear_on_submit=False):
        tag_input = st.text_input(
            "콤마(,)로 구분",
            value=", ".join(issue.tags),
            key="tags_input",
            placeholder="예: login, auth, bug",
        )
        submit_tags = st.form_submit_button("저장", type="primary")
        if submit_tags:
            new_tags = [t.strip() for t in tag_input.split(",") if t.strip()]
            try:
                repository.update_tags(item_id, new_tags, user["name"])
                st.toast("태그가 저장되었습니다", icon="✅")
                st.rerun()
            except Exception as exc:  # pragma: no cover
                st.error(f"태그 저장 실패: {exc}")


# ---------------------------------------------------------------------------
# 설명
# ---------------------------------------------------------------------------

st.markdown("### 설명")
if issue.description.strip():
    with st.container(border=True):
        st.markdown(issue.description)
else:
    st.caption("설명이 없습니다.")


# ---------------------------------------------------------------------------
# 이미지 갤러리
# ---------------------------------------------------------------------------

st.markdown(f"### 스크린샷 ({len(issue.images)})")


@st.dialog("이미지 보기", width="large")
def _show_image_dialog(rel_path: str, filename: str) -> None:
    """원본 이미지 모달."""
    abs_path = _abs_image_path(rel_path)
    if abs_path.exists():
        st.image(str(abs_path), caption=filename, use_container_width=True)
    else:
        st.error(f"파일을 찾을 수 없습니다: {rel_path}")


if issue.images:
    n_cols = min(4, len(issue.images))
    cols = st.columns(n_cols)
    for idx, img_ref in enumerate(issue.images):
        col = cols[idx % n_cols]
        with col:
            thumb_rel = img_ref.thumb or img_ref.file
            thumb_abs = _abs_image_path(thumb_rel)
            if thumb_abs.exists():
                st.image(str(thumb_abs), use_container_width=True)
            else:
                st.caption("(썸네일 없음)")
            filename = Path(img_ref.file).name
            st.caption(filename)
            if st.button("원본 보기", key=f"view_img_{idx}", use_container_width=True):
                _show_image_dialog(img_ref.file, filename)
else:
    st.caption("첨부된 이미지가 없습니다.")

# 이미지 추가
remaining = MAX_IMAGES_PER_ITEM - len(issue.images)
with st.expander(
    f"이미지 추가 (남은 슬롯: {remaining}/{MAX_IMAGES_PER_ITEM})",
    expanded=False,
):
    if remaining <= 0:
        st.warning(f"이미지 한도({MAX_IMAGES_PER_ITEM}장)에 도달했습니다.")
    else:
        # nonce 로 위젯 초기화
        upload_nonce = st.session_state.setdefault(f"upload_nonce_{item_id}", 0)
        ext_list = sorted(e.lstrip(".") for e in ALLOWED_EXT)

        col_upload, col_paste = st.columns([2, 1])
        with col_upload:
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

        with col_paste:
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


# ---------------------------------------------------------------------------
# 코멘트 타임라인
# ---------------------------------------------------------------------------

st.markdown("### 타임라인")

comments: list[Comment] = repository.list_comments(item_id)
# 시간순 정렬 (이미 append 순서가 시간순이지만 안전하게)
comments.sort(key=lambda c: c.at)

if not comments:
    st.caption("아직 코멘트가 없습니다.")
else:
    for comment in comments:
        when = humanize(comment.at) if hasattr(comment.at, "year") else humanize_dt(comment.at)
        abs_when = _abs_tooltip_dt(comment.at)
        if comment.kind == "system":
            # 시스템 코멘트: 점선 박스. body 안에 사용자 입력(담당자 이름 등)이
            # 포함될 수 있으므로 반드시 escape.
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
                # 일반 코멘트 본문은 마크다운 렌더 (unsafe_allow_html=False 기본).
                # Streamlit 의 markdown 은 <script> 등을 sanitize. 단 javascript:
                # 스킴 링크는 막아주지만 완전 신뢰는 어려움 — 추가 안전장치는
                # 향후 별도 패치(예: bleach) 에서 진행.
                st.markdown(comment.body)


# ---------------------------------------------------------------------------
# 코멘트 입력
# ---------------------------------------------------------------------------

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
# 추가 액션 — 보관 (검토자 본인이 author 인 closed 항목)
# ---------------------------------------------------------------------------

if (
    issue.status == Status.closed
    and not issue.archived
    and issue.author == user["name"]
):
    st.markdown("---")
    st.markdown("### 추가 액션")
    if st.button("📦 보관함으로 이동 (archive)", key="archive_btn"):
        try:
            repository.archive_issue(item_id, user["name"])
            st.toast("보관함으로 이동되었습니다", icon="✅")
            st.rerun()
        except Exception as exc:  # pragma: no cover
            st.error(f"보관 실패: {exc}")
elif issue.archived:
    st.info("이 항목은 보관함에 있습니다.")
