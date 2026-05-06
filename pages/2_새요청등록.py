"""새 요청 등록 페이지 — docs/03_ui_design.md 3.6 + docs/07_scenarios.md 7.5.

st.form 컨텍스트로 입력 보존 → 제출 시 검증 → repository.create_issue + 이미지 첨부.
폼 nonce 패턴으로 위젯 key 를 회전시켜 제출 후 입력 초기화.

이미지 입력은 file_uploader (다중) + streamlit_paste_button (1회 1장).
streamlit_paste_button 미설치 환경에서는 graceful 하게 안내만 표시.
"""

from __future__ import annotations

import streamlit as st

from core import paths, repository
from core.images import ALLOWED_EXT, MAX_FILE_MB, MAX_IMAGES_PER_ITEM
from core.models import Role, Urgency
from ui.auth import get_or_init_user, require_user

# streamlit_paste_button 은 옵션 의존성. 미설치/import 실패면 None.
try:  # pragma: no cover - 환경 의존
    from streamlit_paste_button import paste_image_button as _paste_button
except Exception:  # noqa: BLE001
    _paste_button = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 페이지 설정 + 부트스트랩
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="새 요청 등록 — Daily View",
    layout="wide",
    initial_sidebar_state="expanded",
)

paths.ensure_data_dirs()

get_or_init_user()
user = require_user()

name: str = user["name"]
role_str: str = user.get("role", "reviewer")


# ---------------------------------------------------------------------------
# 헤더 + 안내
# ---------------------------------------------------------------------------

st.title("새 요청 등록")

if role_str != "reviewer":
    st.warning("주로 검토자가 등록하지만 개발자도 가능합니다.")


# ---------------------------------------------------------------------------
# 폼 nonce — 제출 후 위젯 초기화용
# ---------------------------------------------------------------------------

st.session_state.setdefault("new_form_nonce", 0)
nonce: int = int(st.session_state["new_form_nonce"])


# ---------------------------------------------------------------------------
# 담당 개발자 후보 (인덱스 전체에서 unique 추출)
# ---------------------------------------------------------------------------

# 너무 복잡하지 않게 — 등장한 적이 있는 모든 author/assignee 이름을 후보로.
existing_entries = repository.list_issues(include_archived=True)
known_names: set[str] = set()
for e in existing_entries:
    if e.assignee:
        known_names.add(e.assignee)
    # 등록자도 다음 후보로 등장 가능 (개발자가 직접 등록한 경우 등).
    if e.author:
        known_names.add(e.author)
known_names.discard(name)  # 자기 자신은 후보에서 제외 (등록자=담당자 케이스 방지)
assignee_options = ["(미지정)"] + sorted(known_names) + ["(직접 입력)"]

# 직전에 지정한 담당자를 기본값으로 — "두 명만 쓰는" 환경에선 매번 같은 사람이라
# 매 등록마다 다시 고르게 하는 건 번거롭다. 직전 값이 후보에 없으면 (미지정).
_last_assignee = st.session_state.get("_last_assignee")
if _last_assignee and _last_assignee in assignee_options:
    _default_assignee_idx = assignee_options.index(_last_assignee)
else:
    _default_assignee_idx = 0  # (미지정)


# ---------------------------------------------------------------------------
# 카테고리 트리 (3 단계). 폼 바깥에 둬서 L1 → L2 → L3 종속 선택이 즉시 반영되게.
# ---------------------------------------------------------------------------

st.markdown("##### 카테고리")
st.caption(
    "기존 카테고리에서 고르거나 새로 입력하면 다음 등록부터 드롭다운에 추가됩니다. "
    "비워둬도 무방."
)

_cat_tree = repository.list_categories()  # {l1: {l2: {l3,...}}}
_NEW = "(새로 입력)"
_NONE = "(없음)"


def _category_picker(level_key: str, options: list[str]) -> tuple[str | None, str]:
    """selectbox + 옵션이 새 입력일 때 text_input 으로 자유 입력 받기.

    반환: (실제 값 or None, selectbox 표시값)
    """
    pick = st.selectbox(
        level_key,
        options=options,
        key=f"new_cat_{level_key}_{nonce}",
    )
    if pick == _NEW:
        new_val = st.text_input(
            f"{level_key} (새로 입력)",
            key=f"new_cat_{level_key}_input_{nonce}",
            placeholder="새 카테고리 이름",
        )
        return ((new_val or "").strip() or None), pick
    if pick == _NONE:
        return None, pick
    return pick, pick


cat_c1, cat_c2, cat_c3 = st.columns(3)

with cat_c1:
    l1_options = [_NONE] + sorted(_cat_tree.keys()) + [_NEW]
    cat_l1, l1_pick = _category_picker("대분류", l1_options)

with cat_c2:
    l2_subtree = _cat_tree.get(cat_l1, {}) if cat_l1 else {}
    l2_options = [_NONE] + sorted(l2_subtree.keys()) + [_NEW]
    cat_l2, l2_pick = _category_picker("중분류", l2_options)

with cat_c3:
    l3_set = l2_subtree.get(cat_l2, set()) if cat_l2 else set()
    l3_options = [_NONE] + sorted(l3_set) + [_NEW]
    cat_l3, l3_pick = _category_picker("소분류", l3_options)


# ---------------------------------------------------------------------------
# 이미지 입력 — 폼 바깥 (미리보기를 즉시 보이려면 form 바깥에 둬야 함)
# ---------------------------------------------------------------------------

st.markdown("##### 스크린샷")
st.caption(
    f"파일 업로드(다중 가능) 또는 클립보드 붙여넣기. "
    f"항목당 최대 {MAX_IMAGES_PER_ITEM}장, 1장당 {MAX_FILE_MB}MB 이내. "
    f"허용 확장자: {', '.join(sorted(ALLOWED_EXT))}"
)

img_col1, img_col2 = st.columns([1, 1])

# 파일 업로드
with img_col1:
    st.markdown("**파일에서**")
    uploaded_files = st.file_uploader(
        "이미지 업로드",
        type=["png", "jpg", "jpeg", "webp", "gif"],
        accept_multiple_files=True,
        key=f"new_files_{nonce}",
        label_visibility="collapsed",
    )

# 클립보드 붙여넣기
paste_image = None
with img_col2:
    st.markdown("**클립보드 (Ctrl+V)**")
    if _paste_button is None:
        st.caption("`streamlit-paste-button` 미설치 — 파일 업로드만 사용 가능합니다.")
    else:
        try:
            paste_result = _paste_button(
                label="붙여넣기",
                key=f"new_paste_{nonce}",
                text_color="#ffffff",
                background_color="#3B82F6",
                hover_background_color="#2563EB",
                errors="ignore",
            )
            if paste_result is not None and getattr(paste_result, "image_data", None) is not None:
                paste_image = paste_result.image_data
        except Exception as exc:  # pragma: no cover - 컴포넌트 환경 의존
            st.caption(f"붙여넣기 컴포넌트 오류: {exc}")

# 미리보기
preview_files: list = list(uploaded_files or [])
preview_total = len(preview_files) + (1 if paste_image is not None else 0)
if preview_total:
    st.caption(f"미리보기 — {preview_total}장")
    cols = st.columns(min(preview_total, 4))
    idx = 0
    if paste_image is not None:
        with cols[idx % len(cols)]:
            st.image(paste_image, caption="(클립보드)", use_container_width=True)
        idx += 1
    for f in preview_files:
        with cols[idx % len(cols)]:
            st.image(f, caption=f.name, use_container_width=True)
        idx += 1


# ---------------------------------------------------------------------------
# 본 폼
# ---------------------------------------------------------------------------

with st.form(key=f"new_request_form_{nonce}", clear_on_submit=False):
    title_input = st.text_input(
        "제목 *",
        max_chars=120,
        key=f"new_title_{nonce}",
        placeholder="간단명료한 한 줄 요약",
    )
    description_input = st.text_area(
        "설명 *",
        height=180,
        key=f"new_desc_{nonce}",
        help="마크다운 지원. 재현 절차/기대 동작/실제 동작을 적어주세요.",
    )

    fc1, fc2 = st.columns([1, 1])
    with fc1:
        urgency_value = st.radio(
            "긴급도 *",
            options=[u.value for u in Urgency],
            format_func=lambda v: {"high": "긴급", "normal": "보통", "low": "낮음"}[v],
            horizontal=True,
            index=1,  # 보통
            key=f"new_urgency_{nonce}",
        )
    with fc2:
        assignee_choice = st.selectbox(
            "담당 개발자",
            options=assignee_options,
            index=_default_assignee_idx,  # 직전 등록 담당자가 기본값 (없으면 미지정)
            key=f"new_assignee_select_{nonce}",
        )

    assignee_manual = st.text_input(
        "담당자 직접 입력",
        key=f"new_assignee_manual_{nonce}",
        placeholder="위에서 (직접 입력) 선택 시 사용",
        help="후보 목록에 없는 새로운 담당자를 지정할 때만 입력하세요.",
    )

    tags_input = st.text_input(
        "태그",
        key=f"new_tags_{nonce}",
        placeholder="login, auth (콤마로 구분)",
    )

    submit = st.form_submit_button("등록", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# 폼 밖: 취소 링크
# ---------------------------------------------------------------------------

if st.button("취소", key=f"new_cancel_{nonce}"):
    st.switch_page("pages/1_요청목록.py")


# ---------------------------------------------------------------------------
# 제출 처리
# ---------------------------------------------------------------------------

if submit:
    title = (title_input or "").strip()
    description = (description_input or "").strip()

    if not title or not description:
        st.error("제목과 설명은 필수입니다.")
        st.stop()

    # 담당자 결정
    final_assignee: str | None = None
    if assignee_choice == "(미지정)":
        final_assignee = None
    elif assignee_choice == "(직접 입력)":
        manual = (assignee_manual or "").strip()
        final_assignee = manual or None
    else:
        final_assignee = assignee_choice

    # 태그 파싱
    tags = [t.strip() for t in (tags_input or "").split(",") if t.strip()]

    # 역할 정규화 (저장된 user["role"] 은 문자열 "reviewer"/"developer")
    try:
        author_role = Role(role_str)
    except ValueError:
        author_role = Role.reviewer

    # 1) 이슈 생성
    try:
        issue = repository.create_issue(
            title=title,
            description=description,
            urgency=Urgency(urgency_value),
            author=name,
            author_role=author_role,
            assignee=final_assignee,
            tags=tags,
            category_l1=cat_l1,
            category_l2=cat_l2,
            category_l3=cat_l3,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"등록 실패: {exc}")
        st.stop()

    # 다음 등록을 위해 직전 담당자 기억 (final_assignee 가 None 이면 그대로 유지)
    if final_assignee:
        st.session_state["_last_assignee"] = final_assignee

    # 2) 이미지 첨부 — 실패해도 이슈 자체는 살린다 (개별 메시지)
    image_errors: list[str] = []

    if paste_image is not None:
        try:
            repository.add_image_from_pil(
                issue.id, paste_image, "pasted.png", name
            )
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"클립보드 이미지 실패: {exc}")

    for f in preview_files:
        try:
            data = bytes(f.getbuffer())
            repository.add_image_from_bytes(issue.id, data, f.name, name)
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"{f.name} 첨부 실패: {exc}")

    if image_errors:
        for msg in image_errors:
            st.warning(msg)

    # 3) 성공 토스트 + 폼 초기화 + 상세보기 이동
    st.toast("등록되었습니다", icon="✅")
    st.session_state["new_form_nonce"] = nonce + 1
    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
    st.session_state["_detail_item_id"] = issue.id
    st.query_params["id"] = issue.id
    st.switch_page("pages/3_상세보기.py")
