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
from datetime import timedelta
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from . import images as images_mod
from . import index as index_mod
from . import logger as audit
from . import paths
from .clock import from_iso, now, to_iso
from .images import MAX_IMAGES_PER_ITEM, save_image_bytes, save_pil_image
from .locking import _write_json_unlocked, atomic_append_jsonl, file_lock
from .models import (
    Comment,
    ImageRef,
    IndexEntry,
    Issue,
    Role,
    Status,
    StatusEvent,
    Urgency,
)
from .workflow import STATUS_LABELS_KO, assert_transition


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
) -> Issue:
    """새 항목 생성.

    폴더/meta.json/빈 comments.jsonl 생성 → audit 로그 → 인덱스 갱신.
    pydantic 검증으로 잘못된 입력은 ValidationError 로 거부.
    카테고리 3 단계는 모두 optional — 빈 문자열은 None 으로 정규화.
    project 도 optional — 빈 문자열은 None 으로 정규화.
    """
    item_id = _new_item_id()
    item_root = paths.item_dir(item_id)
    item_root.mkdir(parents=True, exist_ok=True)
    paths.item_images_dir(item_id).mkdir(parents=True, exist_ok=True)

    timestamp = now()
    issue = Issue(
        id=item_id,
        title=title,
        description=description,
        urgency=Urgency(urgency) if not isinstance(urgency, Urgency) else urgency,
        status=Status.requested,
        author=author,
        author_role=Role(author_role) if not isinstance(author_role, Role) else author_role,
        assignee=assignee,
        created_at=timestamp,
        updated_at=timestamp,
        status_history=[
            StatusEvent(status=Status.requested, at=timestamp, by=author),
        ],
        images=[],
        reviewer_confirmed=False,
        reviewer_confirmed_at=None,
        tags=list(tags or []),
        archived=False,
        category_l1=(category_l1.strip() or None) if category_l1 else None,
        category_l2=(category_l2.strip() or None) if category_l2 else None,
        category_l3=(category_l3.strip() or None) if category_l3 else None,
        project=(project.strip() or None) if project else None,
    )

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
    include_archived: bool,
    include_closed: bool,
    project: str | None,
) -> bool:
    """단일 인덱스 엔트리가 필터 조건에 부합하는지."""
    if not include_archived and entry.get("archived"):
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
    include_archived: bool = False,
    include_closed: bool = True,
    project: str | None = None,
) -> list[IndexEntry]:
    """인덱스 기반 필터링된 목록을 ``updated_at desc`` 로 정렬해 반환.

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
            include_archived=include_archived,
            include_closed=include_closed,
            project=project,
        )
    ]

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
        하위 호환을 위해 시그니처 유지하지만 무시됨. 모든 호출에서 동일한
        결과 반환. 사용자 격리는 다른 함수 (``last_project_for_user``) 의
        역할.

    Notes
    -----
    소스: 인덱스의 모든 unique project ∪ user_projects.json 에 등록된
    *모든 사용자* 의 프로젝트 union. 후자 덕분에 항목이 0 건인 프로젝트도
    옵션에 노출됨.
    """
    seen: set[str] = set()
    for entry in index_mod.read_index():
        raw = entry.get("project")
        if not raw:
            continue
        s = str(raw).strip()
        if s:
            seen.add(s)
    # 모든 사용자가 추가한 프로젝트도 union (항목 0 건도 노출)
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


def count_project_items(project: str) -> int:
    """프로젝트의 전체 항목 수 (활성/보관 모두). 글로벌 삭제 가드용."""
    if not project:
        return 0
    project = project.strip()
    if not project:
        return 0
    n = 0
    for entry in index_mod.read_index():
        if (entry.get("project") or "").strip() == project:
            n += 1
    return n


def list_categories() -> dict[str, dict[str, set[str]]]:
    """현재까지 사용된 카테고리를 트리 구조로 반환.

    구조: ``{l1: {l2: {l3, l3, ...}, ...}, ...}``.
    빈 단계(None) 는 트리에서 제외 — 사용자가 새 등록 시 드롭다운에서
    재사용할 수 있도록 하위 레벨 unique 추출 용도.

    index.json 1 회 읽기로 끝남 (목록 캐시 활용).
    """
    tree: dict[str, dict[str, set[str]]] = {}
    for entry in index_mod.read_index():
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
    return images_mod.count_images(item_id) + 1


def add_image_from_bytes(
    item_id: str,
    data: bytes,
    original_filename: str,
    actor: str,
) -> ImageRef:
    """원본 바이트를 받아 이미지 추가. 한도 초과 시 ValueError."""
    _check_image_quota(item_id)
    seq = _next_image_seq(item_id)
    dest = paths.item_images_dir(item_id)

    ref = save_image_bytes(data, original_filename, dest, seq)

    with file_lock(_meta_lock_path(item_id)):
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
    _add_system_comment(item_id, f"이미지 첨부: {ref.file}")

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return ref


def add_image_from_pil(
    item_id: str,
    img: PILImage.Image,
    original_filename: str,
    actor: str,
) -> ImageRef:
    """PIL.Image 를 받아 이미지 추가 (paste-button 등에서 사용)."""
    _check_image_quota(item_id)
    seq = _next_image_seq(item_id)
    dest = paths.item_images_dir(item_id)

    ref = save_pil_image(img, original_filename, dest, seq)

    with file_lock(_meta_lock_path(item_id)):
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
    _add_system_comment(item_id, f"이미지 첨부: {ref.file}")

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return ref


# ---------------------------------------------------------------------------
# 아카이브
# ---------------------------------------------------------------------------


def archive_issue(item_id: str, actor: str) -> Issue:
    """수동 아카이브. ``archived = True`` 로 설정하고 인덱스 갱신."""
    with file_lock(_meta_lock_path(item_id)):
        issue = _read_meta(item_id)
        issue.archived = True
        issue.updated_at = now()
        _write_meta_unlocked(issue)

    audit.audit_log(actor=actor, action=audit.ARCHIVE, item_id=item_id, detail=None)

    comments_count, images_count = index_mod.get_counts(item_id)
    index_mod.update_index_entry(issue, comments_count, images_count)
    return issue


def auto_archive_closed(days: int = 14) -> int:
    """``closed`` 상태이면서 reviewer_confirmed_at + days < now 인 항목들을
    archived=True 로 변경.

    docs/04_workflow.md 4.7 절. 앱 시작 시 1회 호출 권장. 반환값은 아카이빙된 개수.
    """
    cutoff = now() - timedelta(days=days)
    archived_count = 0

    for entry in index_mod.read_index():
        if entry.get("archived"):
            continue
        if entry.get("status") != Status.closed.value:
            continue
        item_id = entry.get("id")
        if not item_id:
            continue

        try:
            issue = _read_meta(item_id)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        confirmed_at = issue.reviewer_confirmed_at
        if confirmed_at is None:
            continue
        if confirmed_at >= cutoff:
            continue

        # 임계값 초과 → 아카이브
        with file_lock(_meta_lock_path(item_id)):
            issue = _read_meta(item_id)
            issue.archived = True
            issue.updated_at = now()
            _write_meta_unlocked(issue)

        audit.audit_log(
            actor="system",
            action=audit.AUTO_ARCHIVE,
            item_id=item_id,
            detail={"days": days, "closed_at": to_iso(confirmed_at)},
        )

        comments_count, images_count = index_mod.get_counts(item_id)
        index_mod.update_index_entry(issue, comments_count, images_count)
        archived_count += 1

    return archived_count


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
    "archive_issue",
    "auto_archive_closed",
]
