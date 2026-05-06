"""진척도 대시보드 페이지.

기존 차트 위주 통계 페이지를 "관리자 시점의 진척도(progress) 대시보드" 로
재구성. 사이드바 라벨이 파일명 기반이라 파일명은 ``4_통계.py`` 그대로 두고
페이지 제목/내용만 진척도 중심으로 바꾼다.

섹션:
    1) 상단 KPI 카드 6 개 (이번 주 완료 / 진행 중 / 대기 중 / SLA 위반 /
       재요청 / 이번 달 등록)
    2) 담당자별 진행 상황 (진행 중 · 이번 달 완료 · 평균 처리 시간 · SLA 위반)
    3) 카테고리(L1)별 분포 (진행 중 vs 완료)
    4) 일자별 트렌드 (지난 30 일, 등록 vs 완료)
    5) 정체된 항목 Top 5
    6) 최근 활동 (audit log tail)

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
from core.clock import KST, from_iso, humanize, now
from core.logger import tail_audit
from core.models import IndexEntry, Issue, Status, Urgency
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
    "관리자 시점의 진척도 — 지금 무엇을 하고 있는지, 누가 정체되어 있는지, "
    "최근 어떤 일이 있었는지 한 눈에 봅니다."
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
MONTH_START: date = TODAY.replace(day=1)
TREND_DAYS = 30
TREND_START: date = TODAY - timedelta(days=TREND_DAYS - 1)

# Issue (meta.json) 캐시 — 평균 처리 시간 / 카테고리 / closed_at 계산에 필요.
# IndexEntry 에는 closed_at 이 없어 항목별 meta 를 한 번씩 로드한다.
# 항목이 수만 건 이상이면 별도 캐시가 필요하지만 이 워크로드에선 OK.

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
# 헬퍼 — closed_at / 처리 시간
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


def _resolution_hours(issue: Issue) -> float | None:
    """등록 → 종료 시간 (시간 단위). closed 가 아니면 None."""
    closed_at = _closed_at(issue)
    if closed_at is None:
        return None
    return (closed_at - issue.created_at).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# 1) 상단 KPI 카드 6 개
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

# 재요청
reopened_count = int((df["status"] == Status.reopened.value).sum())

# 이번 달 등록
this_month_count = int(
    (df["created_date"] >= MONTH_START).sum()
    if "created_date" in df.columns
    else 0
)

st.subheader("핵심 지표")
k1, k2, k3, k4, k5, k6 = st.columns(6)
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
with k5:
    render_count_metric(
        "재요청", reopened_count, color=STATUS_COLORS["reopened"]
    )
with k6:
    render_count_metric("이번 달 등록", this_month_count, color="#6366F1")

st.divider()


# ---------------------------------------------------------------------------
# 2) 담당자별 진행 상황
# ---------------------------------------------------------------------------

st.subheader("담당자별 진행 상황")


def _build_assignee_table(issues: list[Issue]) -> pd.DataFrame:
    """담당자별 집계 표 생성.

    컬럼: 담당자 / 진행 중 / 이번 달 완료 / 평균 처리 시간 / SLA 위반.
    평균 처리 시간 = 지금까지 closed 된 항목들의 (closed_at - created_at) 평균,
    시간 단위로 표시 (24h 이상이면 "1.2일" 처럼).
    """
    rows: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "in_progress": 0,
            "monthly_closed": 0,
            "resolution_total_h": 0.0,
            "resolution_n": 0,
            "sla_violations": 0,
        }
    )
    for issue in issues:
        key = issue.assignee or "(미배정)"
        bucket = rows[key]
        status_value = issue.status.value

        # 진행 중
        if status_value in IN_PROGRESS_STATUSES and not issue.archived:
            bucket["in_progress"] = int(bucket["in_progress"]) + 1

        # 이번 달 완료
        if issue.status == Status.closed:
            closed_at = _closed_at(issue)
            if closed_at and closed_at.astimezone(KST).date() >= MONTH_START:
                bucket["monthly_closed"] = int(bucket["monthly_closed"]) + 1
            # 평균 처리 시간 — closed 항목 전체 누적
            hrs = _resolution_hours(issue)
            if hrs is not None and hrs >= 0:
                bucket["resolution_total_h"] = (
                    float(bucket["resolution_total_h"]) + hrs
                )
                bucket["resolution_n"] = int(bucket["resolution_n"]) + 1

        # SLA 위반 (활성 항목만)
        if status_value in ACTIVE_STATUSES and not issue.archived:
            if is_sla_violated(
                issue.urgency.value,
                issue.created_at,
                status_value,
                now=NOW,
            ):
                bucket["sla_violations"] = int(bucket["sla_violations"]) + 1

    if not rows:
        return pd.DataFrame()

    out_rows: list[dict[str, object]] = []
    for assignee, data in rows.items():
        n = int(data["resolution_n"])
        if n > 0:
            avg_h = float(data["resolution_total_h"]) / n
            avg_label = (
                f"{avg_h / 24:.1f}일" if avg_h >= 24 else f"{avg_h:.1f}시간"
            )
        else:
            avg_label = "-"
        out_rows.append(
            {
                "담당자": assignee,
                "진행 중": int(data["in_progress"]),
                "이번 달 완료": int(data["monthly_closed"]),
                "평균 처리 시간": avg_label,
                "SLA 위반": int(data["sla_violations"]),
            }
        )

    table = pd.DataFrame(out_rows)
    # 진행 중 많은 순 → SLA 위반 많은 순 → 이번 달 완료 많은 순
    table = table.sort_values(
        by=["진행 중", "SLA 위반", "이번 달 완료"], ascending=[False, False, False]
    ).reset_index(drop=True)
    return table


assignee_table = _build_assignee_table(issues)
if assignee_table.empty:
    st.caption("담당자가 배정된 항목이 아직 없습니다.")
else:
    st.dataframe(assignee_table, use_container_width=True, hide_index=True)
    st.caption(
        "평균 처리 시간 = (검토완료 시각 − 등록 시각) 평균. "
        "검토완료 시각이 없으면 status_history 의 마지막 closed 이벤트를 사용합니다."
    )

st.divider()


# ---------------------------------------------------------------------------
# 3) 카테고리(L1)별 분포
# ---------------------------------------------------------------------------

st.subheader("카테고리별 분포 (대분류)")


def _build_category_table(issues: list[Issue]) -> pd.DataFrame:
    """L1 카테고리별로 진행 중 / 완료 / 합계 집계."""
    rows: dict[str, dict[str, int]] = defaultdict(
        lambda: {"in_progress": 0, "closed": 0, "other": 0, "total": 0}
    )
    for issue in issues:
        l1 = (issue.category_l1 or "").strip() or "(미분류)"
        bucket = rows[l1]
        bucket["total"] += 1
        if issue.archived:
            # 아카이브는 closed 와 같이 친다 (대부분 closed 가 archived 됨)
            bucket["closed"] += 1
            continue
        status_value = issue.status.value
        if status_value in IN_PROGRESS_STATUSES:
            bucket["in_progress"] += 1
        elif status_value == Status.closed.value:
            bucket["closed"] += 1
        else:
            bucket["other"] += 1
    return pd.DataFrame(
        [
            {
                "카테고리": k,
                "진행 중": v["in_progress"],
                "완료": v["closed"],
                "기타": v["other"],
                "합계": v["total"],
            }
            for k, v in rows.items()
        ]
    ).sort_values(by="합계", ascending=False).reset_index(drop=True)


cat_table = _build_category_table(issues)
if cat_table.empty:
    st.caption("표시할 카테고리가 없습니다.")
else:
    chart_left, table_right = st.columns([2, 1])
    with chart_left:
        # 진행 중 vs 완료 비교 막대
        chart_df = cat_table.set_index("카테고리")[["진행 중", "완료"]]
        st.bar_chart(chart_df)
    with table_right:
        st.dataframe(cat_table, use_container_width=True, hide_index=True)

st.divider()


# ---------------------------------------------------------------------------
# 4) 일자별 트렌드 (등록 vs 완료, 지난 30 일)
# ---------------------------------------------------------------------------

st.subheader(f"일자별 등록 / 완료 트렌드 (최근 {TREND_DAYS}일)")


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
if trend_df["등록"].sum() == 0 and trend_df["완료"].sum() == 0:
    st.caption(f"최근 {TREND_DAYS}일 내 등록·완료된 항목이 없습니다.")
else:
    st.line_chart(trend_df)
    total_in = int(trend_df["등록"].sum())
    total_out = int(trend_df["완료"].sum())
    net = total_in - total_out
    net_label = (
        f"순증 +{net}" if net > 0 else (f"순감 {net}" if net < 0 else "균형")
    )
    st.caption(
        f"기간 합계 — 등록 {total_in}건 · 완료 {total_out}건 · {net_label}"
    )

st.divider()


# ---------------------------------------------------------------------------
# 5) 정체된 항목 Top 5
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

st.divider()


# ---------------------------------------------------------------------------
# 6) 최근 활동 (audit log tail)
# ---------------------------------------------------------------------------

st.subheader("최근 활동")

# 액션 키 → 한국어 라벨
_ACTION_LABELS: dict[str, str] = {
    "create_issue": "등록",
    "update_status": "상태 변경",
    "update_assignee": "담당자 변경",
    "update_tags": "태그 변경",
    "update_categories": "카테고리 변경",
    "add_comment": "코멘트",
    "upload_image": "이미지 첨부",
    "confirm_review": "검토 완료",
    "archive": "아카이브",
    "auto_archive": "자동 아카이브",
}


def _format_audit_summary(line: dict) -> str:
    """audit 한 줄을 사람이 읽을 수 있는 요약으로."""
    actor = line.get("actor") or "-"
    action_raw = line.get("action") or "-"
    action_label = _ACTION_LABELS.get(action_raw, action_raw)
    item_id = line.get("item_id")
    detail = line.get("detail") or {}

    if action_raw == "update_status" and isinstance(detail, dict):
        from_v = detail.get("from")
        to_v = detail.get("to")
        from_label = STATUS_LABELS.get(from_v or "", from_v or "")
        to_label = STATUS_LABELS.get(to_v or "", to_v or "")
        return f"{actor}: {from_label} → {to_label}"
    if action_raw == "update_assignee" and isinstance(detail, dict):
        to_v = detail.get("to") or "(미배정)"
        return f"{actor}: 담당자 → {to_v}"
    if action_raw == "create_issue" and isinstance(detail, dict):
        title = detail.get("title") or item_id or "-"
        return f"{actor}: '{title}' 등록"
    return f"{actor}: {action_label}"


audit_lines = tail_audit(20)
if not audit_lines:
    st.caption("기록된 활동이 없습니다.")
else:
    rows = []
    for line in reversed(audit_lines):  # 최신부터
        ts = line.get("ts") or ""
        when_label = "-"
        if ts:
            try:
                when_label = humanize(from_iso(ts), ref=NOW)
            except Exception:  # noqa: BLE001
                when_label = ts
        rows.append(
            {
                "시각": when_label,
                "요약": _format_audit_summary(line),
                "항목": line.get("item_id") or "-",
            }
        )
    st.dataframe(
        pd.DataFrame(rows), use_container_width=True, hide_index=True
    )
