"""새 요청 등록 — 폼."""
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from streamlit_paste_button import paste_image_button as pbutton

from _data import add_item
from _ui import CSS, banner, now, render_sidebar_user


st.set_page_config(page_title="새 요청 등록 (프로토타입)", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

user = render_sidebar_user()
if not user:
    st.warning("좌측 사이드바에서 사용자 정보를 입력해주세요.")
    st.stop()

banner()

st.title("새 요청 등록")

# Show success banner if just created
if "last_created_id" in st.session_state:
    last_id = st.session_state["last_created_id"]
    st.success(f"등록되었습니다 — #{last_id}")
    bc1, bc2, _ = st.columns([1, 1, 3])
    with bc1:
        if st.button("목록으로 이동", type="primary", use_container_width=True):
            del st.session_state["last_created_id"]
            st.switch_page("pages/1_요청목록.py")
    with bc2:
        if st.button("계속 등록하기", use_container_width=True):
            del st.session_state["last_created_id"]
            st.rerun()
    st.divider()

nonce = st.session_state.get("new_form_nonce", 0)

# Image input area — clipboard paste OR file uploader. OUTSIDE form for live preview.
st.markdown("##### 스크린샷")
st.caption("Win+Shift+S로 캡처 후 [붙여넣기] 버튼을 눌러 클립보드 이미지를 추가하거나, 파일을 선택/드래그&드롭할 수 있습니다.")

ic1, ic2 = st.columns([1, 1])
with ic1:
    st.markdown("**클립보드에서 (Ctrl+V)**")
    paste_result = pbutton(
        label="붙여넣기",
        key=f"paste_btn_{nonce}",
        text_color="#ffffff",
        background_color="#3B82F6",
        hover_background_color="#2563EB",
        errors="ignore",
    )
with ic2:
    st.markdown("**파일에서**")
    uploaded_files = st.file_uploader(
        "이미지 업로드 (다중 선택 가능)",
        type=["png", "jpg", "jpeg", "webp", "gif"],
        accept_multiple_files=True,
        key=f"images_{nonce}",
        label_visibility="collapsed",
    )

# Combined preview
preview_items = []
if paste_result.image_data is not None:
    preview_items.append(("클립보드", paste_result.image_data))
if uploaded_files:
    for f in uploaded_files:
        preview_items.append((f.name, f))

if preview_items:
    st.caption(f"미리보기 — {len(preview_items)}장")
    cols = st.columns(min(len(preview_items), 4))
    for i, (name, img) in enumerate(preview_items):
        with cols[i % len(cols)]:
            st.image(img, caption=name, use_container_width=True)

with st.form(key=f"new_request_form_{nonce}"):
    title = st.text_input("제목 *", max_chars=120)
    description = st.text_area("설명 *", height=180, help="마크다운 지원")

    c1, c2 = st.columns(2)
    with c1:
        urgency = st.radio(
            "긴급도 *",
            options=["high", "normal", "low"],
            format_func=lambda u: {"high": "긴급", "normal": "보통", "low": "낮음"}[u],
            horizontal=True,
            index=1,
        )
    with c2:
        assignee = st.selectbox(
            "담당 개발자",
            options=["(미지정)", "이OO", "박OO", "최OO"],
        )

    tags_input = st.text_input("태그", placeholder="login, auth (콤마로 구분)")

    sc1, sc2, _ = st.columns([1, 1, 4])
    with sc1:
        cancel = st.form_submit_button("취소", use_container_width=True)
    with sc2:
        submit = st.form_submit_button("등록", type="primary", use_container_width=True)

if cancel:
    st.switch_page("app.py")

if submit:
    if not title.strip():
        st.error("제목은 필수입니다.")
    elif not description.strip():
        st.error("설명은 필수입니다.")
    else:
        new_id = f"{now().strftime('%Y-%m-%d')}_{secrets.token_hex(3)}"
        tags_list = [t.strip() for t in tags_input.split(",") if t.strip()] if tags_input else []
        new_item = {
            "id": new_id,
            "title": title.strip(),
            "description": description.strip(),
            "urgency": urgency,
            "status": "requested",
            "author": user["name"],
            "author_role": user["role"],
            "assignee": assignee if assignee != "(미지정)" else None,
            "created_at": now(),
            "updated_at": now(),
            "images_count": len(preview_items),
            "comments_count": 0,
            "tags": tags_list,
            "archived": False,
        }
        add_item(new_item)
        st.session_state["last_created_id"] = new_id
        st.session_state["new_form_nonce"] = nonce + 1
        st.rerun()
