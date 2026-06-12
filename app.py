"""Daily View 진입점 — st.navigation 라우터.

공통 처리(부트스트랩·자동새로고침·사용자식별·프로젝트선택)를 여기서 수행하고,
선택된 페이지를 ``pg.run()`` 으로 실행한다. 대시보드 본문은 ``pages/0_대시보드.py``.

메뉴 구성:
    대시보드  ─선─  새 요청 등록(강조)  ─선─  요청목록 · 통계
상세보기는 메뉴에서 숨김(카드 클릭으로만 진입). 숨김/강조는 CSS 로 처리하며,
Streamlit 버전에 따라 selector 가 달라질 수 있어 한 곳에 모아둔다.
"""

from __future__ import annotations

import os

import streamlit as st

from core import paths, repository
from core.index import rebuild_index, verify_index
from ui.auth import get_or_init_user, render_project_selector

# 자동 새로고침 (미설치 시 graceful degradation).
try:  # pragma: no cover - 환경 의존
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
except Exception:  # noqa: BLE001
    _st_autorefresh = None  # type: ignore[assignment]


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
    """세션당 1회만 실행: 디렉토리 보장 + 인덱스 점검 + 자동 아카이브."""
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
        _st_autorefresh(interval=_refresh_sec * 1000, key="global_auto_refresh")


# ---------------------------------------------------------------------------
# 사용자 식별 + 프로젝트 선택 (사이드바, 모든 페이지 공통)
# ---------------------------------------------------------------------------

user = get_or_init_user()
if not user:
    st.title("Daily View")
    st.info("좌측 사이드바에서 이름을 선택하거나 새로 등록하면 시작합니다.")
    st.stop()

render_project_selector(user_name=user["name"])


# ---------------------------------------------------------------------------
# 페이지 정의 + 네비게이션
# ---------------------------------------------------------------------------

_dashboard = st.Page(
    "pages/0_대시보드.py", title="대시보드", icon=":material/dashboard:", default=True
)
_my_work = st.Page(
    "pages/0b_내작업.py", title="내 작업", icon=":material/assignment_ind:"
)
_vendor_req = st.Page(
    "pages/0c_개발사요청.py", title="개발사 요청", icon=":material/forward_to_inbox:"
)
_new = st.Page(
    "pages/2_새요청등록.py", title="새 요청 등록", icon=":material/add_circle:"
)
_list = st.Page("pages/1_요청목록.py", title="개발목록", icon=":material/list_alt:")
_stats = st.Page("pages/4_통계.py", title="통계", icon=":material/bar_chart:")
_detail = st.Page(
    "pages/3_상세보기.py", title="상세보기", icon=":material/description:"
)
_confirm_req = st.Page(
    "pages/5_미구현목록.py",
    title="확인 요청",
    icon=":material/playlist_add:",
)
_confirm_list = st.Page(
    "pages/6_확인요청목록.py",
    title="확인요청목록",
    icon=":material/fact_check:",
)
_criteria = st.Page(
    "pages/7_확인목록.py",
    title="Temp",
    icon=":material/checklist:",
)

# 메뉴 스타일: 상세보기 항목 숨김 + 새 요청 등록 강조(빨강).
# Streamlit 의 사이드바 네비 링크는 a[href] 에 페이지 슬러그가 들어간다.
# 한글 슬러그는 percent-encoding 되므로 부분 매칭으로 시도한다.
st.markdown(
    """
    <style>
    /* 페이지 본문 상단 여백 축소 — Streamlit 기본 padding-top 이 과도하게 큼.
       버전별 컨테이너 이름이 달라 여러 selector 를 함께 지정. */
    .block-container,
    section.main > div.block-container,
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stAppViewBlockContainer"] {
        padding-top: 2rem !important;
    }
    /* 13번: 파일 업로더 dropzone 축소 — 사진/파일만 넣는 곳이라 작아도 됨.
       드래그 안내문구는 숨기고 [Browse files] 클릭만으로 쓰게 한다. */
    [data-testid="stFileUploaderDropzone"] {
        min-height: 2.2rem !important;
        padding: 0.2rem 0.75rem !important;
        align-items: center !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] {
        display: none !important;
    }
    /* 상세보기 메뉴 항목 숨김 — 카드 클릭으로만 진입 */
    section[data-testid="stSidebarNav"] li:has(a[href*="%EC%83%81%EC%84%B8"]) {
        display: none !important;
    }
    /* 새 요청 등록 강조 (빨강 배경 + 흰 글씨) */
    section[data-testid="stSidebarNav"] li:has(a[href*="%EC%83%88_%EC%9A%94%EC%B2%AD"]) a {
        background: #DC2626 !important;
        border-radius: 6px;
    }
    section[data-testid="stSidebarNav"] li:has(a[href*="%EC%83%88_%EC%9A%94%EC%B2%AD"]) a span {
        color: #ffffff !important;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# dict 형태 → 섹션 사이에 구분 영역이 생겨 '선 긋기' 효과.
# 1구역: 개발 흐름(내 작업·개발사 요청·개발목록·새 요청 등록)
# 2구역: 확인 흐름(확인 요청·확인요청목록·Temp)
# 3구역: 조회(대시보드·통계·상세보기) — 대시보드/통계는 추후 통합 예정.
# 상세보기는 3구역에 포함하되 위 CSS 로 사이드바에서 숨긴다.
pg = st.navigation(
    {
        " ": [_my_work, _vendor_req, _list, _new],
        "  ": [_confirm_req, _confirm_list, _criteria],
        "   ": [_dashboard, _stats, _detail],
    }
)
pg.run()
