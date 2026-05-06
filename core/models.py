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
    """긴급도. docs/04_workflow.md 4.4 절."""

    high = "high"
    normal = "normal"
    low = "low"


class Status(str, Enum):
    """이슈 상태. docs/04_workflow.md 4.1 절."""

    requested = "requested"
    in_progress = "in_progress"
    api_check = "api_check"
    done = "done"
    reviewing = "reviewing"
    reopened = "reopened"
    closed = "closed"


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


class Comment(BaseModel):
    """코멘트 한 건. comments.jsonl 한 줄과 1:1 대응."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    at: datetime
    author: str
    role: Role | Literal["system"]
    body: str
    kind: Literal["comment", "system"] = "comment"


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
    status: Status = Status.requested
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


class IndexEntry(BaseModel):
    """index.json items[*] 항목. docs/02_storage.md 2.7 절."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    title: str
    urgency: Urgency
    status: Status
    author: str
    assignee: str | None = None
    created_at: datetime
    updated_at: datetime
    comments_count: int = 0
    images_count: int = 0
    reviewer_confirmed: bool = False
    archived: bool = False
    tags: list[str] = []

    @classmethod
    def from_issue(
        cls,
        issue: Issue,
        comments_count: int,
        images_count: int,
    ) -> IndexEntry:
        """Issue 와 카운트로부터 인덱스 엔트리 생성."""
        return cls(
            id=issue.id,
            title=issue.title,
            urgency=issue.urgency,
            status=issue.status,
            author=issue.author,
            assignee=issue.assignee,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            comments_count=comments_count,
            images_count=images_count,
            reviewer_confirmed=issue.reviewer_confirmed,
            archived=issue.archived,
            tags=list(issue.tags),
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
