"""Shared UI components, theme constants, time helpers for the prototype."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st

KST = ZoneInfo("Asia/Seoul")

def now():
    return datetime.now(KST)

URGENCY_COLORS = {
    "high": "#E53935",
    "normal": "#FB8C00",
    "low": "#43A047",
}
URGENCY_LABELS = {
    "high": "긴급",
    "normal": "보통",
    "low": "낮음",
}
STATUS_COLORS = {
    "requested": "#3B82F6",
    "in_progress": "#8B5CF6",
    "api_check": "#06B6D4",
    "done": "#10B981",
    "reviewing": "#F59E0B",
    "reopened": "#EF4444",
    "closed": "#6B7280",
}
STATUS_LABELS = {
    "requested": "요청됨",
    "in_progress": "확인중",
    "api_check": "API대기",
    "done": "완료",
    "reviewing": "검토중",
    "reopened": "재요청",
    "closed": "검토완료",
}
ROLE_LABELS = {"reviewer": "검토자", "developer": "개발자"}

CSS = """
<style>
.proto-banner {
    background: #FFF3CD;
    border: 1px solid #FFE69C;
    color: #664D03;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 13px;
    margin-bottom: 12px;
}
.urgency-badge, .status-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    color: white;
    font-size: 11px;
    font-weight: 600;
    margin-right: 4px;
}
.card-row {
    border-left: 4px solid #ccc;
    padding: 8px 12px;
    margin-bottom: 4px;
    background: #fafafa;
    border-radius: 4px;
}
.card-row.sla-warn {
    border-left-color: #E53935;
    background: #FFEBEE;
}
.card-id { color: #888; font-size: 11px; font-family: monospace; }
.card-title { font-weight: 600; font-size: 14px; margin: 2px 0; }
.card-meta { color: #666; font-size: 12px; }
.thumb-placeholder {
    width: 100%;
    aspect-ratio: 4/3;
    background: repeating-linear-gradient(
        45deg, #e8e8e8, #e8e8e8 10px, #f0f0f0 10px, #f0f0f0 20px
    );
    border: 1px solid #ccc;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #888;
    font-size: 12px;
    margin-bottom: 8px;
}
.thumb-placeholder.detail {
    aspect-ratio: 16/9;
    height: 180px;
}
.timeline-item {
    border-left: 2px solid #cbd5e1;
    padding: 8px 0 8px 14px;
    margin: 0 0 6px 8px;
}
.timeline-item.system {
    border-left-style: dashed;
    border-left-color: #94a3b8;
    color: #64748b;
    font-style: italic;
    font-size: 12px;
    padding: 4px 0 4px 14px;
}
.timeline-author { font-weight: 600; color: #0f172a; }
.timeline-meta { color: #94a3b8; font-size: 11px; margin-left: 4px; }
.timeline-body { margin-top: 4px; white-space: pre-wrap; line-height: 1.5; }
.urgency-stripe {
    height: 6px;
    border-radius: 3px;
    margin-bottom: 6px;
}
.queue-section-header {
    font-weight: 700;
    font-size: 16px;
    margin: 12px 0 6px 0;
    padding-bottom: 4px;
    border-bottom: 2px solid #e2e8f0;
}
</style>
"""

def relative_time(dt):
    diff = (now() - dt).total_seconds()
    if diff < 60:
        return "방금"
    if diff < 3600:
        return f"{int(diff/60)}분 전"
    if diff < 86400:
        return f"{int(diff/3600)}시간 전"
    if diff < 86400 * 7:
        return f"{int(diff/86400)}일 전"
    return dt.strftime("%Y-%m-%d")

def absolute_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

def urgency_badge_html(urgency):
    return f'<span class="urgency-badge" style="background:{URGENCY_COLORS[urgency]}">{URGENCY_LABELS[urgency]}</span>'

def status_badge_html(status):
    return f'<span class="status-badge" style="background:{STATUS_COLORS[status]}">{STATUS_LABELS[status]}</span>'

def render_sidebar_user():
    """Sidebar widget for user identification. Returns the user dict or None."""
    with st.sidebar:
        st.markdown("### Daily View (프로토타입)")
        user = st.session_state.get("user")
        if user:
            role_kr = ROLE_LABELS[user["role"]]
            st.markdown(f"**현재**: {user['name']}  \n({role_kr})")
            if st.button("변경", key="user_change"):
                st.session_state["user"] = None
                st.rerun()
        else:
            with st.form("user_form"):
                name = st.text_input("이름", key="user_name_input")
                role = st.radio(
                    "역할",
                    options=["reviewer", "developer"],
                    format_func=lambda r: ROLE_LABELS[r],
                    key="user_role_input",
                )
                submitted = st.form_submit_button("저장", type="primary")
                if submitted and name.strip():
                    st.session_state["user"] = {"name": name.strip(), "role": role}
                    st.rerun()
        return st.session_state.get("user")

def render_card_compact(item, *, sla_warn=False):
    """Compact list-item card used in dashboard summaries."""
    sla_class = " sla-warn" if sla_warn else ""
    warn_icon = "[SLA임박] " if sla_warn else ""
    cols = st.columns([7, 1])
    with cols[0]:
        st.markdown(
            f"""<div class="card-row{sla_class}">
                <div class="card-id">{warn_icon}#{item["id"]}</div>
                <div class="card-title">{item["title"]}</div>
                <div class="card-meta">
                    {urgency_badge_html(item["urgency"])} {status_badge_html(item["status"])}
                    · 등록 {item["author"]}
                    · 담당 {item.get("assignee") or "-"}
                    · {relative_time(item["created_at"])}
                    · 코멘트 {item.get("comments_count", 0)} · 이미지 {item.get("images_count", 0)}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    with cols[1]:
        if st.button("열기", key=f"open_{item['id']}", use_container_width=True):
            st.query_params["id"] = item["id"]
            st.switch_page("pages/3_상세보기.py")

def render_card_grid(item):
    """Larger grid card used in the request list page."""
    with st.container(border=True):
        st.markdown(
            f'<div class="urgency-stripe" style="background:{URGENCY_COLORS[item["urgency"]]}"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'{urgency_badge_html(item["urgency"])} {status_badge_html(item["status"])}',
            unsafe_allow_html=True,
        )
        st.caption(f"#{item['id']}")
        st.markdown(
            f'<div class="thumb-placeholder">스크린샷 {item.get("images_count", 0)}장</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"**{item['title']}**")
        st.caption(
            f"등록 {item['author']} · 담당 {item.get('assignee') or '-'}  \n"
            f"{relative_time(item['created_at'])} · 코멘트 {item.get('comments_count', 0)} · 이미지 {item.get('images_count', 0)}"
        )
        if st.button("상세보기", key=f"detail_{item['id']}", use_container_width=True):
            st.query_params["id"] = item["id"]
            st.switch_page("pages/3_상세보기.py")

def banner():
    st.markdown(
        """<div class="proto-banner">
        <strong>프로토타입</strong> — 실제 데이터는 저장되지 않으며 새로고침 시 초기화됩니다.
        </div>""",
        unsafe_allow_html=True,
    )
