"""Dummy data + in-memory state for the prototype.

Everything lives in st.session_state so navigating between pages preserves changes,
but a browser refresh resets to defaults.
"""
from datetime import timedelta
import streamlit as st
from _ui import now


def _ago(*, days=0, hours=0, minutes=0):
    return now() - timedelta(days=days, hours=hours, minutes=minutes)


def _build_default_items():
    return [
        {
            "id": "2026-04-28_a3f1b2",
            "title": "로그인 시 500 에러 발생",
            "description": (
                "OAuth 콜백 후 토큰 교환 단계에서 500 에러.\n\n"
                "**재현 절차**\n"
                "1. 메인 화면에서 [로그인] 클릭\n"
                "2. 카카오 계정 선택 후 동의\n"
                "3. 콜백 URL 복귀 시 500\n\n"
                "**환경**: Chrome 120, Edge 119"
            ),
            "urgency": "high",
            "status": "requested",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(minutes=30),
            "updated_at": _ago(minutes=30),
            "images_count": 2,
            "comments_count": 0,
            "tags": ["login", "auth"],
            "archived": False,
        },
        {
            "id": "2026-04-27_d5f2e1",
            "title": "팝업 X버튼 동작 안함",
            "description": "공지 팝업의 X 버튼이 클릭되지 않음. 영역 외 클릭으로만 닫힘.",
            "urgency": "high",
            "status": "reopened",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=2),
            "updated_at": _ago(hours=4),
            "images_count": 1,
            "comments_count": 6,
            "tags": ["ui", "popup"],
            "archived": False,
        },
        {
            "id": "2026-04-27_x1y2z3",
            "title": "사용자 목록 정렬 변경",
            "description": "최근 수정일 기준 내림차순으로 변경 요청.",
            "urgency": "normal",
            "status": "in_progress",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=1, hours=5),
            "updated_at": _ago(hours=6),
            "images_count": 1,
            "comments_count": 2,
            "tags": ["ui"],
            "archived": False,
        },
        {
            "id": "2026-04-23_e8a3b2",
            "title": "비밀번호 변경 시 안내 메일 미발송",
            "description": "비밀번호 변경 후 안내 메일이 오지 않음. 메일 서비스 측 이슈 의심.",
            "urgency": "normal",
            "status": "api_check",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=5),
            "updated_at": _ago(days=4),
            "images_count": 0,
            "comments_count": 3,
            "tags": ["mail", "external"],
            "archived": False,
        },
        {
            "id": "2026-04-28_b9d2c1",
            "title": "차트 색상 표준화",
            "description": "대시보드 차트 색상을 디자인 가이드대로 통일.",
            "urgency": "normal",
            "status": "done",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(hours=8),
            "updated_at": _ago(hours=1),
            "images_count": 2,
            "comments_count": 4,
            "tags": ["ui", "chart"],
            "archived": False,
        },
        {
            "id": "2026-04-28_c4e8a0",
            "title": "메뉴 정렬 오류",
            "description": "사이드바 메뉴 순서가 설정과 다르게 표시됨.",
            "urgency": "normal",
            "status": "done",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "박OO",
            "created_at": _ago(days=1),
            "updated_at": _ago(hours=5),
            "images_count": 1,
            "comments_count": 2,
            "tags": ["ui", "menu"],
            "archived": False,
        },
        {
            "id": "2026-04-28_f7g8h9",
            "title": "푸터 저작권 문구 오타",
            "description": "푸터의 저작권 연도가 2025로 되어 있음. 2026으로 수정 필요.",
            "urgency": "low",
            "status": "requested",
            "author": "박OO",
            "author_role": "reviewer",
            "assignee": None,
            "created_at": _ago(hours=3),
            "updated_at": _ago(hours=3),
            "images_count": 1,
            "comments_count": 0,
            "tags": ["text"],
            "archived": False,
        },
        {
            "id": "2026-04-27_p1q2r3",
            "title": "검색 결과 페이지네이션 누락",
            "description": "검색 결과가 30건 이상일 때 페이지네이션이 안 보임.",
            "urgency": "normal",
            "status": "reviewing",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=2),
            "updated_at": _ago(hours=2),
            "images_count": 1,
            "comments_count": 3,
            "tags": ["search"],
            "archived": False,
        },
        {
            "id": "2026-04-25_done01",
            "title": "프로필 이미지 업로드 실패",
            "description": "5MB 이상 이미지 업로드 시 무한 로딩.",
            "urgency": "high",
            "status": "closed",
            "author": "김OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=4),
            "updated_at": _ago(days=2),
            "images_count": 2,
            "comments_count": 5,
            "tags": ["upload"],
            "archived": False,
        },
        {
            "id": "2026-04-24_done02",
            "title": "리포트 다운로드 한글 깨짐",
            "description": "엑셀 다운로드 시 한글이 깨져서 나옴.",
            "urgency": "normal",
            "status": "closed",
            "author": "박OO",
            "author_role": "reviewer",
            "assignee": "이OO",
            "created_at": _ago(days=5),
            "updated_at": _ago(days=3),
            "images_count": 1,
            "comments_count": 2,
            "tags": ["report", "encoding"],
            "archived": False,
        },
    ]


def _build_default_comments():
    return {
        "2026-04-28_a3f1b2": [],
        "2026-04-27_d5f2e1": [
            {"id": "c001", "at": _ago(days=2), "author": "김OO", "role": "reviewer",
             "body": "공지 팝업의 X 버튼이 클릭되지 않습니다. 영역 외 클릭으로만 닫힙니다.", "kind": "comment"},
            {"id": "c002", "at": _ago(days=2) + timedelta(hours=2), "author": "이OO", "role": "developer",
             "body": "확인하겠습니다.", "kind": "comment"},
            {"id": "c003", "at": _ago(days=1, hours=8), "author": "system", "role": "system",
             "body": "상태 변경: 확인중 → 완료", "kind": "system"},
            {"id": "c004", "at": _ago(days=1, hours=8), "author": "이OO", "role": "developer",
             "body": "수정 적용했습니다, 확인 부탁드립니다.", "kind": "comment"},
            {"id": "c005", "at": _ago(hours=4), "author": "system", "role": "system",
             "body": "상태 변경: 검토중 → 재요청", "kind": "system"},
            {"id": "c006", "at": _ago(hours=4), "author": "김OO", "role": "reviewer",
             "body": "여전히 동일 증상입니다. 캐시 무효화도 함께 필요한 것 같습니다.", "kind": "comment"},
        ],
        "2026-04-27_x1y2z3": [
            {"id": "c001", "at": _ago(days=1, hours=5), "author": "김OO", "role": "reviewer",
             "body": "정렬을 최근 수정일 내림차순으로 부탁드립니다.", "kind": "comment"},
            {"id": "c002", "at": _ago(hours=6), "author": "system", "role": "system",
             "body": "상태 변경: 요청됨 → 확인중", "kind": "system"},
        ],
        "2026-04-23_e8a3b2": [
            {"id": "c001", "at": _ago(days=5), "author": "김OO", "role": "reviewer",
             "body": "비밀번호 변경 후 안내 메일이 오지 않습니다.", "kind": "comment"},
            {"id": "c002", "at": _ago(days=4, hours=2), "author": "이OO", "role": "developer",
             "body": "메일 서비스 응답 형식이 변경된 것 같습니다. 외부 팀에 문의 보냈습니다.", "kind": "comment"},
            {"id": "c003", "at": _ago(days=4), "author": "system", "role": "system",
             "body": "상태 변경: 확인중 → API대기", "kind": "system"},
        ],
        "2026-04-28_b9d2c1": [
            {"id": "c001", "at": _ago(hours=8), "author": "김OO", "role": "reviewer",
             "body": "차트 색상을 가이드대로 통일해 주세요.", "kind": "comment"},
            {"id": "c002", "at": _ago(hours=2), "author": "system", "role": "system",
             "body": "상태 변경: 요청됨 → 확인중", "kind": "system"},
            {"id": "c003", "at": _ago(hours=1), "author": "이OO", "role": "developer",
             "body": "적용 완료했습니다, 확인 부탁드립니다.", "kind": "comment"},
            {"id": "c004", "at": _ago(hours=1), "author": "system", "role": "system",
             "body": "상태 변경: 확인중 → 완료", "kind": "system"},
        ],
        "2026-04-28_c4e8a0": [
            {"id": "c001", "at": _ago(days=1), "author": "김OO", "role": "reviewer",
             "body": "메뉴 순서가 설정과 다르게 표시됩니다.", "kind": "comment"},
            {"id": "c002", "at": _ago(hours=5), "author": "박OO", "role": "developer",
             "body": "정렬 로직 수정 완료했습니다.", "kind": "comment"},
        ],
        "2026-04-28_f7g8h9": [],
        "2026-04-27_p1q2r3": [
            {"id": "c001", "at": _ago(days=2), "author": "김OO", "role": "reviewer",
             "body": "검색 결과 30건 이상에서 페이지네이션이 보이지 않습니다.", "kind": "comment"},
            {"id": "c002", "at": _ago(days=1), "author": "이OO", "role": "developer",
             "body": "수정 완료, 확인 부탁드립니다.", "kind": "comment"},
            {"id": "c003", "at": _ago(hours=2), "author": "system", "role": "system",
             "body": "상태 변경: 완료 → 검토중", "kind": "system"},
        ],
        "2026-04-25_done01": [],
        "2026-04-24_done02": [],
    }


def get_items():
    """Return the items list (initialized once per session)."""
    if "items" not in st.session_state:
        st.session_state["items"] = _build_default_items()
        st.session_state["comments"] = _build_default_comments()
    return st.session_state["items"]


def get_item(item_id):
    for it in get_items():
        if it["id"] == item_id:
            return it
    return None


def update_item(item_id, **kwargs):
    for it in get_items():
        if it["id"] == item_id:
            it.update(kwargs)
            it["updated_at"] = now()
            return it
    return None


def get_comments(item_id):
    if "comments" not in st.session_state:
        get_items()
    return st.session_state["comments"].get(item_id, [])


def add_comment(item_id, body, author, role, *, kind="comment"):
    if "comments" not in st.session_state:
        get_items()
    comments = st.session_state["comments"].setdefault(item_id, [])
    new_id = f"c{len(comments) + 1:03d}"
    comments.append({
        "id": new_id,
        "at": now(),
        "author": author,
        "role": role,
        "body": body,
        "kind": kind,
    })
    update_item(item_id, comments_count=len(comments))


def add_item(item):
    items = get_items()
    items.insert(0, item)
    if "comments" not in st.session_state:
        st.session_state["comments"] = {}
    st.session_state["comments"].setdefault(item["id"], [])
