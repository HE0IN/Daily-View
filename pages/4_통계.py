"""진척도 대시보드 페이지 (단순화 버전).

사용자 요구에 맞춰 "지금 뭐하고 있는지" 만 빠르게 파악할 수 있도록 재구성.
담당자별 표 / 최근 활동 섹션은 제거하고, 카테고리별 정체 카운트를 중심으로
배치한다.

섹션:
    1) 핵심 KPI 4 개 (이번 주 완료 / 진행 중 / 대기 중 / 정체)
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
from ui.auth import get_or_init_user, render_project_selector, require_user
from ui.components import humanize_dt, render_count_metric
from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_LABELS,
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
_user = require_user()
current_project: str | None = render_project_selector(user_name=_user["name"])

if current_project:
    st.title(f"진척도 대시보드 — {current_project}")
else:
    st.title("진척도 대시보드")
st.caption(
    "지금 무엇을 하고 있는지, 카테고리별로 정체된 게 얼마나 있는지 한 눈에 봅니다."
)


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

# 아카이브/완료 포함한 전체 항목 (카운트 정확성을 위해)
# 사이드바 프로젝트 선택기가 켜져 있으면 해당 프로젝트만 집계 대상.
all_entries: list[IndexEntry] = repository.list_issues(
    include_archived=True, include_closed=True, project=current_project
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

# 정체 — 활성 항목 중 마지막 갱신이 STALE_DAYS 일 이상 경과
_stale_threshold: datetime = NOW - timedelta(days=STALE_DAYS)
stale_count = int(
    (df.loc[active_mask, "updated_at_dt"] < _stale_threshold).sum()
)

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
        f"정체 ({STALE_DAYS}일 이상)", stale_count, color="#DC2626"
    )

st.divider()


# ---------------------------------------------------------------------------
# 2) 카테고리(L1)별 진행 상황 — 정체 카운트 중심
# ---------------------------------------------------------------------------

st.subheader("카테고리별 진행 상황")
st.caption(
    f"'정체' = 활성 상태(완료/아카이브 제외)인데 마지막 갱신이 {STALE_DAYS}일 이상 지난 항목."
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

    # pandas 2.1 에서 Styler.applymap 이 deprecate 되고 2.2 에서 제거됨.
    # 대체: Styler.map. 구버전 호환을 위해 getattr 로 fallback.
    _styler = cat_table.style
    _style_fn = getattr(_styler, "map", None) or _styler.applymap
    styled = _style_fn(_highlight_stalled, subset=["정체"])
    st.dataframe(styled, width="stretch", hide_index=True)

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
        pd.DataFrame(rows), width="stretch", hide_index=True
    )

st.divider()


# ---------------------------------------------------------------------------
# 5) 카테고리 상세 분석 — 긴급도 매트릭스 / 상태 누적 / 평균 처리·정체율·재요청
# ---------------------------------------------------------------------------

st.subheader("카테고리 상세 분석")
st.caption(
    "카테고리(L1) 별로 긴급도 분포, 상태 분포, 평균 처리 시간/정체율/재요청을 확인합니다. "
    "미분류 항목은 통계에서 제외합니다."
)


URGENCY_ORDER: list[str] = ["critical", "high", "normal", "low"]
STATUS_ORDER_FOR_STACK: list[str] = [
    "requested",
    "in_progress",
    "api_check",
    "reviewing",
    "reopened",
    "closed",
]


@st.cache_data(ttl=30)
def _build_category_detail(records_payload: list[dict]) -> dict[str, pd.DataFrame]:
    """카테고리(L1)별 상세 통계 3 종을 한 번에 계산.

    반환:
        - "urgency_matrix": L1 × 긴급도 카운트 (라벨 컬럼)
        - "status_stack": L1 × 상태 카운트 (라벨 컬럼)
        - "summary": L1 별 평균 처리 시간(시간) / 정체율 / 재요청 횟수
    """
    # 카테고리 → 긴급도 카운트
    urgency_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {u: 0 for u in URGENCY_ORDER}
    )
    # 카테고리 → 상태 카운트
    status_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {s: 0 for s in STATUS_ORDER_FOR_STACK}
    )
    # 카테고리 → 처리 시간(초) 리스트 / 활성·정체 카운트 / 재요청 카운트
    proc_secs: dict[str, list[float]] = defaultdict(list)
    active_cnt: dict[str, int] = defaultdict(int)
    stale_cnt: dict[str, int] = defaultdict(int)
    reopen_cnt: dict[str, int] = defaultdict(int)
    total_cnt: dict[str, int] = defaultdict(int)

    for data in records_payload:
        try:
            issue = Issue.model_validate(data)
        except Exception:  # noqa: BLE001
            continue
        l1 = (issue.category_l1 or "").strip()
        if not l1:
            # 미분류 — 통계에서 제외
            continue

        total_cnt[l1] += 1

        # 긴급도 분포 — done(레거시) 등 4 값에 포함된 것만 집계
        u = issue.urgency.value
        if u in urgency_counts[l1]:
            urgency_counts[l1][u] += 1

        # 상태 분포 — done 은 closed 로 합산 (레거시 호환)
        s = issue.status.value
        if s == Status.done.value:
            status_counts[l1]["closed"] += 1
        elif s in status_counts[l1]:
            status_counts[l1][s] += 1

        # 평균 처리 시간 (closed 항목만)
        is_closed_like = issue.archived or s in (Status.closed.value, Status.done.value)
        if is_closed_like:
            ca = _closed_at(issue)
            if ca is not None and issue.created_at is not None:
                delta = (ca - issue.created_at).total_seconds()
                if delta >= 0:
                    proc_secs[l1].append(delta)

        # 활성 / 정체 (정체율 계산용)
        if (s in ACTIVE_STATUSES) and (not issue.archived) and (s != Status.closed.value):
            active_cnt[l1] += 1
            if issue.updated_at <= STALE_CUTOFF:
                stale_cnt[l1] += 1

        # 재요청 횟수: status_history 안에 reopened 가 한 번이라도 등장하는 항목 수
        if any(ev.status == Status.reopened for ev in issue.status_history):
            reopen_cnt[l1] += 1

    if not total_cnt:
        return {
            "urgency_matrix": pd.DataFrame(),
            "status_stack": pd.DataFrame(),
            "summary": pd.DataFrame(),
        }

    cats: list[str] = sorted(total_cnt.keys(), key=lambda k: (-total_cnt[k], k))

    # 긴급도 매트릭스 — 라벨 컬럼명, 0 은 빈 문자열로
    urg_rows = []
    for c in cats:
        row: dict[str, object] = {"카테고리": c}
        for u in URGENCY_ORDER:
            n = urgency_counts[c][u]
            row[URGENCY_LABELS.get(u, u)] = n if n > 0 else ""
        row["전체"] = total_cnt[c]
        urg_rows.append(row)
    urgency_matrix = pd.DataFrame(urg_rows)

    # 상태 누적 — 인덱스가 카테고리, 컬럼은 한글 라벨
    stk_rows = []
    for c in cats:
        row = {"카테고리": c}
        for s in STATUS_ORDER_FOR_STACK:
            row[STATUS_LABELS.get(s, s)] = status_counts[c][s]
        stk_rows.append(row)
    status_stack = pd.DataFrame(stk_rows).set_index("카테고리")

    # 요약 — 평균 처리 / 정체율 / 재요청
    sum_rows = []
    for c in cats:
        secs = proc_secs[c]
        avg_h = round(sum(secs) / len(secs) / 3600.0, 1) if secs else None
        if active_cnt[c] > 0:
            stall_pct = round(stale_cnt[c] / active_cnt[c] * 100.0, 1)
        else:
            stall_pct = 0.0
        sum_rows.append(
            {
                "카테고리": c,
                "전체": total_cnt[c],
                "평균 처리 (시간)": avg_h if avg_h is not None else "-",
                "정체 (활성 중 %)": f"{stall_pct}%"
                if active_cnt[c] > 0
                else "-",
                "재요청 횟수": reopen_cnt[c],
            }
        )
    summary = pd.DataFrame(sum_rows)

    return {
        "urgency_matrix": urgency_matrix,
        "status_stack": status_stack,
        "summary": summary,
    }


_detail = _build_category_detail(_issue_payload)

if _detail["summary"].empty:
    st.caption("분류된(L1 카테고리 있음) 항목이 아직 없습니다.")
else:
    # ---- § 5.1 카테고리 × 긴급도 매트릭스 ----
    st.markdown("**카테고리 × 긴급도 매트릭스**")
    st.caption("0 인 셀은 빈 칸으로 표시.")
    st.dataframe(
        _detail["urgency_matrix"], width="stretch", hide_index=True
    )

    # ---- § 5.2 카테고리 × 상태 누적 막대 ----
    st.markdown("**카테고리 × 상태 분포 (누적 막대)**")
    # 모두 0 인 컬럼은 차트 가독성을 위해 제거
    _stk = _detail["status_stack"]
    _stk = _stk.loc[:, (_stk.sum(axis=0) > 0)]
    if _stk.empty:
        st.caption("표시할 상태 데이터가 없습니다.")
    else:
        st.bar_chart(_stk)

    # ---- § 5.3 평균 처리 / 정체율 / 재요청 요약 ----
    st.markdown("**카테고리별 평균 처리 시간 / 정체율 / 재요청**")
    st.caption(
        f"평균 처리: 완료(closed/archived) 항목의 (closed_at − created_at) 평균 시간. "
        f"정체율: 활성 중 마지막 갱신이 {STALE_DAYS}일 이상 지난 비율. "
        "재요청 횟수: status_history 에 reopened 가 한 번이라도 등장한 항목 수."
    )
    st.dataframe(
        _detail["summary"], width="stretch", hide_index=True
    )
