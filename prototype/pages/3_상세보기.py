"""항목 상세 페이지 — 이미지 갤러리, 코멘트 타임라인, 상태 변경."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from _data import add_comment, get_comments, get_item, update_item
from _ui import (
    CSS,
    ROLE_LABELS,
    STATUS_LABELS,
    URGENCY_LABELS,
    absolute_time,
    banner,
    now,
    relative_time,
    render_sidebar_user,
    status_badge_html,
    urgency_badge_html,
)


# Allowed transitions (matches docs/04_workflow.md 4.3)
TRANSITIONS = {
    ("requested",   "developer"): ["in_progress"],
    ("requested",   "reviewer"):  ["closed"],
    ("in_progress", "developer"): ["api_check", "done"],
    ("api_check",   "developer"): ["in_progress", "done"],
    ("done",        "reviewer"):  ["reviewing", "closed"],
    ("reviewing",   "reviewer"):  ["closed", "reopened"],
    ("reopened",    "developer"): ["in_progress"],
}


st.set_page_config(page_title="상세보기 (프로토타입)", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

user = render_sidebar_user()
if not user:
    st.warning("좌측 사이드바에서 사용자 정보를 입력해주세요.")
    st.stop()

banner()

item_id = st.query_params.get("id")
if not item_id:
    st.error("항목 ID가 지정되지 않았습니다. 목록에서 카드를 클릭해 진입해 주세요.")
    if st.button("← 목록으로"):
        st.switch_page("pages/1_요청목록.py")
    st.stop()

item = get_item(item_id)
if not item:
    st.error(f"항목을 찾을 수 없습니다: {item_id}")
    if st.button("← 목록으로"):
        st.switch_page("pages/1_요청목록.py")
    st.stop()

# Back button
if st.button("← 목록으로"):
    st.switch_page("pages/1_요청목록.py")

# Title + badges
st.markdown(
    f"""
    <h2 style="margin-bottom:4px;">{item['title']}</h2>
    <div style="margin-bottom:8px;">
        {urgency_badge_html(item['urgency'])} {status_badge_html(item['status'])}
        <span style="color:#888;font-size:12px;font-family:monospace;margin-left:8px;">#{item['id']}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# Meta row
mc1, mc2, mc3, mc4 = st.columns(4)
mc1.markdown(f"**등록자**  \n{item['author']} ({ROLE_LABELS[item['author_role']]})")
mc2.markdown(f"**담당자**  \n{item.get('assignee') or '-'}")
mc3.markdown(f"**등록**  \n{absolute_time(item['created_at'])}")
mc4.markdown(f"**최근 갱신**  \n{absolute_time(item['updated_at'])}")

st.divider()

# Status change buttons
allowed = TRANSITIONS.get((item["status"], user["role"]), [])
st.markdown("##### 상태 변경")
if allowed:
    cols = st.columns(len(allowed) + 2)
    for i, next_status in enumerate(allowed):
        with cols[i]:
            label = STATUS_LABELS[next_status]
            btn_type = "primary" if next_status in ("done", "closed") else "secondary"
            if st.button(f"→ {label}", key=f"status_{next_status}", use_container_width=True, type=btn_type):
                add_comment(
                    item_id,
                    f"상태 변경: {STATUS_LABELS[item['status']]} → {STATUS_LABELS[next_status]}",
                    "system",
                    "system",
                    kind="system",
                )
                update_payload = {"status": next_status}
                if next_status == "closed":
                    update_payload["reviewer_confirmed"] = True
                    update_payload["reviewer_confirmed_at"] = now()
                update_item(item_id, **update_payload)
                st.rerun()
else:
    role_kr = ROLE_LABELS[user["role"]]
    st.caption(f"({role_kr} 역할로는 현재 상태에서 변경할 수 있는 옵션이 없습니다.)")

st.divider()

# Description
st.markdown("##### 설명")
st.markdown(item["description"])

st.divider()

# Image gallery (placeholders)
img_count = item.get("images_count", 0)
if img_count > 0:
    st.markdown(f"##### 스크린샷 ({img_count}장)")
    img_cols = st.columns(min(img_count, 3))
    for i in range(img_count):
        with img_cols[i % len(img_cols)]:
            st.markdown(
                f'<div class="thumb-placeholder detail">스크린샷 {i+1}</div>',
                unsafe_allow_html=True,
            )
    st.divider()

# Comments timeline
st.markdown("##### 코멘트 타임라인")
comments = get_comments(item_id)
if not comments:
    st.caption("코멘트가 없습니다.")
else:
    for c in comments:
        if c["kind"] == "system":
            st.markdown(
                f'<div class="timeline-item system">'
                f'─ {relative_time(c["at"])} · {c["body"]}'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            role_kr = ROLE_LABELS.get(c["role"], c["role"])
            # Escape body for safety in this prototype (basic)
            body_html = (
                c["body"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            st.markdown(
                f'<div class="timeline-item">'
                f'<span class="timeline-author">{c["author"]}</span>'
                f'<span class="timeline-meta">({role_kr}) · {absolute_time(c["at"])} · {relative_time(c["at"])}</span>'
                f'<div class="timeline-body">{body_html}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

# Comment input
st.markdown("##### 코멘트 작성")
nonce_key = f"comment_nonce_{item_id}"
nonce = st.session_state.get(nonce_key, 0)

with st.form(key=f"comment_form_{item_id}_{nonce}", clear_on_submit=False):
    body = st.text_area("내용", key=f"comment_body_{item_id}_{nonce}", height=80, label_visibility="collapsed", placeholder="코멘트를 입력하세요…")
    submit = st.form_submit_button("등록", type="primary")

if submit:
    if body.strip():
        add_comment(item_id, body.strip(), user["name"], user["role"])
        st.session_state[nonce_key] = nonce + 1
        st.rerun()
    else:
        st.error("내용을 입력해주세요.")
