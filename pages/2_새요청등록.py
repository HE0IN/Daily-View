"""새 요청 등록 페이지 — docs/03_ui_design.md 3.6 + docs/07_scenarios.md 7.5.

좌우 분할 레이아웃: 좌측 = 이미지 입력 / 우측 = 폼.
카테고리는 우측 컬럼 안 / st.form 바깥에 두어 종속 selectbox 즉시 반영.
폼 nonce 패턴으로 위젯 key 를 회전시켜 제출 후 입력 초기화.

이미지 입력은 두 경로:
  1) file_uploader (다중) — 항상 동작
  2) 정식 paste_clipboard 컴포넌트 — HTTP+IP 환경에서도 단일 클릭 paste 동작
"""

from __future__ import annotations

import streamlit as st
from PIL import Image as PILImage

from components.paste_clipboard import paste_clipboard
from core import paths, project_settings as ps_mod, repository
from core.images import (
    ALLOWED_EXT,
    MAX_FILE_MB,
    MAX_IMAGES_PER_ITEM,
    decode_image_data_url,
)
from core.models import Role, Urgency
from ui.auth import get_or_init_user, render_project_selector, require_user

# 페이지 내 호출 호환 — 기존 변수명 유지
_decode_pasted_b64 = decode_image_data_url


# ---------------------------------------------------------------------------
# 페이지 설정 + 부트스트랩
# ---------------------------------------------------------------------------

# 공통 처리(set_page_config·부트스트랩·사용자식별·프로젝트선택)는
# 진입점 app.py(라우터)가 수행한다. 이 페이지는 session_state 만 읽는다.
user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]


# ---------------------------------------------------------------------------
# 헤더 + 안내
# ---------------------------------------------------------------------------

# 사이드바 프로젝트 선택기 (사용자별). 사용자 ↔ 프로젝트 컨텍스트는
# 사이드바에서만 변경되며, 새 등록 시 자동으로 그 프로젝트가 적용된다.
current_project: str | None = st.session_state.get("_current_project")

st.title("새 요청 등록")

# 프로젝트 미선택 시 새 등록 차단. 사용자가 사이드바에서 프로젝트를 먼저
# 선택/추가해야 한다 — "이미 프로젝트가 정해져 있다" 는 전제 강제.
if not current_project:
    st.warning(
        "먼저 좌측 사이드바에서 **프로젝트** 를 선택하거나 추가해주세요. "
        "새 요청은 현재 선택된 프로젝트에 등록됩니다."
    )
    st.stop()

st.caption(f"프로젝트 **{current_project}** 에 등록됩니다.")


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
    # 등록자(author)는 담당 개발자 후보에서 제외한다 — 요청 등록은 주로
    # 검토자가 하므로, author 를 후보에 넣으면 검토자가 기본 담당자로 잡힌다.
    # 담당자 후보는 '실제로 담당했던 사람(assignee)' 만으로 한정.
known_names.discard(name)  # 자기 자신도 제외
# 담당자 필수화: "(미지정)" 옵션을 제거하여 None 저장이 불가능하도록 함.
# known_names 가 비어있으면 ["(직접 입력)"] 만 남아 사용자가 직접 입력을 강제받는다.
assignee_options = sorted(known_names) + ["(직접 입력)"]

# 직전에 지정한 담당자를 기본값으로 — "두 명만 쓰는" 환경에선 매번 같은 사람이라
# 매 등록마다 다시 고르게 하는 건 번거롭다. 직전 값이 후보에 없으면 첫 번째.
_last_assignee = st.session_state.get("_last_assignee")
if _last_assignee and _last_assignee in assignee_options:
    _default_assignee_idx = assignee_options.index(_last_assignee)
else:
    _default_assignee_idx = 0  # 첫 번째 담당자 (또는 "(직접 입력)")


# ---------------------------------------------------------------------------
# 카테고리 — 옵션은 프로젝트별 project_settings 에서 가져옴 (아래 우측 폼 영역)
# ---------------------------------------------------------------------------

_NONE = "(선택 안 함)"


def _resolve_category(level_key: str, options: list[str]) -> str | None:
    """selectbox 를 위, text_input 을 아래로 배치 (좁은 컬럼에 적합).

    text_input 이 비어있지 않으면 그 값을, 아니면 selectbox 의 선택값을 사용.
    selectbox 에서 (선택 안 함) 을 고르고 text_input 도 비었으면 None.
    """
    pick = st.selectbox(
        f"{level_key} (기존)",
        options=options,
        key=f"new_cat_{level_key}_select_{nonce}",
    )
    manual = st.text_input(
        f"{level_key} (직접 입력)",
        key=f"new_cat_{level_key}_input_{nonce}",
        placeholder="새 카테고리",
    )
    manual_clean = (manual or "").strip()
    if manual_clean and pick != _NONE:
        st.warning(
            f"{level_key}: 기존 선택과 직접 입력이 모두 채워졌습니다. "
            f"하나만 사용하세요 (직접 입력값을 우선 적용합니다)."
        )
    if manual_clean:
        return manual_clean
    if pick == _NONE:
        return None
    return pick


# ---------------------------------------------------------------------------
# 좌우 분할 — 좌측: 이미지 / 우측: 카테고리 + 폼
# ---------------------------------------------------------------------------

left, right = st.columns([1, 1], gap="large")


# ---------------------------------------------------------------------------
# 좌측: 이미지 입력 (file_uploader + paste-button + 미리보기)
# ---------------------------------------------------------------------------

with left:
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

    # 클립보드 붙여넣기 — 정식 declare_component (HTTP+IP 환경 단일 클릭 동작).
    # paste 이벤트 사용 → Secure Context 무관. iframe ↔ Python 양방향 통신을
    # 통해 paste 결과 (base64 dataURL) 를 직접 받음. 새 paste 가 들어올 때마다
    # *누적 리스트* 에 추가 → 사용자가 여러 장 paste 가능.
    with img_col2:
        st.markdown("**클립보드 (Ctrl+V)** — 여러 번 가능")
        try:
            paste_data_url = paste_clipboard(key=f"new_paste_v2_{nonce}")
        except Exception as exc:  # pragma: no cover - 컴포넌트 환경 의존
            paste_data_url = None
            st.caption(f"paste 컴포넌트 오류: {exc}")

    # 누적 리스트 키
    _last_pasted_key = f"_last_pasted_v2_{nonce}"
    _pasted_list_key = f"_decoded_paste_images_{nonce}"

    # 새 dataURL 이 들어오면 (이전과 다르면) 누적 리스트에 append.
    # rerun 마다 같은 dataURL 이 반복 반환되니 중복 추가 방지를 위해 비교.
    if paste_data_url and st.session_state.get(_last_pasted_key) != paste_data_url:
        st.session_state[_last_pasted_key] = paste_data_url
        try:
            _img, _, _ = _decode_pasted_b64(paste_data_url)
            existing_paste = list(st.session_state.get(_pasted_list_key, []))
            existing_paste.append(_img)
            st.session_state[_pasted_list_key] = existing_paste
        except Exception as exc:  # noqa: BLE001
            st.error(
                f"붙여넣기 이미지를 처리할 수 없습니다. DRM(문서보안)으로 보호된 "
                f"화면·이미지는 붙여넣기가 차단될 수 있습니다. ({exc})"
            )

    # 누적된 paste 이미지 리스트
    paste_images: list[PILImage.Image] = list(
        st.session_state.get(_pasted_list_key, [])
    )

    # paste 리스트 초기화 버튼 (사용자가 잘못 paste 한 경우)
    if paste_images:
        if st.button(
            f"클립보드 이미지 비우기 ({len(paste_images)}장)",
            key=f"new_paste_clear_{nonce}",
            width="stretch",
        ):
            st.session_state.pop(_pasted_list_key, None)
            st.session_state.pop(_last_pasted_key, None)
            st.rerun()

    # 미리보기
    preview_files: list = list(uploaded_files or [])
    preview_total = len(preview_files) + len(paste_images)
    if preview_total:
        st.caption(f"미리보기 — {preview_total}장")
        cols = st.columns(min(preview_total, 4))
        idx = 0
        for i, p_img in enumerate(paste_images, start=1):
            with cols[idx % len(cols)]:
                st.image(p_img, caption=f"(클립보드 #{i})", width="stretch")
            idx += 1
        for f in preview_files:
            with cols[idx % len(cols)]:
                st.image(f, caption=f.name, width="stretch")
            idx += 1


# ---------------------------------------------------------------------------
# 우측: 카테고리 (폼 바깥) + 본 폼
# ---------------------------------------------------------------------------

with right:
    # 프로젝트는 사이드바에서 이미 선택됨 — 폼 내 입력 X.
    # current_project 가 그대로 등록 시점에 사용됨.
    proj_value = current_project

    # ------- 카테고리 (st.form 바깥, 종속 selectbox 즉시 반영) -------
    st.markdown("##### 카테고리")
    st.caption(
        "사이드바 [⚙ 설정] 에서 추가한 카테고리만 옵션으로 노출됩니다. 직접 입력도 가능."
    )

    # 프로젝트별 카테고리 풀: 사이드바 [⚙ 설정] 에서 명시 등록된 항목만 노출.
    # 직접 입력은 그대로 허용 — 단, 자동 등록되지는 않음.
    if current_project:
        _cats = ps_mod.list_project_categories(current_project)
        _all_l1 = _cats.get("l1", [])
        _all_l2 = _cats.get("l2", [])
        _all_l3 = _cats.get("l3", [])
    else:
        _all_l1 = _all_l2 = _all_l3 = []

    l1_options = [_NONE] + _all_l1
    l2_options = [_NONE] + _all_l2
    l3_options = [_NONE] + _all_l3

    cat_c1, cat_c2, cat_c3 = st.columns(3, gap="small")
    with cat_c1:
        cat_l1 = _resolve_category("대분류", l1_options)
    with cat_c2:
        cat_l2 = _resolve_category("중분류", l2_options)
    with cat_c3:
        cat_l3 = _resolve_category("소분류", l3_options)

    # ------- 본 폼 -------
    st.markdown("##### 요청 내용")
    with st.form(key=f"new_request_form_{nonce}", clear_on_submit=False):
        title_input = st.text_input(
            "제목 *",
            max_chars=120,
            key=f"new_title_{nonce}",
            placeholder="간단명료한 한 줄 요약",
        )
        description_input = st.text_area(
            "설명",
            height=180,
            key=f"new_desc_{nonce}",
            placeholder=(
                "마크다운 지원 — 재현 절차 / 기대 동작 / 실제 동작 등을 적으면 좋습니다.\n"
                "비워둬도 됩니다."
            ),
        )

        # 긴급도 4 단계 — 라벨은 ui.theme.URGENCY_LABELS 사용 (백엔드 갱신 반영)
        from ui.theme import URGENCY_LABELS as _URGENCY_LABELS
        _urg_options = [u.value for u in Urgency]
        urgency_value = st.radio(
            "긴급도 *",
            options=_urg_options,
            format_func=lambda v: _URGENCY_LABELS.get(v, v),
            horizontal=True,
            # 4 단계 [critical, high, normal, low] 중 default 는 "중" (normal)
            index=_urg_options.index("normal") if "normal" in _urg_options else 0,
            key=f"new_urgency_{nonce}",
        )

        assignee_choice = st.selectbox(
            "담당 개발자",
            options=assignee_options,
            index=_default_assignee_idx,  # 직전 등록 담당자가 기본값 (없으면 미지정)
            key=f"new_assignee_select_{nonce}",
        )

        assignee_manual = st.text_input(
            "담당자 직접 입력",
            key=f"new_assignee_manual_{nonce}",
            placeholder="위에서 (직접 입력) 선택 시 — 후보 목록에 없는 새 담당자만 사용",
        )

        submit = st.form_submit_button("등록", type="primary", width="stretch")


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

    if not title:
        st.error("제목은 필수입니다.")
        st.stop()

    # 담당자 결정 — 미지정 옵션을 제거했으므로 항상 값이 있어야 한다.
    final_assignee: str | None = None
    if assignee_choice == "(직접 입력)":
        manual = (assignee_manual or "").strip()
        final_assignee = manual or None
    else:
        final_assignee = (assignee_choice or "").strip() or None

    # 담당자 필수 검증: 빈 값이면 등록 차단
    if not final_assignee:
        st.error("담당 개발자를 지정해주세요.")
        st.stop()

    # 등록자는 항상 '등록자' 권한 (역할 폐기) → author_role 은 reviewer 고정.
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
            category_l1=cat_l1,
            category_l2=cat_l2,
            category_l3=cat_l3,
            project=proj_value,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"등록 실패: {exc}")
        st.stop()

    # 다음 등록을 위해 직전 담당자 기억 (final_assignee 가 None 이면 그대로 유지)
    if final_assignee:
        st.session_state["_last_assignee"] = final_assignee

    # 프로젝트는 사이드바에서 관리되므로 별도 갱신 불필요 — current_project 가
    # 그대로 _current_project session_state 값과 동일.

    # 2) 이미지 첨부 — 실패해도 이슈 자체는 살린다 (개별 메시지)
    image_errors: list[str] = []

    # 누적된 paste 이미지들 모두 첨부 (새 요청 = 문제 현황 → 요청/AS-IS)
    for i, p_img in enumerate(paste_images, start=1):
        try:
            repository.add_image_from_pil(
                issue.id, p_img, f"pasted_{i}.png", name, kind="request"
            )
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"클립보드 이미지 #{i} 실패: {exc}")

    for f in preview_files:
        try:
            data = bytes(f.getbuffer())
            repository.add_image_from_bytes(
                issue.id, data, f.name, name, kind="request"
            )
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"{f.name} 첨부 실패: {exc}")

    if image_errors:
        for msg in image_errors:
            st.warning(msg)
        st.info(
            "이미지가 안 올라가나요? DRM(문서보안)으로 보호된 화면·이미지는 "
            "캡처·붙여넣기·업로드가 차단될 수 있습니다."
        )

    # 3) 성공 토스트 + 폼 초기화 + 상세보기 이동
    st.toast("등록되었습니다", icon="✅")
    # 누적된 paste 이미지/last 캐시 제거 — 다음 폼에 재첨부되지 않도록.
    st.session_state.pop(f"_decoded_paste_images_{nonce}", None)
    st.session_state.pop(f"_last_pasted_v2_{nonce}", None)
    st.session_state["new_form_nonce"] = nonce + 1
    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
    st.session_state["_detail_item_id"] = issue.id
    st.session_state["_detail_origin"] = "pages/1_요청목록.py"
    st.query_params["id"] = issue.id
    st.switch_page("pages/3_상세보기.py")
