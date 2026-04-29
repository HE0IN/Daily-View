"""요청 목록 — 필터 + 카드 그리드."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from _data import get_items
from _ui import (
    CSS,
    STATUS_LABELS,
    URGENCY_LABELS,
    banner,
    render_card_grid,
    render_sidebar_user,
)


st.set_page_config(page_title="요청 목록 (프로토타입)", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

user = render_sidebar_user()
if not user:
    st.warning("좌측 사이드바에서 사용자 정보를 입력해주세요.")
    st.stop()

banner()

st.title("요청 목록")

items = get_items()
all_assignees = sorted({i.get("assignee") for i in items if i.get("assignee")})

# Default filter values differ by role
default_assignee_options = ["전체", "(미할당)"] + list(all_assignees)
default_assignee = "전체"
if user["role"] == "developer" and user["name"] in all_assignees:
    default_assignee = user["name"]

# Filter row
fc1, fc2, fc3, fc4, fc5 = st.columns([1, 1.2, 1.2, 1, 2])

with fc1:
    urgency_filter = st.selectbox(
        "긴급도",
        options=["전체", "high", "normal", "low"],
        format_func=lambda v: "전체" if v == "전체" else URGENCY_LABELS[v],
    )

with fc2:
    status_options = ["전체"] + list(STATUS_LABELS.keys())
    status_filter = st.selectbox(
        "상태",
        options=status_options,
        format_func=lambda v: "전체" if v == "전체" else STATUS_LABELS[v],
    )

with fc3:
    assignee_filter = st.selectbox(
        "담당자",
        options=default_assignee_options,
        index=default_assignee_options.index(default_assignee),
    )

with fc4:
    show_closed = st.checkbox("검토완료 포함", value=False)

with fc5:
    search_query = st.text_input("검색", placeholder="제목/태그에서 검색")

# Apply filters
filtered = list(items)
if not show_closed:
    filtered = [i for i in filtered if i["status"] != "closed"]
if urgency_filter != "전체":
    filtered = [i for i in filtered if i["urgency"] == urgency_filter]
if status_filter != "전체":
    filtered = [i for i in filtered if i["status"] == status_filter]
if assignee_filter == "(미할당)":
    filtered = [i for i in filtered if not i.get("assignee")]
elif assignee_filter != "전체":
    filtered = [i for i in filtered if i.get("assignee") == assignee_filter]
if search_query:
    q = search_query.lower()
    filtered = [
        i for i in filtered
        if q in i["title"].lower() or any(q in t.lower() for t in i.get("tags", []))
    ]

filtered.sort(key=lambda i: i["updated_at"], reverse=True)

st.caption(f"총 {len(filtered)}건")

if not filtered:
    st.info("조건에 맞는 항목이 없습니다.")
else:
    cols_per_row = 3
    for row_start in range(0, len(filtered), cols_per_row):
        row = filtered[row_start:row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, item in zip(cols, row):
            with col:
                render_card_grid(item)
        # pad the last row if needed
        for c in cols[len(row):]:
            with c:
                st.empty()
