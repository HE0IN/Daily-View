"""Daily View prototype — entry point (dashboard)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from _data import get_items
from _ui import (
    CSS,
    URGENCY_LABELS,
    STATUS_LABELS,
    banner,
    now,
    render_card_compact,
    render_sidebar_user,
)


st.set_page_config(
    page_title="Daily View (프로토타입)",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

user = render_sidebar_user()

if not user:
    st.title("Daily View — 프로토타입")
    banner()
    st.info("좌측 사이드바에서 이름과 역할을 입력하면 시작됩니다.")
    st.stop()

banner()

st.title("대시보드")
role_label = "검토자" if user["role"] == "reviewer" else "개발자"
st.markdown(f"안녕하세요, **{user['name']}**님 ({role_label})")

items = get_items()
my_items = [i for i in items if i["author"] == user["name"]]

# Counts (active only)
active = [i for i in items if not i.get("archived") and i["status"] != "closed"]
counts_status = {}
counts_urgency = {}
for it in active:
    counts_status[it["status"]] = counts_status.get(it["status"], 0) + 1
    counts_urgency[it["urgency"]] = counts_urgency.get(it["urgency"], 0) + 1

st.divider()

if user["role"] == "reviewer":
    # === REVIEWER VIEW ===
    cta1, cta2, _ = st.columns([1, 1, 4])
    with cta1:
        if st.button("+ 새 요청 등록", type="primary", use_container_width=True):
            st.switch_page("pages/2_새요청등록.py")
    with cta2:
        if st.button("전체 목록 보기", use_container_width=True):
            st.switch_page("pages/1_요청목록.py")

    st.markdown('<div class="queue-section-header">검토 대기</div>', unsafe_allow_html=True)
    review_queue = [i for i in items if i["status"] == "done" and i["author"] == user["name"]]
    st.caption(f"{len(review_queue)}건 — 개발자가 완료 처리한 내 등록 항목")
    if review_queue:
        for item in review_queue:
            render_card_compact(item)
    else:
        st.caption("검토할 항목이 없습니다.")

    st.markdown('<div class="queue-section-header">내가 등록한 미해결</div>', unsafe_allow_html=True)
    my_open = [i for i in my_items if i["status"] != "closed"]
    st.caption(f"{len(my_open)}건")
    if my_open:
        for item in my_open[:5]:
            render_card_compact(item)
        if len(my_open) > 5:
            st.caption(f"… 외 {len(my_open) - 5}건은 [요청목록]에서 확인")
    else:
        st.caption("미해결 항목이 없습니다.")

else:
    # === DEVELOPER VIEW ===
    cta1, cta2, _ = st.columns([1, 1, 4])
    with cta1:
        if st.button("내 큐 전체 보기", type="primary", use_container_width=True):
            st.switch_page("pages/1_요청목록.py")
    with cta2:
        if st.button("새 요청 등록", use_container_width=True):
            st.switch_page("pages/2_새요청등록.py")

    st.markdown('<div class="queue-section-header">처리 큐</div>', unsafe_allow_html=True)
    queue = [
        i for i in items
        if i["status"] in ("requested", "reopened")
        and (i.get("assignee") == user["name"] or i.get("assignee") is None)
    ]
    st.caption(f"{len(queue)}건 — 내게 할당되거나 미할당된 활성 항목")
    if queue:
        for item in queue:
            sla_warn = (
                item["urgency"] == "high"
                and (now() - item["created_at"]).total_seconds() > 7200
            )
            render_card_compact(item, sla_warn=sla_warn)
    else:
        st.caption("처리할 항목이 없습니다.")

    st.markdown('<div class="queue-section-header">외부 대기 중</div>', unsafe_allow_html=True)
    api_check_items = [i for i in items if i["status"] == "api_check"]
    st.caption(f"{len(api_check_items)}건 — 외부 팀 답변 대기")
    if api_check_items:
        for item in api_check_items:
            render_card_compact(item)
    else:
        st.caption("외부 대기 중인 항목이 없습니다.")

st.divider()

st.subheader("전체 현황 (활성 항목)")
mc = st.columns(7)
order_status = ["requested", "in_progress", "api_check", "done", "reviewing", "reopened"]
mc[0].metric("긴급", counts_urgency.get("high", 0))
mc[1].metric("보통", counts_urgency.get("normal", 0))
mc[2].metric("낮음", counts_urgency.get("low", 0))
mc[3].metric(STATUS_LABELS["requested"], counts_status.get("requested", 0))
mc[4].metric(STATUS_LABELS["in_progress"], counts_status.get("in_progress", 0))
mc[5].metric(STATUS_LABELS["api_check"], counts_status.get("api_check", 0))
mc[6].metric(STATUS_LABELS["done"], counts_status.get("done", 0))
