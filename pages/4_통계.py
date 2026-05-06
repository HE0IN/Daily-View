"""진척도 대시보드 페이지 (단순화 버전).

사용자 요구에 맞춰 "지금 뭐하고 있는지" 만 빠르게 파악할 수 있도록 재구성.
담당자별 표 / 최근 활동 섹션은 제거하고, 카테고리별 정체 카운트를 중심으로
배치한다.

섹션:
    1) 핵심 KPI 4 개 (이번 주 완료 / 진행 중 / 대기 중 / SLA 위반)
    2) 카테고리(L1)별 진행 상황 — 정체 카운트 강조 + 누적 막대 차트
    3) 30 일 등록/완료 트렌드 — 라인 차트 + 지난 7 일 합계 캡션
    4) 정체된 항목 Top 5 — updated_at 오름차순

자동 새로고침은 ``streamlit-autorefresh`` 가 설치돼 있고 ``AUTO_REFRESH_SEC``
환경변수가 양수일 때만 활성화 (기본 60 초).
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import streamlit as st

from core import paths, repository
from core.clock import KST, now
from core.models import IndexEntry, Issue, Status
from ui.auth import get_or_init_user, require_user
from ui.components import humanize_dt, render_count_metric
from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_COLORS,
    URGENCY_LABELS,
    is_sla_violated,
)


# ---------------------------------------------------------------------------
# 페이지 셋업
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="진척도 — Daily View",
    layout="wide",
    initial_sidebar_state="expanded",
)
paths.ensure_data_dirs()

# 자동 새로고침 — 미설치/오류 시 조용히 패스
try:  # pragma: no cover - 환경 의존
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
except Exception:  # noqa: BLE001
    _st_autorefresh = None  # type: ignore[assignment]

if _st_autorefresh is not None:
    try:
        _refresh_sec = int(os.environ.get("AUTO_REFRESH_SEC", "60"))
    except ValueError:
        _refresh_sec = 60
    if _refresh_sec > 0:
        _st_autorefresh(interval=_refresh_sec * 1000, key="dashboard_autorefresh")

get_or_init_user()
require_user()  # 사용자 식별 보장만 (값 사용 X)

st.title("진척도 대시보드")
st.caption(
    "지금 무엇을 하고 있는지, 카테고리별로 정체된 게 얼마나 있는지 한 눈에 봅니다."
)


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

# 아카이브/완료 포함한 전체 항목 (카운트 정확성을 위해)
all_entries: list[IndexEntry] = repository.list_issues(
    include_archived=True, include_closed=True
)

if not all_entries:
    st.info("아직 데이터가 없습니다. [새 요청 등록] 페이지에서 첫 항목을 만들어보세요.")
    st.stop()

NOW: datetime = now()
TODAY: date = NOW.date()
WEEK_START: date = TODAY - timedelta(days=6)  # 최근 7일 (오늘 포함)
TREND_DAYS = 30
TREND_START: date = TODAY - timedelta(days=TREND_DAYS - 1)
STALE_DAYS = 3  # "정체" 기준 — 마지막 갱신이 3 일 이상 경과


# Issue (meta.json) 캐시 — 카테고리 / closed_at 계산에 필요.
# IndexEntry 에는 closed_at 이 없어 항목별 meta 를 한 번씩 로드한다.

@st.cache_data(ttl=30)  # 30 초 캐시 — 자동 새로고침과 균형
def _load_issue_cached(item_id: str) -> dict | None:
    """meta.json 1 건을 dict 로 로드. 실패 시 None."""
    try:
        issue = repository.get_issue(item_id)
    except (FileNotFoundError, OSError, ValueError):
        return None
    return issue.model_dump(mode="json")


def _load_issues(entries: Iterable[IndexEntry]) -> list[Issue]:
    """IndexEntry 리스트에 대응하는 Issue 들을 로드. 누락은 건너뜀."""
    out: list[Issue] = []
    for e in entries:
        data = _load_issue_cached(e.id)
        if data is None:
            continue
        try:
            out.append(Issue.model_validate(data))
        except Exception:  # noqa: BLE001
            continue
    return out


issues: list[Issue] = _load_issues(all_entries)

# DataFrame — 빠른 집계용 (IndexEntry 기반).
records = [e.model_dump(mode="json") for e in all_entries]
df = pd.DataFrame(records)
df["created_at_dt"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
df["updated_at_dt"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")
df["created_at_kst"] = df["created_at_dt"].dt.tz_convert(KST)
df["updated_at_kst"] = df["updated_at_dt"].dt.tz_convert(KST)
df["created_date"] = df["created_at_kst"].dt.date


# ---------------------------------------------------------------------------
# 헬퍼 — closed_at
# ---------------------------------------------------------------------------


def _closed_at(issue: Issue) -> datetime | None:
    """이슈의 종료 시각. ``reviewer_confirmed_at`` 우선,
    없으면 status_history 의 마지막 ``closed`` 이벤트 사용."""
    if issue.reviewer_confirmed_at is not None:
        return issue.reviewer_confirmed_at
    for ev in reversed(issue.status_history):
        if ev.status == Status.closed:
            return ev.at
    return None


# ---------------------------------------------------------------------------
# 1) 핵심 KPI 4 개
# ---------------------------------------------------------------------------

ACTIVE_STATUSES = {
    Status.requested.value,
    Status.in_progress.value,
    Status.api_check.value,
    Status.reviewing.value,
    Status.reopened.value,
    Status.done.value,  # 레거시 호환
}
IN_PROGRESS_STATUSES = {
    Status.in_progress.value,
    Status.api_check.value,
    Status.reviewing.value,
}

# 활성 / closed 마스크 (IndexEntry 기반)
active_mask = df["status"].isin(ACTIVE_STATUSES) & (~df["archived"].fillna(False))

# 이번 주 완료 — closed_at 이 최근 7일 이내 (Issue 의 reviewer_confirmed_at 사용)
weekly_closed_count = 0
for issue in issues:
    if issue.status != Status.closed:
        continue
    closed_at = _closed_at(issue)
    if closed_at is None:
        continue
    if closed_at.astimezone(KST).date() >= WEEK_START:
        weekly_closed_count += 1

# 진행 중 / 대기 중
in_progress_count = int(df["status"].isin(IN_PROGRESS_STATUSES).sum())
requested_count = int((df["status"] == Status.requested.value).sum())

# SLA 위반 — 활성 항목만
sla_violations = 0
for _, row in df[active_mask].iterrows():
    created_at = row["created_at"]
    if not created_at:
        continue
    if is_sla_violated(row["urgency"], created_at, row["status"], now=NOW):
        sla_violations += 1

st.subheader("핵심 지표")
k1, k2, k3, k4 = st.columns(4)
with k1:
    render_count_metric("이번 주 완료", weekly_closed_count, color="#10B981")
with k2:
    render_count_metric(
        "진행 중", in_progress_count, color=STATUS_COLORS["in_progress"]
    )
with k3:
    render_count_metric(
        "대기 중", requested_count, color=STATUS_COLORS["requested"]
    )
with k4:
    render_count_metric(
        "SLA 위반", sla_violations, color=URGENCY_COLORS["high"]
    )

st.divider()


# ---------------------------------------------------------------------------
# 2) 카테고리(L1)별 진행 상황 — 정체 카운트 중심
# ---------------------------------------------------------------------------

st.subheader("카테고리별 진행 상황")
st.caption(
    f"'정체' = 활성 상태(완료/아카이브 제외)인데 마지막 갱신이 {STALE_DAYS}일 이상 지난 항목. "
    "SLA 위반과는 다른 개념입니다 (SLA = 첫 응답 기준, 정체 = 마지막 갱신 기준)."
)

STALE_CUTOFF: datetime = NOW - timedelta(days=STALE_DAYS)


@st.cache_data(ttl=30)
def _build_category_table(records_payload: list[dict]) -> pd.DataFrame:
    """L1 카테고리별로 진행 중 / 정체 / 완료 / 합계 집계.

    파라미터로 ``records_payload`` (Issue.model_dump 리스트) 를 받아 캐시 키로
    사용한다. 캐시 hit 시 Issue 재로드 비용을 절감.
    """
    rows: dict[str, dict[str, int]] = defaultdict(
        lambda: {"in_progress": 0, "stalled": 0, "closed": 0, "total": 0}
    )
    for data in records_payload:
        try:
            issue = Issue.model_validate(data)
        except Exception:  # noqa: BLE001
            continue
        l1 = (issue.category_l1 or "").strip() or "(미분류)"
        bucket = rows[l1]
        bucket["total"] += 1

        # 아카이브는 closed 와 같이 친다 (대부분 closed 가 archived 됨)
        if issue.archived:
            bucket["closed"] += 1
            continue

        status_value = issue.status.value
        if status_value == Status.closed.value:
            bucket["closed"] += 1
            continue

        # 활성 항목 중 진행 중 카운트
        if status_value in IN_PROGRESS_STATUSES:
            bucket["in_progress"] += 1

        # 활성 항목 중 정체 여부 (updated_at 기준)
        if status_value in ACTIVE_STATUSES:
            if issue.updated_at <= STALE_CUTOFF:
                bucket["stalled"] += 1

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(
        [
            {
                "카테고리": k,
                "전체": v["total"],
                "진행 중": v["in_progress"],
                "정체": v["stalled"],
                "완료": v["closed"],
            }
            for k, v in rows.items()
        ]
    ).sort_values(by=["정체", "전체"], ascending=[False, False]).reset_index(
        drop=True
    )
    return table


# 캐시 키 안정화를 위해 dict 리스트로 전달
_issue_payload = [iss.model_dump(mode="json") for iss in issues]
cat_table = _build_category_table(_issue_payload)

if cat_table.empty:
    st.caption("표시할 카테고리가 없습니다.")
else:
    # 표 — 정체 컬럼이 0 보다 크면 빨간색으로 강조
    def _highlight_stalled(val: object) -> str:
        try:
            n = int(val)
        except (TypeError, ValueError):
            return ""
        if n > 0:
            return "background-color: #FEE2E2; color: #B91C1C; font-weight: 600;"
        return ""

    styled = cat_table.style.applymap(_highlight_stalled, subset=["정체"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # 누적 막대 차트 — 진행 중 / 정체 / 완료
    chart_df = cat_table.set_index("카테고리")[["진행 중", "정체", "완료"]]
    st.bar_chart(chart_df)

st.divider()


# ---------------------------------------------------------------------------
# 3) 일자별 트렌드 (등록 vs 완료, 지난 30 일)
# ---------------------------------------------------------------------------

st.subheader(f"등록 / 완료 트렌드 (최근 {TREND_DAYS}일)")


def _build_trend_df(issues: list[Issue]) -> pd.DataFrame:
    """일자별 등록·완료 카운트. 빈 날짜는 0 으로 채움."""
    full_idx = pd.date_range(start=TREND_START, end=TODAY, freq="D").date

    created_by_date: dict[date, int] = defaultdict(int)
    closed_by_date: dict[date, int] = defaultdict(int)

    for issue in issues:
        created_d = issue.created_at.astimezone(KST).date()
        if created_d >= TREND_START:
            created_by_date[created_d] += 1
        if issue.status == Status.closed:
            closed_at = _closed_at(issue)
            if closed_at is not None:
                closed_d = closed_at.astimezone(KST).date()
                if closed_d >= TREND_START:
                    closed_by_date[closed_d] += 1

    return pd.DataFrame(
        {
            "등록": [created_by_date.get(d, 0) for d in full_idx],
            "완료": [closed_by_date.get(d, 0) for d in full_idx],
        },
        index=pd.Index(full_idx, name="날짜"),
    )


trend_df = _build_trend_df(issues)

# 지난 7 일 (오늘 포함) 합계 — 사용자가 궁금해하는 "이번주 개발량"
weekly_mask = [d >= WEEK_START for d in trend_df.index]
weekly_in = int(trend_df.loc[weekly_mask, "등록"].sum())
weekly_out = int(trend_df.loc[weekly_mask, "완료"].sum())
st.caption(f"지난 7일: 등록 {weekly_in}건 · 완료 {weekly_out}건")

if trend_df["등록"].sum() == 0 and trend_df["완료"].sum() == 0:
    st.caption(f"최근 {TREND_DAYS}일 내 등록·완료된 항목이 없습니다.")
else:
    st.line_chart(trend_df)

st.divider()


# ---------------------------------------------------------------------------
# 4) 정체된 항목 Top 5
# ---------------------------------------------------------------------------

st.subheader("정체된 항목 Top 5")
st.caption("활성 상태(완료/아카이브 제외) 중 마지막 갱신이 가장 오래된 항목들.")

stalled_df = df[active_mask].copy()
if stalled_df.empty:
    st.success("현재 정체된 활성 항목이 없습니다.")
else:
    stalled_df = stalled_df.sort_values(by="updated_at_dt", ascending=True).head(5)

    rows: list[dict[str, object]] = []
    for _, row in stalled_df.iterrows():
        updated_at = row["updated_at"]
        last_update = humanize_dt(updated_at) if updated_at else "-"
        rows.append(
            {
                "ID": row["id"],
                "제목": row["title"],
                "긴급도": URGENCY_LABELS.get(row["urgency"], row["urgency"]),
                "상태": STATUS_LABELS.get(row["status"], row["status"]),
                "담당자": row["assignee"] or "(미배정)",
                "마지막 갱신": last_update,
            }
        )
    st.dataframe(
        pd.DataFrame(rows), use_container_width=True, hide_index=True
    )
