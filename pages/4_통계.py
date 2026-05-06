"""통계 페이지.

docs/03_ui_design.md 3.7 절을 따른다.
``list_issues`` 로 모든 항목(아카이브/클로즈 포함)을 끌어와 카운트와 트렌드 차트를 그린다.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from core import paths, repository
from core.clock import KST, from_iso, now
from core.logger import tail_audit
from core.models import Status, Urgency
from ui.auth import get_or_init_user, require_user
from ui.components import render_count_metric
from ui.theme import (
    STATUS_LABELS,
    URGENCY_COLORS,
    URGENCY_LABELS,
    is_sla_violated,
)


# ---------------------------------------------------------------------------
# 페이지 셋업
# ---------------------------------------------------------------------------

st.set_page_config(page_title="통계 — Daily View", layout="wide")
paths.ensure_data_dirs()
get_or_init_user()
require_user()  # 사용자 식별 보장만 (값 사용 X)

st.title("통계")
st.caption("등록된 모든 항목 (아카이브 포함) 기준의 통계입니다.")


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

all_entries = repository.list_issues(include_archived=True, include_closed=True)

if not all_entries:
    st.info("아직 데이터가 없습니다. [새 요청 등록]에서 첫 항목을 만들어보세요.")
    st.stop()

# DataFrame 변환 — IndexEntry.model_dump 는 Enum 객체를 그대로 둘 수 있어 mode='json' 사용
records = [e.model_dump(mode="json") for e in all_entries]
df = pd.DataFrame(records)

# 날짜 컬럼 변환 (timezone-aware)
df["created_at_dt"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
df["updated_at_dt"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")
# 한국 표기를 위해 KST 로 변환
df["created_at_kst"] = df["created_at_dt"].dt.tz_convert(KST)
df["updated_at_kst"] = df["updated_at_dt"].dt.tz_convert(KST)


# ---------------------------------------------------------------------------
# 상단 카드 행
# ---------------------------------------------------------------------------

active_mask = (~df["status"].isin([Status.closed.value])) & (~df["archived"])
closed_mask = df["status"] == Status.closed.value
high_unresolved_mask = (df["urgency"] == Urgency.high.value) & active_mask

c1, c2, c3, c4 = st.columns(4)
with c1:
    render_count_metric("전체", len(df))
with c2:
    render_count_metric("활성", int(active_mask.sum()), color="#3B82F6")
with c3:
    render_count_metric("완료(검토완료)", int(closed_mask.sum()), color="#6B7280")
with c4:
    render_count_metric(
        "긴급(미해결)",
        int(high_unresolved_mask.sum()),
        color=URGENCY_COLORS["high"],
    )

st.markdown("---")


# ---------------------------------------------------------------------------
# 섹션 1: 긴급도별 분포
# ---------------------------------------------------------------------------

st.subheader("긴급도별 분포")
urgency_counts = (
    df["urgency"]
    .value_counts()
    .reindex(["high", "normal", "low"])
    .fillna(0)
    .astype(int)
)
urg_chart_df = pd.DataFrame(
    {
        "긴급도": [URGENCY_LABELS.get(k, k) for k in urgency_counts.index],
        "건수": urgency_counts.values,
    }
).set_index("긴급도")
st.bar_chart(urg_chart_df)


# ---------------------------------------------------------------------------
# 섹션 2: 상태별 분포
# ---------------------------------------------------------------------------

st.subheader("상태별 분포")
# 모든 상태 키 순서를 고정
status_keys = [s.value for s in Status]
status_counts = (
    df["status"].value_counts().reindex(status_keys).fillna(0).astype(int)
)
st_chart_df = pd.DataFrame(
    {
        "상태": [STATUS_LABELS.get(k, k) for k in status_counts.index],
        "건수": status_counts.values,
    }
).set_index("상태")
st.bar_chart(st_chart_df)


# ---------------------------------------------------------------------------
# 섹션 3: 일자별 등록 트렌드 (지난 30일)
# ---------------------------------------------------------------------------

st.subheader("일자별 등록 트렌드 (최근 30일)")
today_kst = now().date()
start_date = today_kst - timedelta(days=29)

# 지난 30일에 등록된 항목들
recent_mask = df["created_at_kst"].dt.date >= start_date
recent = df[recent_mask].copy()
if recent.empty:
    st.caption("최근 30일 내 등록된 항목이 없습니다.")
else:
    recent["날짜"] = recent["created_at_kst"].dt.date
    daily_counts = recent.groupby("날짜").size()
    # 빈 날짜를 0으로 채우기 위한 전체 인덱스
    full_idx = pd.date_range(start=start_date, end=today_kst, freq="D").date
    trend_df = pd.DataFrame(
        {"등록 건수": [int(daily_counts.get(d, 0)) for d in full_idx]},
        index=pd.Index(full_idx, name="날짜"),
    )
    st.line_chart(trend_df)


# ---------------------------------------------------------------------------
# 섹션 4: 등록자/담당자별 건수
# ---------------------------------------------------------------------------

st.subheader("등록자 / 담당자별 건수")
left_col, right_col = st.columns(2)

with left_col:
    st.markdown("**등록자별**")
    author_counts = df["author"].fillna("(미상)").value_counts().reset_index()
    author_counts.columns = ["등록자", "건수"]
    st.dataframe(author_counts, use_container_width=True, hide_index=True)

with right_col:
    st.markdown("**담당자별**")
    df_assignee = df.copy()
    df_assignee["assignee"] = df_assignee["assignee"].fillna("(미배정)")
    assignee_counts = df_assignee["assignee"].value_counts().reset_index()
    assignee_counts.columns = ["담당자", "건수"]
    st.dataframe(assignee_counts, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 섹션 5: SLA 위반
# ---------------------------------------------------------------------------

st.subheader("SLA 위반 (활성 항목 대상)")
violated_rows = []
for _, row in df[active_mask].iterrows():
    if is_sla_violated(row["urgency"], row["created_at"], row["status"]):
        violated_rows.append(
            {
                "ID": row["id"],
                "제목": row["title"],
                "긴급도": URGENCY_LABELS.get(row["urgency"], row["urgency"]),
                "상태": STATUS_LABELS.get(row["status"], row["status"]),
                "등록자": row["author"],
                "담당자": row["assignee"] or "(미배정)",
                "등록 시각": (
                    row["created_at_kst"].strftime("%Y-%m-%d %H:%M")
                    if pd.notna(row["created_at_kst"])
                    else "-"
                ),
            }
        )

if not violated_rows:
    st.success("현재 SLA 위반 활성 항목이 없습니다.")
else:
    st.error(f"SLA 위반: {len(violated_rows)}건")
    sla_df = pd.DataFrame(violated_rows)
    st.dataframe(sla_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 섹션 6: 평균 처리 시간 (closed 항목 대상)
# ---------------------------------------------------------------------------

st.subheader("평균 처리 시간")


def _load_resolution_hours() -> tuple[list[float], int]:
    """closed 항목들의 created_at → reviewer_confirmed_at 시간(시간 단위)."""
    hours: list[float] = []
    skipped = 0
    closed_entries = df[df["status"] == Status.closed.value]
    for _, row in closed_entries.iterrows():
        try:
            issue = repository.get_issue(row["id"])
        except FileNotFoundError:
            skipped += 1
            continue
        if issue.reviewer_confirmed_at is None:
            skipped += 1
            continue
        delta: timedelta = issue.reviewer_confirmed_at - issue.created_at
        hours.append(delta.total_seconds() / 3600.0)
    return hours, skipped


resolution_hours, skipped = _load_resolution_hours()
if not resolution_hours:
    st.caption("아직 처리 완료된 항목이 없거나 데이터가 부족합니다.")
else:
    avg_hours = sum(resolution_hours) / len(resolution_hours)
    median_hours = sorted(resolution_hours)[len(resolution_hours) // 2]
    min_hours = min(resolution_hours)
    max_hours = max(resolution_hours)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("표본 수", len(resolution_hours))
    with m2:
        st.metric("평균", f"{avg_hours:.1f}h")
    with m3:
        st.metric("중앙값", f"{median_hours:.1f}h")
    with m4:
        st.metric("최대", f"{max_hours:.1f}h")
    st.caption(
        f"등록 → 검토완료 시각 차이의 시간 단위 통계. "
        f"(최소 {min_hours:.1f}h{', 누락 ' + str(skipped) + '건' if skipped else ''})"
    )


# ---------------------------------------------------------------------------
# 섹션 7: 최근 활동 (audit log tail)
# ---------------------------------------------------------------------------

st.subheader("최근 활동")
audit_lines = tail_audit(20)
if not audit_lines:
    st.caption("기록된 활동이 없습니다.")
else:
    activity_rows = []
    for line in reversed(audit_lines):  # 최신부터
        ts = line.get("ts", "")
        try:
            ts_str = from_iso(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
        except Exception:
            ts_str = ts or "-"
        activity_rows.append(
            {
                "시각": ts_str,
                "작업자": line.get("actor", "-"),
                "동작": line.get("action", "-"),
                "항목": line.get("item_id") or "-",
            }
        )
    st.dataframe(
        pd.DataFrame(activity_rows),
        use_container_width=True,
        hide_index=True,
    )
