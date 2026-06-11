"""도메인 모델 (pydantic v2).

docs/04_workflow.md 4.9 절의 정의를 그대로 따른다.
모든 datetime은 timezone-aware(KST) 여야 하며, 직렬화는 pydantic의
``model_dump(mode="json")`` / ``model_validate()`` 를 직접 사용한다.

repository 가 어떤 형태의 직렬화 헬퍼를 별도로 두지 않고 pydantic의 표준
방식만 의존하도록 한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enum 정의
# ---------------------------------------------------------------------------


class Urgency(str, Enum):
    """긴급도. docs/04_workflow.md 4.4 절.

    4 단계: critical (긴급) > high (상) > normal (중) > low (하).
    기존 데이터의 ``high`` 는 의미가 "상" 으로 재해석된다 (라벨만 변경).
    새 ``critical`` 은 신규 등록자만 사용.
    """

    critical = "critical"  # 신규: 긴급 (가장 높음)
    high = "high"          # 라벨 "긴급" → "상" 변경
    normal = "normal"
    low = "low"


class Status(str, Enum):
    """이슈 상태 — 등록자/담당자 워크플로 (10 단계).

    권한은 역할 고정이 아니라 '항목별 위치' 로 결정된다:
      - Role.developer = '담당자' 권한 (issue.assignee == 현재 사용자)
      - Role.reviewer  = '등록자' 권한 (issue.author == 현재 사용자)

    흐름:
      담당자확인요청 → 담당자검토중 → 담당자검토완료
        → (담당자신규개발중 / 담당자코드수정중 / 개발사확인중→개발사회신확인중)
        → 등록자확인요청 → 등록자검토중 → 완료
      (등록자검토중 → 담당자확인요청 으로 반려 가능)
    """

    assignee_request = "assignee_request"        # 담당자확인요청 (새 요청 등록 직후)
    assignee_reviewing = "assignee_reviewing"    # 담당자검토중
    assignee_reviewed = "assignee_reviewed"      # 담당자검토완료
    assignee_developing = "assignee_developing"  # 담당자신규개발중
    assignee_fixing = "assignee_fixing"          # 담당자코드수정중
    vendor_wait = "vendor_wait"                  # 개발사요청대기 (요청 전 모아두기)
    vendor_request = "vendor_request"            # 개발사확인중
    vendor_reply = "vendor_reply"                # 개발사회신확인중
    author_request = "author_request"            # 등록자확인요청
    author_reviewing = "author_reviewing"        # 등록자검토중
    closed = "closed"                            # 완료
    # 확인대기 — 확인요청(unimplemented) 항목 전용. 새요청등록(개발) 또는
    # 확인목록으로 가기 '전' 단계. dev 항목 워크플로우에는 노출되지 않는다.
    pending_check = "pending_check"              # 확인대기
    temp = "temp"                                # Temp (확정 보류 — 옛 '확인목록')


class Role(str, Enum):
    """사용자 역할."""

    reviewer = "reviewer"
    developer = "developer"


# ---------------------------------------------------------------------------
# 보조 모델
# ---------------------------------------------------------------------------


class StatusEvent(BaseModel):
    """상태 전이 이력 한 건."""

    model_config = ConfigDict(use_enum_values=False)

    status: Status
    at: datetime
    by: str  # 사용자 이름


class ImageRef(BaseModel):
    """첨부 이미지 메타. docs/02_storage.md 2.3 절."""

    model_config = ConfigDict(use_enum_values=False)

    file: str
    thumb: str | None = None
    uploaded_at: datetime
    sha256: str
    size_bytes: int
    # 이미지 구분: 요청(AS-IS) / 개발(TO-BE). None = 구분 없음(옛 데이터 호환).
    kind: Literal["request", "dev"] | None = None


class Comment(BaseModel):
    """코멘트 한 건. comments.jsonl 한 줄과 1:1 대응."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    at: datetime
    author: str
    role: Role | Literal["system"]
    body: str
    kind: Literal["comment", "system"] = "comment"
    edited: bool = False  # 수정 여부 — 타임라인에서 '(수정됨)' 표시용 (4번)


# ---------------------------------------------------------------------------
# 메인 모델
# ---------------------------------------------------------------------------


class Issue(BaseModel):
    """이슈(요청) 메타데이터. meta.json 1:1 대응."""

    model_config = ConfigDict(use_enum_values=False)

    schema_version: int = 1
    id: str
    title: str = Field(min_length=1, max_length=120)
    description: str
    urgency: Urgency
    status: Status = Status.assignee_request
    # 항목 종류: dev=개발목록(정식 요청) / unimplemented=미구현목록(가벼운 수집함).
    # unimplemented 는 담당자·상태 워크플로우 없이 제목/설명/캡쳐만 쌓아두는 용도이며,
    # '개발 요청' 으로 승격하면 kind 가 dev 로 바뀌며 담당자확인요청으로 전환된다.
    kind: Literal["dev", "unimplemented", "criteria"] = "dev"
    author: str
    author_role: Role
    assignee: str | None = None
    created_at: datetime
    updated_at: datetime
    status_history: list[StatusEvent] = []
    images: list[ImageRef] = []
    reviewer_confirmed: bool = False
    reviewer_confirmed_at: datetime | None = None
    tags: list[str] = []
    archived: bool = False
    # 카테고리 3 단계 (대 / 중 / 소). 모두 optional — 기존 meta.json 도 그대로 호환.
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    # 프로젝트 식별자 (자유 문자열). 사이드바에서 현재 프로젝트로 필터링.
    # 기존 meta.json 호환을 위해 optional — 누락 시 None 으로 처리.
    project: str | None = None


class IndexEntry(BaseModel):
    """index.json items[*] 항목. docs/02_storage.md 2.7 절."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    title: str
    urgency: Urgency
    status: Status
    kind: Literal["dev", "unimplemented", "criteria"] = "dev"
    author: str
    assignee: str | None = None
    created_at: datetime
    updated_at: datetime
    comments_count: int = 0
    images_count: int = 0
    reviewer_confirmed: bool = False
    archived: bool = False
    tags: list[str] = []
    # 카테고리 3 단계 — 목록 필터·표시용. Issue 와 동일 의미.
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    # 프로젝트 식별자 — 사이드바 프로젝트 선택용 필터.
    project: str | None = None
    # 첫 첨부 이미지의 thumb 또는 file 상대 경로 (item_dir 기준).
    # 카드에서 paths.item_dir(id) 와 결합해 절대경로로 변환.
    first_image_thumb: str | None = None
    # 길면 잘라낸 설명 미리보기 (예: 200자). 카드 노출용.
    description_preview: str = ""

    @classmethod
    def from_issue(
        cls,
        issue: Issue,
        comments_count: int,
        images_count: int,
    ) -> IndexEntry:
        """Issue 와 카운트로부터 인덱스 엔트리 생성."""
        first_image_thumb = None
        # 썸네일이 있는 첫 이미지를 사용. PDF 등 thumb 가 없는 첨부는 건너뛴다
        # (file 로 폴백하면 카드에서 이미지로 디코드를 시도하다 깨진다).
        for _img in issue.images:
            if _img.thumb:
                first_image_thumb = _img.thumb
                break
        desc = issue.description or ""
        description_preview = desc[:200]
        return cls(
            id=issue.id,
            title=issue.title,
            urgency=issue.urgency,
            status=issue.status,
            kind=issue.kind,
            author=issue.author,
            assignee=issue.assignee,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            comments_count=comments_count,
            images_count=images_count,
            reviewer_confirmed=issue.reviewer_confirmed,
            archived=issue.archived,
            tags=list(issue.tags),
            category_l1=issue.category_l1,
            category_l2=issue.category_l2,
            category_l3=issue.category_l3,
            project=issue.project,
            first_image_thumb=first_image_thumb,
            description_preview=description_preview,
        )


__all__ = [
    "Urgency",
    "Status",
    "Role",
    "StatusEvent",
    "ImageRef",
    "Comment",
    "Issue",
    "IndexEntry",
]
