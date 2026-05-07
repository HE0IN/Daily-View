"""Daily View 진입점 — 대시보드.

docs/03_ui_design.md 3.3 + docs/07_scenarios.md 7.3, 7.4 절을 따른다.
역할(검토자/개발자)에 따라 카드 섹션 구성과 메인 CTA가 달라진다.

- 환경 부트스트랩(``ensure_data_dirs`` / ``verify_index`` / ``auto_archive_closed``)은
  세션당 1회만 실행 (``st.session_state`` 플래그로 가드).
- 카드 클릭 시 ``?id=`` query param 을 세팅하고 상세보기 페이지로 이동.
- 사이드바 액션 큐 카운트는 역할별 라벨로 표시.
"""

from __future__ import annotations

import os

import streamlit as st

from core import paths, repository
from core.index import rebuild_index, verify_index
from core.logger import tail_audit
from core.models import Status
from ui import components
from ui.auth import get_or_init_user, render_project_selector
from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_COLORS,
    URGENCY_LABELS,
)

# 자동 새로고침 (M3, docs/04_workflow.md 4.5). 미설치 시 graceful degradation.
try:  # pragma: no cover - 환경 의존
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
except Exception:  # noqa: BLE001
    _st_autorefresh = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 페이지 메타
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Daily View",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# 1회성 부트스트랩
# ---------------------------------------------------------------------------


def _bootstrap_once() -> None:
    """세션당 1회만 실행: 디렉토리 보장 + 인덱스 점검 + 자동 아카이브.

    데이터 디렉토리 생성 실패는 치명적이므로 ``st.error`` + ``st.stop`` 으로
    중단한다. 인덱스 손상은 자동 재구축으로 복구를 시도한다.
    """
    if st.session_state.get("_bootstrap_done"):
        return

    # 1) 디렉토리 보장 — 실패 시 앱 자체 진행 불가
    try:
        paths.ensure_data_dirs()
    except Exception as exc:  # pragma: no cover - 부팅 단계 안전망
        st.error(
            f"데이터 디렉토리를 준비하지 못했습니다: {exc}\n\n"
            f"`.env` 의 `DATA_DIR` 경로를 확인하거나 권한을 점검해주세요."
        )
        st.stop()

    # 2) 인덱스 정합성 점검 — 문제 있으면 자동 재빌드.
    try:
        ok, problems = verify_index()
        if not ok:
            count = rebuild_index()
            st.toast(
                f"인덱스를 재구축했습니다 ({count}건, 문제 {len(problems)}건 감지)",
                icon="🔄",
            )
    except Exception as exc:  # pragma: no cover - 부팅 단계 안전망
        # 점검 자체가 실패하면 한 번 더 강제 재구축 시도
        try:
            count = rebuild_index()
            st.toast(f"인덱스 재구축 완료 ({count}건)", icon="🔄")
        except Exception as rebuild_exc:  # noqa: BLE001
            st.warning(
                f"인덱스 점검/재구축 실패: {exc} / rebuild: {rebuild_exc}"
            )

    # 3) 14일 지난 검토완료 항목 자동 아카이브 (1회).
    try:
        archived = repository.auto_archive_closed(14)
        if archived > 0:
            st.toast(f"오래된 항목 {archived}건을 보관함으로 이동했습니다", icon="📦")
    except Exception as exc:  # pragma: no cover
        st.warning(f"자동 아카이브 실패: {exc}")

    st.session_state["_bootstrap_done"] = True


_bootstrap_once()


# ---------------------------------------------------------------------------
# 자동 새로고침 (다른 사용자 변경 반영용; 환경변수 0 이면 비활성)
# ---------------------------------------------------------------------------

if _st_autorefresh is not None:
    try:
        _refresh_sec = int(os.environ.get("AUTO_REFRESH_SEC", "30"))
    except ValueError:
        _refresh_sec = 30
    if _refresh_sec > 0:
        _st_autorefresh(interval=_refresh_sec * 1000, key="dashboard_auto_refresh")


# ---------------------------------------------------------------------------
# 사용자 식별
# ---------------------------------------------------------------------------

user = get_or_init_user()
if not user:
    st.title("Daily View")
    st.info("좌측 사이드바에서 이름과 역할을 입력하면 시작합니다.")
    st.stop()

name: str = user["name"]
role: str = user.get("role", "reviewer")
role_label = "검토자" if role == "reviewer" else "개발자"

# 프로젝트 사이드바 선택기 — 모든 list_issues 호출에 필터로 전달.
current_project: str | None = render_project_selector(user_name=name)


# ---------------------------------------------------------------------------
# 카드 그리드 CSS — 같은 행 카드들이 가장 긴 카드 높이로 stretch
# ---------------------------------------------------------------------------

components.render_card_grid_css()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _entries_to_dicts(entries) -> list[dict]:
    """IndexEntry 리스트를 dict 리스트로 직렬화."""
    return [e.model_dump(mode="json") for e in entries]


def _render_card_grid(items: list[dict], *, key_prefix: str, cols: int = 4) -> None:
    """카드 그리드 렌더. 클릭 시 상세보기로 이동."""
    if not items:
        st.info("해당 항목이 없습니다.")
        return

    for row_start in range(0, len(items), cols):
        row = items[row_start : row_start + cols]
        col_objs = st.columns(cols)
        for col, item in zip(col_objs, row):
            with col:
                clicked = components.render_card(
                    item, key_prefix=f"{key_prefix}_{row_start}"
                )
                if clicked:
                    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
                    # session_state 로 ID 를 함께 전달한다 (상세보기에서 둘 다 체크).
                    _iid = item.get("id", "")
                    st.session_state["_detail_item_id"] = _iid
                    st.query_params["id"] = _iid
                    st.switch_page("pages/3_상세보기.py")
        # 빈 칼럼은 그대로 둔다 (Streamlit 자동 처리).


def _count_by(entries, attr: str) -> dict[str, int]:
    """긴급도/상태별 카운트."""
    counts: dict[str, int] = {}
    for e in entries:
        value = getattr(e, attr, None)
        key = value.value if hasattr(value, "value") else (value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

if current_project:
    st.caption(f"{current_project} / 대시보드")
st.title("대시보드")
st.write(f"안녕하세요, **{name}**님 ({role_label})")


# ---------------------------------------------------------------------------
# 데이터 로드 (전체 활성 + 보관함 제외)
# ---------------------------------------------------------------------------

all_active = repository.list_issues(
    include_archived=False, include_closed=True, project=current_project
)
active_only = repository.list_issues(
    include_archived=False, include_closed=False, project=current_project
)


# ---------------------------------------------------------------------------
# 역할별 본문
# ---------------------------------------------------------------------------

if role == "reviewer":
    # ── 검토자 화면 (07_scenarios.md 7.3) ─────────────────────────────────
    cta_col, _ = st.columns([1, 4])
    with cta_col:
        if st.button("+ 새 요청 등록", type="primary", use_container_width=True):
            st.switch_page("pages/2_새요청등록.py")

    st.divider()

    # 검토 대기 — 검토중 상태이면서 내가 등록자.
    # 단순화된 흐름에서는 개발자가 작업 완료 시 바로 reviewing 으로 전환됨.
    # 레거시 done 항목도 포함해서 검토자가 정리할 수 있게.
    review_queue_entries = [
        e
        for e in all_active
        if e.author == name and e.status in (Status.reviewing, Status.done)
    ]
    review_queue = _entries_to_dicts(review_queue_entries)

    st.subheader(f"검토 대기 ({len(review_queue)})")
    st.caption("개발자가 작업을 끝내 검토를 기다리는 항목")
    _render_card_grid(review_queue, key_prefix="reviewer_queue")

    st.divider()

    # 내가 등록한 미해결
    my_open_entries = repository.list_issues(
        author=name,
        include_closed=False,
        include_archived=False,
        project=current_project,
    )
    my_open = _entries_to_dicts(my_open_entries)
    st.subheader(f"내가 등록한 미해결 ({len(my_open)})")
    _render_card_grid(my_open[:9], key_prefix="reviewer_open")
    if len(my_open) > 9:
        st.caption(f"… 외 {len(my_open) - 9}건은 [요청목록]에서 확인")

    st.divider()

    # 전체 현황 (활성 항목 기준)
    st.subheader("전체 현황 (활성)")
    urgency_counts = _count_by(active_only, "urgency")
    status_counts = _count_by(active_only, "status")

    st.markdown("**긴급도별**")
    u_cols = st.columns(3)
    for col, key in zip(u_cols, ["high", "normal", "low"]):
        with col:
            components.render_count_metric(
                URGENCY_LABELS[key],
                urgency_counts.get(key, 0),
                color=URGENCY_COLORS[key],
            )

    st.markdown("**상태별**")
    s_keys = ["requested", "in_progress", "api_check", "done", "reviewing", "reopened"]
    s_cols = st.columns(len(s_keys))
    for col, key in zip(s_cols, s_keys):
        with col:
            components.render_count_metric(
                STATUS_LABELS[key],
                status_counts.get(key, 0),
                color=STATUS_COLORS[key],
            )

    # 사이드바 액션 큐 카운트
    sidebar_count = len(review_queue_entries)
    sidebar_label = f"검토 대기 {sidebar_count}건"

else:
    # ── 개발자 화면 (07_scenarios.md 7.4) ────────────────────────────────
    cta_col, _ = st.columns([1, 4])
    with cta_col:
        if st.button("내 큐 전체 보기", type="primary", use_container_width=True):
            # 요청목록의 담당자 필터를 자기 자신으로 미리 세팅
            st.session_state["list_default_assignee"] = name
            st.switch_page("pages/1_요청목록.py")

    st.divider()

    # 처리 큐 — requested + reopened (전체)
    requested_entries = repository.list_issues(
        status=Status.requested,
        include_archived=False,
        project=current_project,
    )
    reopened_entries = repository.list_issues(
        status=Status.reopened,
        include_archived=False,
        project=current_project,
    )
    queue_entries = list(requested_entries) + list(reopened_entries)
    # updated_at desc 재정렬
    queue_entries.sort(
        key=lambda e: e.model_dump(mode="json").get("updated_at") or "",
        reverse=True,
    )
    queue = _entries_to_dicts(queue_entries)

    st.subheader(f"처리 큐 ({len(queue)})")
    st.caption("요청됨 또는 재요청 상태의 활성 항목")
    _render_card_grid(queue, key_prefix="dev_queue")

    st.divider()

    # 외부 대기 중
    api_entries = repository.list_issues(
        status=Status.api_check,
        include_archived=False,
        project=current_project,
    )
    api_check = _entries_to_dicts(api_entries)
    st.subheader(f"외부 대기 중 ({len(api_check)})")
    st.caption("외부 API 답변 대기 중인 항목")
    _render_card_grid(api_check, key_prefix="dev_api")

    st.divider()

    # 최근 내 활동 (audit.log)
    st.subheader("최근 내 활동")
    log_lines = tail_audit(50)
    my_lines = [line for line in log_lines if line.get("actor") == name][-5:]
    if not my_lines:
        st.info("아직 활동 기록이 없습니다.")
    else:
        for line in reversed(my_lines):  # 최신부터
            ts = line.get("ts", "")
            action = line.get("action", "")
            item_id = line.get("item_id") or ""
            st.markdown(
                f"- **{components.humanize_dt(ts)}** · `{action}` · `#{item_id}`"
            )

    sidebar_count = len(queue_entries)
    sidebar_label = f"처리 대기 {sidebar_count}건"


# ---------------------------------------------------------------------------
# 사이드바 액션 큐 카운트
# ---------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    st.markdown(f"**내 액션 큐**: {sidebar_label}")
