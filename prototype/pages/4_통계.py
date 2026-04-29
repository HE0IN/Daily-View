"""통계 — 더미 카운트 차트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from _data import get_items
from _ui import CSS, STATUS_LABELS, URGENCY_LABELS, banner, render_sidebar_user


st.set_page_config(page_title="통계 (프로토타입)", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

user = render_sidebar_user()
if not user:
    st.warning("좌측 사이드바에서 사용자 정보를 입력해주세요.")
    st.stop()

banner()

st.title("통계")

items = get_items()
active = [i for i in items if not i.get("archived")]

# Top-level metrics
total_active = sum(1 for i in active if i["status"] != "closed")
total_closed = sum(1 for i in active if i["status"] == "closed")
total_high = sum(1 for i in active if i["status"] != "closed" and i["urgency"] == "high")

c1, c2, c3, c4 = st.columns(4)
c1.metric("전체", len(active))
c2.metric("활성", total_active)
c3.metric("검토완료", total_closed)
c4.metric("긴급(활성)", total_high)

st.divider()

# Status distribution
status_order = ["requested", "in_progress", "api_check", "done", "reviewing", "reopened", "closed"]
df_status = pd.DataFrame({
    "상태": [STATUS_LABELS[s] for s in status_order],
    "건수": [sum(1 for i in active if i["status"] == s) for s in status_order],
})

# Urgency distribution
urgency_order = ["high", "normal", "low"]
df_urgency = pd.DataFrame({
    "긴급도": [URGENCY_LABELS[u] for u in urgency_order],
    "건수": [sum(1 for i in active if i["urgency"] == u) for u in urgency_order],
})

cc1, cc2 = st.columns(2)
with cc1:
    st.subheader("상태별")
    st.bar_chart(df_status, x="상태", y="건수")
with cc2:
    st.subheader("긴급도별")
    st.bar_chart(df_urgency, x="긴급도", y="건수")

# Author / assignee
authors = {}
assignees = {}
for it in active:
    authors[it["author"]] = authors.get(it["author"], 0) + 1
    a = it.get("assignee") or "(미할당)"
    assignees[a] = assignees.get(a, 0) + 1

ac1, ac2 = st.columns(2)
with ac1:
    st.subheader("등록자별")
    df_author = pd.DataFrame({"등록자": list(authors.keys()), "건수": list(authors.values())})
    st.bar_chart(df_author, x="등록자", y="건수")
with ac2:
    st.subheader("담당자별")
    df_assignee = pd.DataFrame({"담당자": list(assignees.keys()), "건수": list(assignees.values())})
    st.bar_chart(df_assignee, x="담당자", y="건수")

st.caption("※ 프로토타입의 더미 데이터 기반입니다. 본 구현 시 실제 데이터로 자동 대체됩니다.")
