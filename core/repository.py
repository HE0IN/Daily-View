"""디스크 I/O 단일 진입점.

UI / 페이지는 본 모듈만 호출한다. docs/01_architecture.md 1.3, 1.6 절과
docs/02_storage.md 전반을 따른다.

규칙
----
- 모든 시간은 :func:`core.clock.now` 만 사용 (호출자가 datetime 을 넘기지 않음)
- 상태 변경은 :func:`core.workflow.assert_transition` 으로 가드
- 쓰기 함수는 모두 audit_log 를 남기고 인덱스를 갱신
- meta.json 갱신 시 ``updated_at`` 자동 설정
"""

from __future__ import annotations

import json
import secrets
import uuid
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from . import images as images_mod
from . import index as index_mod
from . import logger as audit
from . import paths
from .clock import from_iso, now
from .images import MAX_IMAGES_PER_ITEM, save_image_bytes, save_pil_image
from .locking import _write_json_unlocked, atomic_append_jsonl, file_lock
from .models import (
    RULE_STATUS_VALUES,
    Comment,
    ImageRef,
    IndexEntry,
    Issue,
    Role,
    Status,
    StatusEvent,
    Urgency,
)
from .workflow import (
    RULE_STATUS_LABELS_KO,
    STATUS_LABELS_KO,
    assert_transition,
)


# ---------------------------------------------------------------------------
# id 생성
# ---------------------------------------------------------------------------


def _new_item_id() -> str:
    """``{YYYY-MM-DD}_{6-hex}`` 형식의 새 id 생성."""
    return f"{now().strftime('%Y-%m-%d')}_{secrets.token_hex(3)}"


def _new_comment_id() -> str:
    """``c`` + uuid4 hex 8자."""
    return "c" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# 락 헬퍼 — 항목별 meta 갱신용
# ---------------------------------------------------------------------------


def _meta_lock_path(item_id: str) -> Path:
    return paths.item_meta_path(item_id).with_suffix(".json.lock")


# ---------------------------------------------------------------------------
# meta.json 입출력 — 내부 헬퍼
# ---------------------------------------------------------------------------


def _read_meta(item_id: str) -> Issue:
    """meta.json 을 읽어 Issue 로 반환. 없거나 파싱 실패 시 예외."""
    path = paths.item_meta_path(item_id)
    if not path.exists():
        raise FileNotFoundError(f"meta.json 없음: {item_id}")
    with open(path, mode="r", encoding="utf-8") as f:
        data = json.load(f)
    return Issue.model_validate(data)


def _write_meta_unlocked(issue: Issue) -> None:
    """Issue 를 meta.json 으로 직렬화. 호출자가 meta 락을 보유 중이라고 가정.

    Windows FileLock 비재진입성 때문에 락 보유 코드 경로는 본 함수를 사용한다.
    """
    payload = issue.model_dump(mode="json")
    _write_json_unlocked(paths.item_meta_path(issue.id), payload)


# ---------------------------------------------------------------------------
# 생성
# ---------------------------------------------------------------------------


def create_issue(
    *,
    title: str,
    description: str,
    urgency: Urgency | str,
    author: str,
    author_role: Role | str,
    assignee: str | None = None,
    tags: list[str] | None = None,
    category_l1: str | None = None,
    category_l2: str | None = None,
    category_l3: str | None = None,
    project: str | None = None,
    kind: str = "dev",
) -> Issue:
    """새 항목 생성.

    폴더/meta.json/빈 comments.jsonl 생성 → audit 로그 → 인덱스 갱신.
    pydantic 검증으로 잘못된 입력은 ValidationError 로 거부.
    카테고리 3 단계는 모두 optional — 빈 문자열은 None 으로 정규화.
    project 도 optional — 빈 문자열은 None 으로 정규화.
    """
    item_id = _new_item_id()
    timestamp = now()
    _kind = kind if kind in ("dev", "unimplemented", "criteria") else "dev"
    # 확인요청(unimplemented) 항목은 '확인대기'로 시작한다 (담당자확인요청 아님).
    _initial_status = (
        Status.pending_check if _kind == "unimplemented" else Status.assignee_request
    )
    # 모델 검증을 mkdir '전에' 수행 — 잘못된 입력(ValidationError/ValueError)이면
    # 여기서 raise 되어 빈 항목 폴더가 남지 않는다 (문제점 #9).
    issue = Issue(
        id=item_id,
        title=title,
        description=description,
        urgency=Urgency(urgency) if not isinstance(urgency, Urgency) else urgency,
        status=_initial_status,
        kind=_kind,
        author=author,
        author_role=Role(author_role) if not isinstance(author_role, Role) else author_role,
        assignee=assignee,
        created_at=timestamp,
        updated_at=timestamp,
        status_history=[
            StatusEvent(status=_initial_status, at=timestamp, by=author),
        ],
        images=[],
        reviewer_confirmed=False,
        reviewer_confirmed_at=None,
        tags=list(tags or []),
        deleted=False,
        deleted_at=None,
        archived=False,
        category_l1=(category_l1.strip() or None) if category_l1 else None,
        category_l2=(category_l2.strip() or None) if category_l2 else None,
        category_l3=(category_l3.strip() or None) if category_l3 else None,
        project=(project.strip() or None) if project else None,
    )

    # 검증을 통과한 뒤에야 디렉토리 생성.
    item_root = paths.item_dir(item_id)
    item_root.mkdir(parents=True, exist_ok=True)
    paths.item_images_dir(item_id).mkdir(parents=True, exist_ok=True)

    # meta.json 작성 (생성이라 경합 가능성은 낮지만 일관성 위해 락 사용)
    with file_lock(_meta_lock_path(item_id)):
        _write_meta_unlocked(issue)

    # 빈 comments.jsonl 생성 (touch)
    comments_path = paths.item_comments_path(item_id)
    if not comments_path.exists():
        comments_path.touch()

    # audit
    audit.audit_log(
        actor=author,
        action=audit.CREATE_ISSUE,
        item_id=item_id,
        detail={"urgency": issue.urgency.value, "title": title},
    )

    # 카테고리 풀 자동 누적 — 새 요청 등록 시 입력한 카테고리가 사이드바
    # selectbox 옵션 풀에 자동으로 추가됨. 별도 [가져오기] 동작 불필요.
    if issue.project and (issue.category_l1 or issue.category_l2 or issue.category_l3):
        try:
            from . import project_settings as _ps
            if issue.category_l1:
                _ps.add_project_category(issue.project, l1=issue.category_l1)
            if issue.category_l2:
                _ps.add_project_category(issue.project, l2=issue.category_l2)
            if issue.category_l3:
                _ps.add_project_category(issue.project, l3=issue.category_l3)
        except Exception:
            pass  # 풀 누적 실패는 항목 생성 자체를 막지 않음

    # 인덱스
    index_mod.update_index_entry(issue, comments_count=0, images_count=0)
    return issue


# ---------------------------------------------------------------------------
# 단건 조회
# ---------------------------------------------------------------------------


def get_issue(item_id: str) -> Issue:
    """meta.json 로드. 없으면 :class:`FileNotFoundError`."""
    return _read_meta(item_id)


# ---------------------------------------------------------------------------
# 목록 조회
# ---------------------------------------------------------------------------


def _entry_matches(
    entry: dict[str, Any],
    *,
    status: Status | str | None,
    urgency: Urgency | str | None,
    assignee: str | None,
    author: str | None,
    search: str | None,
    include_deleted: bool,
    include_closed: bool,
    project: str | None,
) -> bool:
    """단일 인덱스 엔트리가 필터 조건에 부합하는지."""
    if not include_deleted and entry.get("deleted"):
        return False

    entry_status = entry.get("status")
    if not include_closed and entry_status == Status.closed.value:
        return False

    if status is not None:
        target = status.value if isinstance(status, Status) else str(status)
        if entry_status != target:
            return False

    if urgency is not None:
        target = urgency.value if isinstance(urgency, Urgency) else str(urgency)
        if entry.get("urgency") != target:
            return False

    if assignee is not None and entry.get("assignee") != assignee:
        return False

    if author is not None and entry.get("author") != author:
        return False

    if project is not None and entry.get("project") != project:
        return False

    if search:
        needle = search.lower()
        title = (entry.get("title") or "").lower()
        tags = [str(t).lower() for t in entry.get("tags") or []]
        if needle not in title and not any(needle in t for t in tags):
            return False

    return True


def list_issues(
    *,
    status: Status | str | None = None,
    urgency: Urgency | str | None = None,
    assignee: str | None = None,
    author: str | None = None,
    search: str | None = None,
    include_deleted: bool = False,
    include_closed: bool = True,
    project: str | None = None,
    kind: str | None = "dev",
) -> list[IndexEntry]:
    """인덱스 기반 필터링된 목록을 ``updated_at desc`` 로 정렬해 반환.

    kind: "dev"(기본, 개발목록) / "unimplemented"(미구현목록) / None(전체).
    기본이 "dev" 라 기존 호출은 미구현 항목을 자동으로 제외한다.

    ``include_deleted`` 기본 False — 삭제 태그가 붙은 항목만 숨긴다.
    완료(closed) 항목은 ``include_closed`` 로만 제어되며, 삭제와 무관하게
    항상 완료로 집계된다 (2026-08-11: 옛 archived 자동보관이 완료 항목을
    삭제 목록으로 밀어넣던 문제 수정).

    검색은 title/tags 부분 매칭(case-insensitive). 인덱스가 비어 있으면 빈 리스트.
    project 가 주어지면 해당 프로젝트로 필터 — 빈 문자열은 None 과 동일(필터 미적용).
    """
    # 빈 문자열은 필터 미적용으로 정규화 (UI 측 편의).
    if isinstance(project, str) and not project.strip():
        project = None

    raw = index_mod.read_index()
    filtered = [
        e for e in raw
        if _entry_matches(
            e,
            status=status,
            urgency=urgency,
            assignee=assignee,
            author=author,
            search=search,
            include_deleted=include_deleted,
            include_closed=include_closed,
            project=project,
        )
    ]
    # kind 필터 — None 이면 전체, 아니면 해당 종류만 (옛 데이터는 dev 로 간주).
    if kind is not None:
        filtered = [e for e in filtered if (e.get("kind") or "dev") == kind]

    # updated_at desc — ISO 문자열은 사전순 = 시간순.
    filtered.sort(key=lambda e: e.get("updated_at") or "", reverse=True)

    result: list[IndexEntry] = []
    for entry in filtered:
        try:
            result.append(IndexEntry.model_validate(entry))
        except Exception:
            continue
    return result


# ---------------------------------------------------------------------------
# 코멘트
# ---------------------------------------------------------------------------


def list_comments(item_id: str) -> list[Comment]:
    """comments.jsonl 전체를 Comment 리스트로 반환. 손상 라인은 건너뜀."""
    path = paths.item_comments_path(item_id)
    if not path.exists():
        return []

    out: list[Comment] = []
    with open(path, mode="r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(Comment.model_validate_json(raw))
            except Exception:
                # 손상된 코멘트 라인은 스킵 (rebuild 도구에서 후처리 가능)
                continue
    return out


def _append_comment_line(item_id: str, comment: Comment) -> None:
    """comments.jsonl 에 한 줄 append."""
    line_obj = comment.model_dump(mode="json")
    atomic_append_jsonl(paths.item_comments_path(item_id), line_obj)


def add_comment(
    item_id: str,
    author: str,
    role: Role | str,
    body: str,
) -> Comment:
    """일반 코멘트 추가. meta.updated_at 갱신 + audit + 인덱스 카운트 갱신."""
    if not body or not body.strip():
        raise ValueError("코멘트 내용이 비어 있습니다")

    role_value: Role | str
    if isinstance(role, Role):
        role_value = role
    else:
        role_value = Role(role)

    comment = Comment(
        id=_new_comment_id(),
        at=now(),
        author=author,
        role=role_value,
        body=body,
        kind="comment",
    )
    _append_comment_line(item_id, comment)

    # meta.updated_at 갱신
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=author,
        action=audit.ADD_COMMENT,
        item_id=item_id,
        detail={"comment_id": comment.id, "role": str(role_value)},
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return comment


def _add_system_comment(item_id: str, body: str) -> Comment:
    """시스템 코멘트 (상태 변경 등)를 한 줄 append. meta 는 호출자가 갱신."""
    comment = Comment(
        id=_new_comment_id(),
        at=now(),
        author="system",
        role="system",
        body=body,
        kind="system",
    )
    _append_comment_line(item_id, comment)
    return comment


def _rewrite_comments_unlocked(item_id: str, comments: list[Comment]) -> None:
    """comments.jsonl 전체를 재작성 (atomic). 락은 호출자가 보유해야 한다."""
    import json
    import os
    import tempfile

    path = paths.item_comments_path(item_id)
    lines = [
        json.dumps(c.model_dump(mode="json"), ensure_ascii=False)
        for c in comments
    ]
    content = ("\n".join(lines) + "\n") if lines else ""
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    )
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def delete_comment(item_id: str, comment_id: str, actor: str) -> None:
    """일반 코멘트 한 건 삭제 — comments.jsonl 을 해당 라인 제외하고 재작성.

    시스템 코멘트(상태 변경 등 이력)는 삭제 대상에서 제외한다(ValueError).
    """
    with file_lock(_meta_lock_path(item_id)):
        comments = list_comments(item_id)
        target = next((c for c in comments if c.id == comment_id), None)
        if target is None:
            return  # 이미 없음 — noop
        if target.kind == "system":
            raise ValueError("시스템 코멘트(이력)는 삭제할 수 없습니다.")
        kept = [c for c in comments if c.id != comment_id]
        _rewrite_comments_unlocked(item_id, kept)

    audit.audit_log(
        actor=actor,
        action=audit.DELETE_COMMENT,
        item_id=item_id,
        detail={"comment_id": comment_id},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)


def edit_comment(
    item_id: str, comment_id: str, new_body: str, actor: str
) -> None:
    """일반 코멘트 한 건의 본문을 수정하고 edited=True 로 표시 (4번).

    시스템 코멘트(상태 변경 등 이력)는 수정할 수 없다(ValueError).
    빈 본문도 거부한다. 코멘트 개수는 그대로라 인덱스 갱신은 생략한다.
    """
    cleaned = (new_body or "").strip()
    if not cleaned:
        raise ValueError("코멘트 내용은 비울 수 없습니다.")
    with file_lock(_meta_lock_path(item_id)):
        comments = list_comments(item_id)
        target = next((c for c in comments if c.id == comment_id), None)
        if target is None:
            raise ValueError("코멘트를 찾을 수 없습니다.")
        if target.kind == "system":
            raise ValueError("시스템 코멘트(이력)는 수정할 수 없습니다.")
        target.body = cleaned
        target.edited = True
        _rewrite_comments_unlocked(item_id, comments)

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"edit_comment": comment_id},
    )


# ---------------------------------------------------------------------------
# 상태 / 메타 갱신
# ---------------------------------------------------------------------------


def update_status(
    item_id: str,
    new_status: Status | str,
    actor: str,
    actor_role: Role | str,
) -> Issue:
    """워크플로우 검증 → meta 갱신 → status_history 추가 → 시스템 코멘트
    → audit → 인덱스 갱신.

    new_status 가 ``closed`` 이면 reviewer_confirmed=True, reviewer_confirmed_at=now.

    담당자(assignee)는 자동 전환하지 않는다 — 개발자가 상세보기에서 수동 관리.
    """
    new_status_e = Status(new_status) if not isinstance(new_status, Status) else new_status
    actor_role_e = Role(actor_role) if not isinstance(actor_role, Role) else actor_role

    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old_status = issue.status

        assert_transition(old_status, actor_role_e, new_status_e)

        timestamp = now()
        issue.status = new_status_e
        issue.updated_at = timestamp
        issue.status_history.append(
            StatusEvent(status=new_status_e, at=timestamp, by=actor)
        )

        if new_status_e == Status.closed:
            issue.reviewer_confirmed = True
            issue.reviewer_confirmed_at = timestamp

        _write_meta_unlocked(issue)

    # 시스템 코멘트 (한국어 라벨)
    old_label = STATUS_LABELS_KO.get(old_status, old_status.value)
    new_label = STATUS_LABELS_KO.get(new_status_e, new_status_e.value)
    _add_system_comment(item_id, f"상태 변경: {old_label} → {new_label}")

    # audit
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_STATUS,
        item_id=item_id,
        detail={
            "from": old_status.value,
            "to": new_status_e.value,
            "role": actor_role_e.value,
        },
    )
    if new_status_e == Status.closed:
        audit.audit_log(
            actor=actor,
            action=audit.CONFIRM_REVIEW,
            item_id=item_id,
            detail=None,
        )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def update_assignee(
    item_id: str,
    new_assignee: str | None,
    actor: str,
) -> Issue:
    """담당자 재배정. None 으로 설정하면 미배정 상태."""
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old = issue.assignee
        issue.assignee = new_assignee
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    _add_system_comment(
        item_id,
        f"담당자 변경: {old or '(없음)'} → {new_assignee or '(없음)'}",
    )

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_ASSIGNEE,
        item_id=item_id,
        detail={"from": old, "to": new_assignee},
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def update_issue_content(
    item_id: str,
    title: str,
    description: str,
    actor: str,
) -> Issue:
    """제목/설명 수정. 제목은 필수(1~120자)."""
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise ValueError("제목은 비울 수 없습니다.")
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        issue.title = cleaned_title[:120]
        issue.description = description or ""
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    _add_system_comment(item_id, "제목/설명이 수정되었습니다.")
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"title": cleaned_title},
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def promote_unimplemented(
    item_id: str,
    *,
    title: str,
    description: str,
    urgency: Urgency | str,
    assignee: str,
    actor: str,
    category_l1: str | None = None,
    category_l2: str | None = None,
    category_l3: str | None = None,
) -> Issue:
    """미구현 항목(kind=unimplemented)을 개발 요청(dev)으로 승격.

    kind 를 dev 로 바꾸고 담당자/긴급도/카테고리를 설정, 상태를 담당자확인요청으로
    초기화한다. 이미지(캡쳐)는 같은 항목이라 그대로 따라간다.
    """
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise ValueError("제목은 비울 수 없습니다.")
    assignee = (assignee or "").strip()
    if not assignee:
        raise ValueError("담당자는 필수입니다.")
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.kind != "unimplemented":
            raise ValueError("미구현 항목만 개발 요청으로 승격할 수 있습니다.")
        timestamp = now()
        issue.kind = "dev"
        issue.title = cleaned_title[:120]
        issue.description = description or ""
        issue.urgency = (
            Urgency(urgency) if not isinstance(urgency, Urgency) else urgency
        )
        issue.assignee = assignee
        issue.status = Status.assignee_request
        # 카테고리는 명시적으로 값이 주어졌을 때만 덮어쓴다 — None 이면 기존값 보존.
        # (승격 폼에서 카테고리를 안 건드렸을 때 기존 카테고리가 지워지지 않게, 문제점 #4)
        if category_l1 is not None:
            issue.category_l1 = category_l1.strip() or None
        if category_l2 is not None:
            issue.category_l2 = category_l2.strip() or None
        if category_l3 is not None:
            issue.category_l3 = category_l3.strip() or None
        issue.updated_at = timestamp
        # 상태 이력 초기화 — 담당자확인요청부터 새로 시작.
        issue.status_history = [
            StatusEvent(status=Status.assignee_request, at=timestamp, by=actor)
        ]
        _write_meta_unlocked(issue)

    # 카테고리 풀 자동 누적 (create_issue 와 동일 — 승격 중 직접 입력한 카테고리도
    # 다음 등록 시 selectbox 옵션에 나오도록, 문제점 #14).
    if issue.project and (issue.category_l1 or issue.category_l2 or issue.category_l3):
        try:
            from . import project_settings as _ps
            if issue.category_l1:
                _ps.add_project_category(issue.project, l1=issue.category_l1)
            if issue.category_l2:
                _ps.add_project_category(issue.project, l2=issue.category_l2)
            if issue.category_l3:
                _ps.add_project_category(issue.project, l3=issue.category_l3)
        except Exception:  # noqa: BLE001
            pass

    _add_system_comment(
        item_id,
        f"미구현목록에서 개발 요청으로 승격되었습니다 (담당자: {assignee}).",
    )
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"promote": "unimplemented->dev", "assignee": assignee},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def promote_to_criteria(item_id: str, actor: str) -> Issue:
    """어떤 항목이든 Temp(kind=criteria, status=temp)로 이동 (확정 보류).

    상태를 Temp 로 바꾸고 담당자를 비운다 (확인대기·Temp 는 담당자 없음).
    원래 목록(확인요청목록/개발목록)에서 빠지고 Temp 목록에 나타난다.
    이미 Temp(criteria)인 항목은 ValueError.
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.kind == "criteria":
            raise ValueError("이미 Temp 항목입니다.")
        _old_kind = issue.kind
        issue.kind = "criteria"
        issue.status = Status.temp
        issue.assignee = None
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    _add_system_comment(item_id, "Temp 로 이동되었습니다 (상태: Temp · 담당자 해제).")
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"move": f"{_old_kind}->temp"},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def revert_criteria_to_request(item_id: str, actor: str) -> Issue:
    """Temp(kind=criteria) → 확인요청목록(unimplemented) 되돌리기.

    kind 를 unimplemented 로, 상태를 확인대기(pending_check)로 되돌리고
    담당자를 비운다 (5번). promote_to_criteria 의 역방향.
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.kind != "criteria":
            raise ValueError("Temp 항목만 확인요청목록으로 되돌릴 수 있습니다.")
        issue.kind = "unimplemented"
        issue.status = Status.pending_check
        issue.assignee = None
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    _add_system_comment(item_id, "확인요청목록으로 되돌렸습니다 (상태: 확인대기).")
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"move": "criteria->unimplemented"},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def set_rule_status(
    item_id: str, rule_status: str, actor: str, *, silent: bool = False
) -> Issue:
    """항목의 성격(정리) 라벨을 변경한다 (docs/09).

    rule_status: "unsorted" | "needs_check" | "confirmed".
    변경 시 시스템 코멘트 + audit 기록. 값이 같으면 아무 것도 하지 않는다.
    ``silent=True`` 면 시스템 코멘트를 남기지 않는다 (AI 일괄 적용 등 대량 처리용).
    """
    if rule_status not in RULE_STATUS_VALUES:
        raise ValueError(
            f"알 수 없는 성격 라벨: {rule_status!r} "
            f"(가능: {', '.join(RULE_STATUS_VALUES)})"
        )

    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old = issue.rule_status
        if old == rule_status:
            return issue  # 변경 없음
        issue.rule_status = rule_status  # type: ignore[assignment]
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    if not silent:
        _old_ko = RULE_STATUS_LABELS_KO.get(old, old)
        _new_ko = RULE_STATUS_LABELS_KO.get(rule_status, rule_status)
        _add_system_comment(item_id, f"성격 라벨 변경: {_old_ko} → {_new_ko}")
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"rule_status": f"{old}->{rule_status}"},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def send_pending_to_dev(
    item_id: str, actor: str, assignee: str | None = None
) -> Issue:
    """확인요청(확인대기) 항목을 담당자확인요청(개발목록)으로 보낸다 (1·3번).

    kind 를 unimplemented→dev, 상태를 확인대기(pending_check)→담당자확인요청
    (assignee_request)으로 바꾼다. 확인요청목록에서 빠지고 개발목록에 나타난다.
    ``assignee`` 를 주면 담당자로 지정한다 — 상세보기에서 확인대기→담당자확인요청
    으로 보낼 때는 담당자 지정이 필수다 (5번). 옛 데이터 일괄 정규화 등에서는
    생략(None) 가능.
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.kind != "unimplemented":
            raise ValueError("확인요청 항목만 담당자확인요청으로 보낼 수 있습니다.")
        timestamp = now()
        issue.kind = "dev"
        issue.status = Status.assignee_request
        if assignee and assignee.strip():
            issue.assignee = assignee.strip()
        issue.updated_at = timestamp
        issue.status_history.append(
            StatusEvent(status=Status.assignee_request, at=timestamp, by=actor)
        )
        _write_meta_unlocked(issue)

    _moved_msg = "담당자확인요청으로 보냈습니다 (확인요청목록 → 개발목록)."
    if assignee and assignee.strip():
        _moved_msg = (
            f"담당자확인요청으로 보냈습니다 (담당자: {assignee.strip()} · "
            f"확인요청목록 → 개발목록)."
        )
    _add_system_comment(item_id, _moved_msg)
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_STATUS,
        item_id=item_id,
        detail={"move": "unimplemented->dev", "to": Status.assignee_request.value},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def send_dev_to_pending(item_id: str, actor: str) -> Issue:
    """담당자확인요청(개발목록) 항목을 확인대기(확인요청목록)로 되돌린다 (3번).

    kind 를 dev→unimplemented, 상태를 담당자확인요청→확인대기(pending_check)로
    바꾸고 담당자를 비운다(확인대기는 담당자 없음). 개발목록에서 빠지고
    확인요청목록에 나타난다. send_pending_to_dev 의 역방향.
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.status != Status.assignee_request:
            raise ValueError(
                "담당자확인요청 상태에서만 확인대기로 되돌릴 수 있습니다."
            )
        timestamp = now()
        issue.kind = "unimplemented"
        issue.status = Status.pending_check
        issue.assignee = None
        issue.updated_at = timestamp
        issue.status_history.append(
            StatusEvent(status=Status.pending_check, at=timestamp, by=actor)
        )
        _write_meta_unlocked(issue)

    _add_system_comment(
        item_id,
        "확인대기로 되돌렸습니다 (개발목록 → 확인요청목록 · 담당자 해제).",
    )
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_STATUS,
        item_id=item_id,
        detail={"move": "dev->unimplemented", "to": Status.pending_check.value},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def clear_assignee(item_id: str, actor: str) -> Issue:
    """담당자 해제 — 확인대기·Temp 항목은 담당자가 없어야 한다 (5번)."""
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if issue.assignee is None:
            return issue
        issue.assignee = None
        issue.updated_at = now()
        _write_meta_unlocked(issue)
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_ASSIGNEE,
        item_id=item_id,
        detail={"clear": True},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def update_urgency(
    item_id: str,
    new_urgency: Urgency | str,
    actor: str,
) -> Issue:
    """긴급도 변경. 4 단계 (critical / high / normal / low) 중 하나."""
    new_urg = (
        Urgency(new_urgency) if not isinstance(new_urgency, Urgency) else new_urgency
    )
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old = issue.urgency
        if old == new_urg:
            return issue  # 변경 없음
        issue.urgency = new_urg
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    # 시스템 코멘트 + audit 로 추적성 보장
    from .workflow import URGENCY_LABELS_KO  # 지연 import (순환 회피)
    _add_system_comment(
        item_id,
        f"긴급도 변경: {URGENCY_LABELS_KO.get(old.value, old.value)} → "
        f"{URGENCY_LABELS_KO.get(new_urg.value, new_urg.value)}",
    )
    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_URGENCY,
        item_id=item_id,
        detail={"from": old.value, "to": new_urg.value},
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def update_tags(
    item_id: str,
    tags: list[str],
    actor: str,
) -> Issue:
    """태그 전체 교체."""
    cleaned = [str(t).strip() for t in tags if str(t).strip()]
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old = list(issue.tags)
        issue.tags = cleaned
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_TAGS,
        item_id=item_id,
        detail={"from": old, "to": cleaned},
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def update_categories(
    item_id: str,
    *,
    category_l1: str | None,
    category_l2: str | None,
    category_l3: str | None,
    actor: str,
) -> Issue:
    """카테고리 3 단계 일괄 변경. 빈 문자열은 None 으로 정규화.

    하위 단계만 비우는 것은 허용 (예: l1 만 지정, l2/l3 None).
    audit 로그 + 인덱스 갱신 + 시스템 코멘트.
    """
    def _norm(v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    new_l1 = _norm(category_l1)
    new_l2 = _norm(category_l2)
    new_l3 = _norm(category_l3)

    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old_path = (issue.category_l1, issue.category_l2, issue.category_l3)
        new_path = (new_l1, new_l2, new_l3)
        if old_path == new_path:
            return issue
        issue.category_l1 = new_l1
        issue.category_l2 = new_l2
        issue.category_l3 = new_l3
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    def _fmt(p: tuple[str | None, str | None, str | None]) -> str:
        parts = [x for x in p if x]
        return " > ".join(parts) if parts else "(없음)"

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CATEGORIES,
        item_id=item_id,
        detail={"from": list(old_path), "to": list(new_path)},
    )
    _add_system_comment(item_id, f"카테고리 변경: {_fmt(old_path)} → {_fmt(new_path)}")

    # 카테고리 풀 자동 누적 — 사용자가 변경 popover 에서 *새* 카테고리를
    # 입력한 경우 사이드바 옵션 풀에도 추가됨. 같은 흐름.
    if issue.project and (new_l1 or new_l2 or new_l3):
        try:
            from . import project_settings as _ps
            if new_l1:
                _ps.add_project_category(issue.project, l1=new_l1)
            if new_l2:
                _ps.add_project_category(issue.project, l2=new_l2)
            if new_l3:
                _ps.add_project_category(issue.project, l3=new_l3)
        except Exception:
            pass

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def update_project(
    item_id: str,
    new_project: str | None,
    actor: str,
) -> Issue:
    """프로젝트 식별자 변경. 빈 문자열은 None 으로 정규화.

    update_assignee / update_categories 와 동일 패턴 — meta 락 → audit →
    시스템 코멘트 → 인덱스 갱신. 변경 없으면 (old == new) early return.
    """
    if isinstance(new_project, str):
        cleaned = new_project.strip()
        normalized: str | None = cleaned or None
    else:
        normalized = new_project

    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        old = issue.project
        if old == normalized:
            return issue
        issue.project = normalized
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_PROJECT,
        item_id=item_id,
        detail={"from": old, "to": normalized},
    )
    _add_system_comment(
        item_id,
        f"프로젝트 변경: {old or '없음'} → {normalized or '없음'}",
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def list_projects(participant: str | None = None) -> list[str]:
    """프로젝트 식별자 unique 리스트 (정렬). **글로벌 풀** — 모든 사용자에게 모든 프로젝트 노출.

    Parameters
    ----------
    participant : str | None
        하위 호환을 위해 시그니처 유지하지만 무시됨. 사용자 격리는 다른
        함수 (``last_project_for_user``) 의 역할.

    Notes
    -----
    소스: 인덱스의 **삭제되지 않은 항목** (deleted=False) 의 unique project ∪
    user_projects.json 에 등록된 *모든 사용자* 의 프로젝트 union.

    삭제 태그가 붙은 항목의 프로젝트는 의도적으로 제외 — 항목을 모두 삭제한
    프로젝트는 옵션에서 사라져야 자연스럽다 (그래야 마지막 항목 삭제 후
    사이드바에서 완전히 제거됨). 완료 항목은 포함된다.
    """
    seen: set[str] = set()
    for entry in index_mod.read_index():
        if entry.get("deleted"):
            continue  # 삭제된 항목은 프로젝트 풀에 영향 X
        raw = entry.get("project")
        if not raw:
            continue
        s = str(raw).strip()
        if s:
            seen.add(s)
    # 사용자가 명시적으로 추가한 프로젝트도 union (항목 0 건이라도 노출).
    # remove_project_globally 가 user_projects.json 에서 제거하면 여기서도 빠짐.
    from . import user_projects as up_mod
    seen.update(up_mod.list_all_projects())
    return sorted(seen)


def last_project_for_user(user: str) -> str | None:
    """``user`` 가 가장 최근에 *등록* (author) 한 항목의 project 를 반환.

    사이드바 첫 진입 시 사용자별 기본 프로젝트로 사용. 없으면 None.
    인덱스 1 회 스캔 — created_at 가 가장 최근인 항목 기준.
    """
    if not user:
        return None
    latest_at = ""
    latest_project: str | None = None
    for entry in index_mod.read_index():
        if (entry.get("author") or "").strip() != user:
            continue
        proj = (entry.get("project") or "").strip()
        if not proj:
            continue
        created = entry.get("created_at") or ""
        if isinstance(created, str) and created > latest_at:
            latest_at = created
            latest_project = proj
    return latest_project


def count_project_items(project: str, *, include_deleted: bool = False) -> int:
    """프로젝트의 항목 수. 글로벌 삭제 가드용.

    Parameters
    ----------
    project : str
        대상 프로젝트 이름.
    include_deleted : bool, default False
        ``False`` (기본): 삭제 태그가 붙지 않은 항목만 카운트. 항목을 모두
        삭제했으면 프로젝트 자체도 삭제 가능해야 한다.
        ``True``: 삭제된 항목까지 모두 카운트 (감사/통계 용도).
    """
    if not project:
        return 0
    project = project.strip()
    if not project:
        return 0
    n = 0
    for entry in index_mod.read_index():
        if (entry.get("project") or "").strip() != project:
            continue
        if not include_deleted and entry.get("deleted"):
            continue
        n += 1
    return n


def list_categories(project: str | None = None) -> dict[str, dict[str, set[str]]]:
    """현재까지 사용된 카테고리 트리.

    구조: ``{l1: {l2: {l3, l3, ...}, ...}, ...}``. 빈 단계(None) 는 트리에서
    제외 — 사용자가 새 등록 시 드롭다운에서 재사용할 수 있도록 하위 레벨
    unique 추출 용도. index.json 1 회 읽기로 끝남 (목록 캐시 활용).

    Parameters
    ----------
    project : str | None
        지정 시 *그 프로젝트* 의 항목만 추출. None 이면 전체.

    Notes
    -----
    삭제 태그(deleted=True) 항목은 제외 — 항목을 모두 삭제한 카테고리는
    옵션에서 자동으로 사라진다 (= 명시적 카테고리 삭제 기능 불필요).
    완료 항목의 카테고리는 계속 노출된다.
    """
    tree: dict[str, dict[str, set[str]]] = {}
    for entry in index_mod.read_index():
        if entry.get("deleted"):
            continue  # 삭제된 항목 제외
        if project is not None:
            if (entry.get("project") or "").strip() != project:
                continue
        l1 = (entry.get("category_l1") or "").strip()
        l2 = (entry.get("category_l2") or "").strip()
        l3 = (entry.get("category_l3") or "").strip()
        if not l1:
            continue
        l2_map = tree.setdefault(l1, {})
        if l2:
            l3_set = l2_map.setdefault(l2, set())
            if l3:
                l3_set.add(l3)
    return tree


def flat_categories(
    tree: dict[str, dict[str, set[str]]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """카테고리 트리를 레벨별 평면(unique) 리스트로 펼쳐 반환.

    사용자가 "대분류가 달라도 중분류 이름이 같으면 다 보고 싶다"고 한 요구사항
    대응. 입력/수정 폼의 selectbox 옵션 구성 시 트리 종속을 해제한다.

    반환값: ``(l1_list, l2_list, l3_list)`` — 각각 알파벳 정렬된 unique 값.
    트리를 인자로 받지 않으면 :func:`list_categories` 결과를 사용한다.
    """
    if tree is None:
        tree = list_categories()
    all_l1 = sorted(tree.keys())
    all_l2 = sorted(
        {l2 for l2_map in tree.values() for l2 in l2_map.keys()}
    )
    all_l3 = sorted(
        {
            l3
            for l2_map in tree.values()
            for l3_set in l2_map.values()
            for l3 in l3_set
        }
    )
    return all_l1, all_l2, all_l3


# ---------------------------------------------------------------------------
# 이미지
# ---------------------------------------------------------------------------


def _check_image_quota(item_id: str) -> None:
    if images_mod.count_images(item_id) >= MAX_IMAGES_PER_ITEM:
        raise ValueError(
            f"이미지 개수 한도 초과: 항목당 최대 {MAX_IMAGES_PER_ITEM}장"
        )


def _next_image_seq(item_id: str) -> int:
    """다음 이미지 시퀀스 번호 = 기존 파일들의 최대 seq + 1.

    개수(count) 기반이 아니라 실제 파일명의 접두 번호(``NNN_...``) 최대값 기반이라,
    중간 이미지를 삭제한 뒤 추가해도 번호가 재사용되지 않는다(파일명 충돌 방지).
    """
    d = paths.item_images_dir(item_id)
    max_seq = 0
    if d.exists():
        for p in d.iterdir():
            # 파일명은 '{seq}_{slug}...' — 첫 '_' 앞 전체가 번호이므로 4자리(≥1000)
            # 이상도 정확히 파싱한다 (앞 3글자만 보던 버그 수정, 문제점 #10).
            head = p.name.split("_", 1)[0]
            if head.isdigit():
                max_seq = max(max_seq, int(head))
    return max_seq + 1


def delete_image(item_id: str, image_index: int, actor: str) -> Issue:
    """이미지 한 장 삭제 — issue.images 에서 제거하고 파일(원본+썸네일)도 지운다.

    잘못 첨부한 이미지를 제거하는 용도. image_index 는 issue.images 의 인덱스.
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if not (0 <= image_index < len(issue.images)):
            raise ValueError("이미지를 찾을 수 없습니다.")
        img = issue.images.pop(image_index)
        item_dir = paths.item_dir(item_id)
        # 옛 seq 충돌로 같은 파일을 참조하는 항목이 남아 있을 수 있으니, 다른 항목이
        # 아직 쓰는 파일은 지우지 않는다 (남은 항목이 깨지지 않도록).
        _still_used = {i.file for i in issue.images}
        _still_used |= {i.thumb for i in issue.images if i.thumb}
        for _rel in (img.file, img.thumb):
            if _rel and _rel not in _still_used:
                try:
                    (item_dir / _rel).unlink(missing_ok=True)
                except OSError:
                    pass
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"delete_image": image_index},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def set_image_caption(
    item_id: str, image_index: int, caption: str, actor: str
) -> Issue:
    """이미지 한 장의 설명(캡션)을 설정/수정한다. image_index 는 issue.images 인덱스."""
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        if not (0 <= image_index < len(issue.images)):
            raise ValueError("이미지를 찾을 수 없습니다.")
        issue.images[image_index].caption = (caption or "").strip()
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPDATE_CONTENT,
        item_id=item_id,
        detail={"caption_image": image_index},
    )
    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(_read_meta(item_id), comments_count, images_count)
    return _read_meta(item_id)


def add_image_from_bytes(
    item_id: str,
    data: bytes,
    original_filename: str,
    actor: str,
    kind: str | None = None,
    caption: str = "",
) -> ImageRef:
    """원본 바이트를 받아 이미지 추가. 한도 초과 시 ValueError.

    kind: "request"(요청/AS-IS) / "dev"(개발/TO-BE) / None(구분 없음).
    caption: 사진별 설명(선택).
    """
    dest = paths.item_images_dir(item_id)
    # 한도확인·seq계산·파일저장·meta반영을 모두 락 안에서 — 동시 업로드가 같은
    # seq/파일명으로 충돌해 중복 ImageRef/카운트 불일치가 생기지 않게 (문제점 #11).
    with file_lock(_meta_lock_path(item_id)):
        _check_image_quota(item_id)
        seq = _next_image_seq(item_id)
        ref = save_image_bytes(data, original_filename, dest, seq, kind=kind)
        ref.caption = (caption or "").strip()
        issue = _read_meta(item_id)
        issue.images.append(ref)
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPLOAD_IMAGE,
        item_id=item_id,
        detail={"file": ref.file, "size_bytes": ref.size_bytes, "sha256": ref.sha256},
    )
    _kl = {"request": "요청", "dev": "개발"}.get(kind or "", "")
    _add_system_comment(
        item_id, f"이미지 첨부{f'({_kl})' if _kl else ''}: {ref.file}"
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return ref


def add_image_from_pil(
    item_id: str,
    img: PILImage.Image,
    original_filename: str,
    actor: str,
    kind: str | None = None,
    caption: str = "",
) -> ImageRef:
    """PIL.Image 를 받아 이미지 추가 (paste-button 등에서 사용).

    kind: "request"(요청/AS-IS) / "dev"(개발/TO-BE) / None(구분 없음).
    caption: 사진별 설명(선택).
    """
    dest = paths.item_images_dir(item_id)
    # 락 안에서 한도확인·seq계산·저장·meta반영 (동시 업로드 충돌 방지, 문제점 #11).
    with file_lock(_meta_lock_path(item_id)):
        _check_image_quota(item_id)
        seq = _next_image_seq(item_id)
        ref = save_pil_image(img, original_filename, dest, seq, kind=kind)
        ref.caption = (caption or "").strip()
        issue = _read_meta(item_id)
        issue.images.append(ref)
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(
        actor=actor,
        action=audit.UPLOAD_IMAGE,
        item_id=item_id,
        detail={"file": ref.file, "size_bytes": ref.size_bytes, "sha256": ref.sha256},
    )
    _kl = {"request": "요청", "dev": "개발"}.get(kind or "", "")
    _add_system_comment(
        item_id, f"이미지 첨부{f'({_kl})' if _kl else ''}: {ref.file}"
    )

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return ref


# ---------------------------------------------------------------------------
# 삭제 (소프트 삭제 = 삭제 태그) / 복구
# ---------------------------------------------------------------------------


def delete_issue(item_id: str, actor: str) -> Issue:
    """삭제 태그를 붙인다. ``deleted = True`` + ``deleted_at`` 기록 후 인덱스 갱신.

    상태(status)는 건드리지 않는다 — 완료 항목을 삭제하면 '완료이면서 삭제됨'
    이 되고, 대시보드에서는 삭제 목록에만 보인다. :func:`restore_issue` 로
    되돌릴 수 있다 (복구 가능한 소프트 삭제).
    """
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        issue.deleted = True
        issue.deleted_at = now()
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(actor=actor, action=audit.ARCHIVE, item_id=item_id, detail=None)

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def restore_issue(item_id: str, actor: str) -> Issue:
    """삭제 태그를 뗀다 (복구). 레거시 ``archived`` 플래그도 함께 내린다."""
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        issue.deleted = False
        issue.deleted_at = None
        issue.archived = False
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(actor=actor, action=audit.RESTORE, item_id=item_id, detail=None)

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


# 옛 이름 — 호출부가 남아 있어도 깨지지 않도록 유지 (동작은 delete_issue 와 동일).
archive_issue = delete_issue


def delete_issue_permanently(item_id: str, actor: str) -> None:
    """항목 폴더(메타·이미지·코멘트 전체)를 디스크에서 완전 삭제. 복구 불가.

    인덱스 엔트리도 제거한다. ``paths.item_dir`` 의 형식 검증으로 path
    traversal 을 차단한다 (잘못된 id 면 InvalidItemIdError).
    """
    import shutil

    # 형식 검증 (path traversal 차단) — item_dir 가 검증을 수행.
    target = paths.item_dir(item_id)

    # audit 먼저 — 폴더 삭제로 item.log 는 사라지지만 통합 audit.log 에는 남는다.
    audit.audit_log(actor=actor, action=audit.DELETE, item_id=item_id, detail=None)

    # 인덱스에서 제거
    index_mod.remove_index_entry(item_id)

    # 폴더 자체 삭제
    if target.exists():
        shutil.rmtree(target)


def restore_legacy_archived() -> dict[str, int]:
    """레거시 ``archived`` 플래그를 전부 해제해 원래 단계로 되돌린다 (재실행 안전).

    배경 — 2026-08-11 이전에는 ``archived`` 하나가 두 가지를 겸했다:
      (1) 사용자가 [삭제] 를 누른 항목
      (2) 완료 후 14 일이 지나 ``auto_archive_closed`` 가 자동 보관한 항목
    대시보드 '삭제' 가 archived 전체를 보여줬기 때문에, (2) 가 삭제 목록으로
    밀려나 '완료 1건 / 삭제 다수' 로 보이던 것이 원인이다.

    **상태로는 (1)/(2) 를 구분할 수 없다.** 완료된 항목을 다시 열면
    (``완료 → 등록자검토중 → 반려``) archived 는 True 로 남은 채 상태만 바뀌므로,
    '담당자검토중인데 자동 보관된' 항목이 실제로 존재한다. 그래서 추측으로
    삭제 태그를 붙이지 않고 **전부 원래 상태 그대로 되살린다** — 진짜 지울 것은
    사용자가 [삭제] 로 다시 표시한다 (그때부터 ``deleted`` 로 명확히 남는다).

    각 항목은 자기 ``status``/``kind`` 에 해당하는 섹션으로 자동 복귀한다
    (완료 → 완료, 담당자검토중 → 담당자 처리, 확인대기 → 확인요청목록 …).

    ``updated_at`` 은 건드리지 않는다 — 목록 정렬(최신순)이 통째로 뒤집히는 것을
    막기 위해. 처리 후 archived 는 항상 False 가 되므로 다음 실행에는 대상이 없다.

    Returns
    -------
    dict[str, int]
        되살린 항목의 상태값별 건수. 예: ``{"closed": 12, "assignee_reviewing": 3}``.
        대상이 없으면 빈 dict.
    """
    restored: dict[str, int] = {}

    for entry in index_mod.read_index():
        if not entry.get("archived"):
            continue
        item_id = entry.get("id")
        if not item_id:
            continue

        try:
            issue = _read_meta(item_id)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            continue
        if not issue.archived:
            continue  # 인덱스만 낡은 경우 — meta 기준으로 스킵

        with file_lock(_meta_lock_path(item_id)):
            issue = _read_meta(item_id)
            issue.archived = False
            # updated_at 은 의도적으로 유지 (정렬 보존). deleted 도 건드리지 않는다.
            _write_meta_unlocked(issue)

        status_value = issue.status.value
        audit.audit_log(
            actor="system",
            action=audit.RESTORE_LEGACY,
            item_id=item_id,
            detail={"status": status_value},
        )

        comments_count, images_count = index_mod.get_counts(item_id)
        index_mod.update_index_entry(issue, comments_count, images_count)
        restored[status_value] = restored.get(status_value, 0) + 1

    return restored


__all__ = [
    "create_issue",
    "get_issue",
    "list_issues",
    "list_comments",
    "add_comment",
    "update_status",
    "update_assignee",
    "update_tags",
    "update_categories",
    "list_categories",
    "flat_categories",
    "update_project",
    "list_projects",
    "add_image_from_bytes",
    "add_image_from_pil",
    "delete_issue",
    "restore_issue",
    "archive_issue",
    "delete_issue_permanently",
    "restore_legacy_archived",
]
