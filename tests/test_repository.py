"""repository 통합 시나리오 테스트.

create → list → status 전이 → comment → image → archive 의 전체 흐름을
실제 디스크에 쓰면서 검증한다. 환경변수 ``DATA_DIR`` 를 ``tmp_path`` 로 격리.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from core import index as index_mod
from core import paths, repository
from core.clock import from_iso, to_iso
from core.models import Issue, Role, Status, Urgency
from core.workflow import WorkflowError


# ---------------------------------------------------------------------------
# 생성
# ---------------------------------------------------------------------------


def test_create_issue_basic(temp_data_dir: Path, sample_issue_kwargs: dict) -> None:
    """create_issue → get_issue 가 동일 이슈를 반환. id/상태/타임스탬프 검증."""
    issue = repository.create_issue(**sample_issue_kwargs)

    # id 형식: YYYY-MM-DD_6hex
    assert re.match(r"^\d{4}-\d{2}-\d{2}_[0-9a-f]{6}$", issue.id), (
        f"id 형식 위반: {issue.id}"
    )

    # 상태/타임스탬프
    assert issue.status == Status.assignee_request
    assert issue.created_at == issue.updated_at, "생성 직후엔 동일해야 함"
    assert len(issue.status_history) == 1
    assert issue.status_history[0].status == Status.assignee_request
    assert issue.status_history[0].by == sample_issue_kwargs["author"]

    # 라운드트립
    fetched = repository.get_issue(issue.id)
    assert fetched.id == issue.id
    assert fetched.title == sample_issue_kwargs["title"]
    assert fetched.urgency == Urgency.normal
    assert fetched.status == Status.assignee_request

    # meta.json 디스크에 존재
    meta_path = paths.item_meta_path(issue.id)
    assert meta_path.exists()
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    assert raw["id"] == issue.id

    # 빈 comments.jsonl 생성
    assert paths.item_comments_path(issue.id).exists()
    # 이미지 디렉토리도 생성
    assert paths.item_images_dir(issue.id).exists()


def test_create_issue_validation_empty_title(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """빈 title 은 pydantic ValidationError."""
    sample_issue_kwargs["title"] = ""
    with pytest.raises(ValidationError):
        repository.create_issue(**sample_issue_kwargs)


def test_create_issue_validation_title_too_long(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """title > 120자는 ValidationError."""
    sample_issue_kwargs["title"] = "가" * 121
    with pytest.raises(ValidationError):
        repository.create_issue(**sample_issue_kwargs)


def test_create_issue_validation_invalid_urgency(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """알 수 없는 urgency 문자열 → ValueError 또는 ValidationError."""
    sample_issue_kwargs["urgency"] = "super_high"
    with pytest.raises((ValidationError, ValueError)):
        repository.create_issue(**sample_issue_kwargs)


# ---------------------------------------------------------------------------
# 목록
# ---------------------------------------------------------------------------


def _make_issue(
    sample_issue_kwargs: dict, **overrides
) -> Issue:
    """헬퍼: 기본 인자에 overrides 적용해 create_issue 호출."""
    kw = dict(sample_issue_kwargs)
    kw.update(overrides)
    return repository.create_issue(**kw)


def _drive_to_closed(item_id: str) -> None:
    """담당자확인요청 → ... → 완료 까지 전체 전이 (closed 항목 생성 헬퍼)."""
    for _st, _actor, _role in [
        (Status.assignee_reviewing, "dev", Role.developer),
        (Status.assignee_reviewed, "dev", Role.developer),
        (Status.assignee_developing, "dev", Role.developer),
        (Status.author_request, "dev", Role.developer),
        (Status.author_reviewing, "rev", Role.reviewer),
        (Status.closed, "rev", Role.reviewer),
    ]:
        repository.update_status(item_id, _st, actor=_actor, actor_role=_role)


def test_list_issues_filters(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """status/urgency/assignee/author/search 필터가 각각 정확히 동작."""
    a = _make_issue(
        sample_issue_kwargs,
        title="apple bug",
        urgency="high",
        assignee="alice",
        author="reviewer1",
        author_role="reviewer",
        tags=["frontend"],
    )
    b = _make_issue(
        sample_issue_kwargs,
        title="banana issue",
        urgency="low",
        assignee="bob",
        author="reviewer2",
        author_role="reviewer",
        tags=["backend"],
    )
    c = _make_issue(
        sample_issue_kwargs,
        title="apple feature",
        urgency="normal",
        assignee=None,
        author="reviewer1",
        author_role="reviewer",
        tags=["frontend", "ui"],
    )

    all_ids = {a.id, b.id, c.id}
    listed = {e.id for e in repository.list_issues()}
    assert listed == all_ids

    # urgency 필터
    high = repository.list_issues(urgency="high")
    assert {e.id for e in high} == {a.id}

    # assignee 필터
    bobs = repository.list_issues(assignee="bob")
    assert {e.id for e in bobs} == {b.id}

    # author 필터
    rev1 = repository.list_issues(author="reviewer1")
    assert {e.id for e in rev1} == {a.id, c.id}

    # 검색: title 부분 매칭
    apples = repository.list_issues(search="apple")
    assert {e.id for e in apples} == {a.id, c.id}

    # 검색: 태그 매칭
    backend = repository.list_issues(search="backend")
    assert {e.id for e in backend} == {b.id}

    # 대소문자 무시
    upper = repository.list_issues(search="APPLE")
    assert {e.id for e in upper} == {a.id, c.id}


def test_list_issues_include_deleted_default(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """include_deleted 기본 False → 삭제 표시된 항목 미포함."""
    a = _make_issue(sample_issue_kwargs, title="A")
    b = _make_issue(sample_issue_kwargs, title="B")

    repository.delete_issue(a.id, actor="tester")

    default = repository.list_issues()
    assert {e.id for e in default} == {b.id}, "삭제된 a 가 기본 목록에 포함됨"

    incl = repository.list_issues(include_deleted=True)
    assert {e.id for e in incl} == {a.id, b.id}


def test_list_issues_include_closed_default_true(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """include_closed 기본 True → closed 항목도 기본에 포함."""
    a = _make_issue(sample_issue_kwargs, title="A")
    b = _make_issue(sample_issue_kwargs, title="B")

    # a 를 closed 까지 진행
    _drive_to_closed(a.id)

    default = repository.list_issues()
    assert {e.id for e in default} == {a.id, b.id}, "closed 가 기본 목록에서 빠짐"

    no_closed = repository.list_issues(include_closed=False)
    assert {e.id for e in no_closed} == {b.id}


def test_list_issues_sort_by_updated_at_desc(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """updated_at 내림차순 정렬."""
    a = _make_issue(sample_issue_kwargs, title="A")
    time.sleep(1.1)  # ISO 초 단위 분리 보장
    b = _make_issue(sample_issue_kwargs, title="B")
    time.sleep(1.1)
    c = _make_issue(sample_issue_kwargs, title="C")

    listed = repository.list_issues()
    ids = [e.id for e in listed]
    assert ids == [c.id, b.id, a.id], (
        f"updated_at desc 정렬 위반: {ids}"
    )

    # a 를 다시 갱신 → 맨 위로 와야 한다
    time.sleep(1.1)
    repository.update_status(
        a.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    listed2 = repository.list_issues()
    assert listed2[0].id == a.id, "갱신된 항목이 맨 위로 오지 않음"


# ---------------------------------------------------------------------------
# 상태 전이
# ---------------------------------------------------------------------------


def test_update_status_full_workflow(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """전체 흐름: 담당자확인요청 → 검토중 → 검토완료 → 신규개발중
    → 등록자확인요청 → 등록자검토중 → 완료."""
    issue = _make_issue(sample_issue_kwargs)

    final = issue
    for _st, _actor, _role in [
        (Status.assignee_reviewing, "dev", Role.developer),
        (Status.assignee_reviewed, "dev", Role.developer),
        (Status.assignee_developing, "dev", Role.developer),
        (Status.author_request, "dev", Role.developer),
        (Status.author_reviewing, "rev", Role.reviewer),
        (Status.closed, "rev", Role.reviewer),
    ]:
        final = repository.update_status(
            issue.id, _st, actor=_actor, actor_role=_role
        )

    assert final.status == Status.closed
    assert final.reviewer_confirmed is True, "closed 진입 시 reviewer_confirmed True"
    assert final.reviewer_confirmed_at is not None, "reviewer_confirmed_at not None"


def test_update_status_unauthorized_role(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """등록자(reviewer)가 담당자 전이(검토중) 시도 → WorkflowError."""
    issue = _make_issue(sample_issue_kwargs)

    with pytest.raises(WorkflowError):
        repository.update_status(
            issue.id, Status.assignee_reviewing, actor="bad", actor_role=Role.reviewer
        )

    # 상태 변경 시도가 실패했으니 디스크 상태도 그대로
    after = repository.get_issue(issue.id)
    assert after.status == Status.assignee_request


def test_update_status_invalid_transition(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """담당자확인요청 → 등록자확인요청 직접 점프 (검토 단계 생략) → WorkflowError."""
    issue = _make_issue(sample_issue_kwargs)

    with pytest.raises(WorkflowError):
        repository.update_status(
            issue.id, Status.author_request, actor="dev", actor_role=Role.developer
        )


def test_status_history_appended_on_each_change(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """매 상태 변경마다 status_history 에 StatusEvent 추가."""
    issue = _make_issue(sample_issue_kwargs)
    assert len(issue.status_history) == 1

    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.assignee_reviewed, actor="dev", actor_role=Role.developer
    )

    final = repository.get_issue(issue.id)
    statuses = [ev.status for ev in final.status_history]
    bys = [ev.by for ev in final.status_history]

    assert statuses == [
        Status.assignee_request,
        Status.assignee_reviewing,
        Status.assignee_reviewed,
    ]
    assert bys == [sample_issue_kwargs["author"], "dev", "dev"]
    # 모든 at 이 timezone-aware 한 datetime
    for ev in final.status_history:
        assert ev.at.tzinfo is not None, f"naive datetime: {ev}"


def test_system_comment_on_status_change(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """상태 변경 시 시스템 코멘트가 comments.jsonl 에 추가됨."""
    issue = _make_issue(sample_issue_kwargs)

    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )

    comments = repository.list_comments(issue.id)
    sys_comments = [c for c in comments if c.kind == "system"]
    assert len(sys_comments) == 1, (
        f"시스템 코멘트가 1개여야 함, 실제 {len(sys_comments)}"
    )

    body = sys_comments[0].body
    assert "상태 변경" in body, f"body 에 '상태 변경' 누락: {body!r}"
    # 라벨: requested → 요청중, in_progress → 개발중
    assert "담당자확인요청" in body or "담당자검토중" in body, f"라벨 누락: {body!r}"
    # role 은 'system' 문자열
    assert sys_comments[0].role == "system"


# ---------------------------------------------------------------------------
# 코멘트
# ---------------------------------------------------------------------------


def test_add_comment_basic(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """add_comment → list_comments 에서 보여야 하고 id 가 'c' 로 시작."""
    issue = _make_issue(sample_issue_kwargs)

    comment = repository.add_comment(
        issue.id, author="rev", role=Role.reviewer, body="첫 코멘트"
    )

    assert comment.id.startswith("c"), f"코멘트 id 가 'c' 로 시작해야: {comment.id}"
    assert comment.kind == "comment"
    assert comment.body == "첫 코멘트"

    listed = repository.list_comments(issue.id)
    user_comments = [c for c in listed if c.kind == "comment"]
    assert len(user_comments) == 1
    assert user_comments[0].id == comment.id

    # updated_at 가 created_at 보다 미래 또는 같음
    refreshed = repository.get_issue(issue.id)
    assert refreshed.updated_at >= refreshed.created_at


def test_add_comment_empty_body_rejected(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """빈 body 는 ValueError."""
    issue = _make_issue(sample_issue_kwargs)

    with pytest.raises(ValueError):
        repository.add_comment(issue.id, author="rev", role=Role.reviewer, body="")
    with pytest.raises(ValueError):
        repository.add_comment(issue.id, author="rev", role=Role.reviewer, body="   ")


# ---------------------------------------------------------------------------
# 인덱스 동기화
# ---------------------------------------------------------------------------


def test_index_updated_on_create(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """create_issue 직후 index.json 에 엔트리가 존재."""
    issue = _make_issue(sample_issue_kwargs, title="인덱스 검증")

    raw = index_mod.read_index()
    found = [e for e in raw if e.get("id") == issue.id]
    assert len(found) == 1, "인덱스에 엔트리 없음"
    entry = found[0]
    assert entry["title"] == "인덱스 검증"
    assert entry["status"] == Status.assignee_request.value
    assert entry["comments_count"] == 0
    assert entry["images_count"] == 0


def test_index_updated_on_status_change(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """update_status 후 인덱스의 status 가 새 값."""
    issue = _make_issue(sample_issue_kwargs)
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )

    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry["status"] == Status.assignee_reviewing.value


def test_index_comments_count_includes_system(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """add_comment 와 status 변경(시스템 코멘트) 모두 comments_count 에 카운트."""
    issue = _make_issue(sample_issue_kwargs)

    # 일반 코멘트 2개
    repository.add_comment(issue.id, author="rev", role=Role.reviewer, body="c1")
    repository.add_comment(issue.id, author="rev", role=Role.reviewer, body="c2")

    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry["comments_count"] == 2

    # 상태 변경 → 시스템 코멘트 1개 추가
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )

    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry["comments_count"] == 3, (
        f"시스템 코멘트도 카운트되어야: 기대 3, 실제 {entry['comments_count']}"
    )


# ---------------------------------------------------------------------------
# 프로젝트 필드
# ---------------------------------------------------------------------------


def test_create_issue_with_project(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """create_issue 에 project 인자 → meta.json 라운드트립 + 인덱스 반영."""
    issue = repository.create_issue(project="proj-A", **sample_issue_kwargs)

    assert issue.project == "proj-A"

    fetched = repository.get_issue(issue.id)
    assert fetched.project == "proj-A"

    # 인덱스에도 project 가 들어가야 함
    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry.get("project") == "proj-A"


def test_create_issue_project_default_none(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """project 인자 미지정 시 None 으로 저장 — 기존 호환성."""
    issue = repository.create_issue(**sample_issue_kwargs)
    assert issue.project is None
    assert repository.get_issue(issue.id).project is None


def test_update_project(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """프로젝트 변경 → meta + 시스템 코멘트 + audit + 인덱스 갱신."""
    issue = repository.create_issue(project="proj-A", **sample_issue_kwargs)

    updated = repository.update_project(issue.id, "proj-B", actor="rev")
    assert updated.project == "proj-B"

    refreshed = repository.get_issue(issue.id)
    assert refreshed.project == "proj-B"

    # 시스템 코멘트
    sys_comments = [c for c in repository.list_comments(issue.id) if c.kind == "system"]
    assert any("프로젝트 변경" in c.body for c in sys_comments), (
        f"시스템 코멘트에 '프로젝트 변경' 없음: {[c.body for c in sys_comments]}"
    )
    # old → new 모두 본문에 포함
    target = next(c for c in sys_comments if "프로젝트 변경" in c.body)
    assert "proj-A" in target.body and "proj-B" in target.body

    # audit
    audit_lines = [
        json.loads(line)
        for line in paths.audit_log_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    project_audits = [
        a for a in audit_lines if a.get("action") == "update_project"
    ]
    assert len(project_audits) == 1
    assert project_audits[0]["detail"] == {"from": "proj-A", "to": "proj-B"}

    # 인덱스 갱신
    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry.get("project") == "proj-B"

    # 변경 없음 → early return (audit 더 이상 추가되지 않음)
    repository.update_project(issue.id, "proj-B", actor="rev")
    audit_lines2 = [
        json.loads(line)
        for line in paths.audit_log_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    project_audits2 = [
        a for a in audit_lines2 if a.get("action") == "update_project"
    ]
    assert len(project_audits2) == 1, "변경 없을 때 audit 추가되면 안 됨"


def test_update_project_normalizes_empty(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """빈 문자열 / 공백만 → None 으로 정규화."""
    issue = repository.create_issue(project="proj-A", **sample_issue_kwargs)

    updated = repository.update_project(issue.id, "", actor="rev")
    assert updated.project is None

    # 다시 값 넣고 공백만 입력 → None
    repository.update_project(issue.id, "proj-B", actor="rev")
    updated2 = repository.update_project(issue.id, "   ", actor="rev")
    assert updated2.project is None


def test_list_projects_unique(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """여러 항목의 project 중 unique 만 정렬되어 반환. None/빈은 제외."""
    repository.create_issue(project="zeta", **sample_issue_kwargs)
    repository.create_issue(project="alpha", **sample_issue_kwargs)
    repository.create_issue(project="alpha", **sample_issue_kwargs)  # 중복
    repository.create_issue(project=None, **sample_issue_kwargs)  # None
    repository.create_issue(project="", **sample_issue_kwargs)  # 빈 문자열 → None
    repository.create_issue(project="beta", **sample_issue_kwargs)

    projects = repository.list_projects()
    assert projects == ["alpha", "beta", "zeta"], (
        f"정렬된 unique project 리스트 기대 ['alpha','beta','zeta'], 실제 {projects}"
    )


def test_list_issues_with_project_filter(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """list_issues 의 project 필터 동작."""
    a = repository.create_issue(project="proj-A", **sample_issue_kwargs)
    b = repository.create_issue(project="proj-B", **sample_issue_kwargs)
    c = repository.create_issue(project="proj-A", **sample_issue_kwargs)
    d = repository.create_issue(**sample_issue_kwargs)  # project None

    # project='proj-A' → a, c 만
    pa = repository.list_issues(project="proj-A")
    assert {e.id for e in pa} == {a.id, c.id}

    # project='proj-B' → b 만
    pb = repository.list_issues(project="proj-B")
    assert {e.id for e in pb} == {b.id}

    # project=None (기본) → 모두 (4개)
    all_listed = repository.list_issues()
    assert {e.id for e in all_listed} == {a.id, b.id, c.id, d.id}

    # project='' 빈 문자열 → None 과 동일 (모두)
    empty = repository.list_issues(project="")
    assert {e.id for e in empty} == {a.id, b.id, c.id, d.id}

    # 존재하지 않는 프로젝트 → 빈 결과
    none_match = repository.list_issues(project="proj-X")
    assert none_match == []


# ---------------------------------------------------------------------------
# 삭제 태그 / 복구 / 레거시 archived 마이그레이션
# ---------------------------------------------------------------------------


def test_delete_issue_flag_and_visibility(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """delete_issue 후 deleted=True. 기본 list 에서 제외, include_deleted 로 포함."""
    issue = _make_issue(sample_issue_kwargs)
    deleted = repository.delete_issue(issue.id, actor="tester")

    assert deleted.deleted is True
    assert deleted.deleted_at is not None
    refreshed = repository.get_issue(issue.id)
    assert refreshed.deleted is True

    # 기본 list_issues 에서 제외
    default = repository.list_issues()
    assert all(e.id != issue.id for e in default), "삭제된 항목이 기본 목록에 포함"

    incl = repository.list_issues(include_deleted=True)
    assert any(e.id == issue.id for e in incl)


def test_restore_issue(temp_data_dir: Path, sample_issue_kwargs: dict) -> None:
    """restore_issue 로 삭제 태그를 떼면 다시 기본 목록에 나온다."""
    issue = _make_issue(sample_issue_kwargs)
    repository.delete_issue(issue.id, actor="tester")

    restored = repository.restore_issue(issue.id, actor="tester")
    assert restored.deleted is False
    assert restored.deleted_at is None

    default = repository.list_issues()
    assert any(e.id == issue.id for e in default), "복구된 항목이 목록에 없음"


def test_closed_issue_stays_in_closed_list_not_deleted(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """완료 항목은 시간이 지나도 완료로 조회된다 (옛 자동보관 회귀 방지).

    대시보드 '완료' = status=closed & include_deleted=False 이므로, 완료 처리만
    한 항목은 언제 조회해도 여기 잡혀야 한다.
    """
    issue = _make_issue(sample_issue_kwargs)
    _drive_to_closed(issue.id)

    done = repository.list_issues(status=Status.closed, include_closed=True)
    assert [e.id for e in done] == [issue.id]
    assert repository.get_issue(issue.id).deleted is False

    # 삭제 목록(deleted=True)에는 없어야 한다.
    all_entries = repository.list_issues(include_deleted=True, include_closed=True)
    assert [e.id for e in all_entries if e.deleted] == []


def _force_legacy_archived(item_id: str) -> str:
    """옛 archived=True 상태를 meta 직접 편집으로 재현. updated_at 원문 반환."""
    meta_path = paths.item_meta_path(item_id)
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    raw["archived"] = True
    raw.pop("deleted", None)
    raw.pop("deleted_at", None)
    meta_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return raw["updated_at"]


def test_restore_legacy_archived_closed_returns_to_done(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """레거시 archived=True 완료 항목 → 삭제가 아니라 완료로 복귀."""
    issue = _make_issue(sample_issue_kwargs)
    _drive_to_closed(issue.id)
    updated_before = _force_legacy_archived(issue.id)
    index_mod.rebuild_index()

    assert repository.restore_legacy_archived() == {Status.closed.value: 1}

    after = repository.get_issue(issue.id)
    assert after.deleted is False, "완료 항목이 삭제로 분류됨"
    assert after.archived is False
    # 정렬 보존 — 마이그레이션은 updated_at 을 건드리지 않는다 (meta 원문 비교).
    meta_path = paths.item_meta_path(issue.id)
    updated_after = json.loads(meta_path.read_text(encoding="utf-8"))["updated_at"]
    assert updated_after == updated_before, "마이그레이션이 updated_at 을 변경함"

    done = repository.list_issues(status=Status.closed, include_closed=True)
    assert [e.id for e in done] == [issue.id]


def test_restore_legacy_archived_keeps_open_items_in_workflow(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """미완료 archived 항목도 삭제로 추정하지 않고 원래 단계로 되살린다.

    완료 후 다시 열린 항목(완료 → 등록자검토중 → 반려)은 archived=True 인 채
    상태만 바뀌므로, 상태만으로 '사람이 삭제한 것' 을 구분할 수 없다.
    """
    issue = _make_issue(sample_issue_kwargs)
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    _force_legacy_archived(issue.id)
    index_mod.rebuild_index()

    assert repository.restore_legacy_archived() == {
        Status.assignee_reviewing.value: 1
    }

    after = repository.get_issue(issue.id)
    assert after.deleted is False, "미완료 항목이 삭제로 추정됨"
    assert after.archived is False
    # 담당자 처리 섹션(담당자검토중)에 다시 잡힌다.
    listed = repository.list_issues(status=Status.assignee_reviewing)
    assert [e.id for e in listed] == [issue.id]


def test_restore_legacy_archived_breakdown_and_idempotent(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """상태별 건수를 돌려주고, 두 번째 실행에는 대상이 없다 (부팅마다 안전)."""
    a = _make_issue(sample_issue_kwargs, title="A")
    b = _make_issue(sample_issue_kwargs, title="B")
    c = _make_issue(sample_issue_kwargs, title="C")
    _drive_to_closed(c.id)
    for iid in (a.id, b.id, c.id):
        _force_legacy_archived(iid)
    index_mod.rebuild_index()

    assert repository.restore_legacy_archived() == {
        Status.assignee_request.value: 2,
        Status.closed.value: 1,
    }
    assert repository.restore_legacy_archived() == {}

    # 셋 다 기본 목록(삭제 아님)에 있다.
    listed = {e.id for e in repository.list_issues(include_closed=True)}
    assert listed == {a.id, b.id, c.id}


def test_restore_legacy_archived_preserves_explicit_delete(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """새 방식으로 삭제한 항목(deleted=True)은 복구 대상이 아니다."""
    issue = _make_issue(sample_issue_kwargs)
    repository.delete_issue(issue.id, actor="tester")

    assert repository.restore_legacy_archived() == {}
    assert repository.get_issue(issue.id).deleted is True


# ---------------------------------------------------------------------------
# Urgency: critical (4 단계 확장)
# ---------------------------------------------------------------------------


def test_create_issue_with_critical_urgency(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """``urgency='critical'`` 로 생성 → meta.json/index 라운드트립 + 필터 동작."""
    sample_issue_kwargs["urgency"] = "critical"
    issue = repository.create_issue(**sample_issue_kwargs)

    # enum 으로 정규화
    assert issue.urgency == Urgency.critical
    assert issue.urgency.value == "critical"

    # meta.json 라운드트립
    fetched = repository.get_issue(issue.id)
    assert fetched.urgency == Urgency.critical

    # 인덱스에도 critical 로 저장
    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry["urgency"] == "critical"

    # urgency 필터링도 동작
    crits = repository.list_issues(urgency="critical")
    assert {e.id for e in crits} == {issue.id}


# ---------------------------------------------------------------------------
# 프로젝트 설정 (api_assignee + 카테고리 풀)
# ---------------------------------------------------------------------------


def test_set_get_api_assignee(temp_data_dir: Path) -> None:
    """set/get api_assignee 라운드트립 + None 으로 제거."""
    from core import project_settings as ps

    assert ps.get_api_assignee("P") is None

    ps.set_api_assignee("P", "외부김")
    assert ps.get_api_assignee("P") == "외부김"

    # 빈 문자열도 정규화되어 None 으로 처리
    ps.set_api_assignee("P", "  ")
    assert ps.get_api_assignee("P") is None

    # None 으로 명시 제거
    ps.set_api_assignee("P", "외부김")
    assert ps.get_api_assignee("P") == "외부김"
    ps.set_api_assignee("P", None)
    assert ps.get_api_assignee("P") is None


def test_project_categories_add_remove(temp_data_dir: Path) -> None:
    """add/remove_project_category 가 단계별 정확히 동작."""
    from core import project_settings as ps

    # 초기 빈 상태
    cats0 = ps.list_project_categories("P")
    assert cats0 == {"l1": [], "l2": [], "l3": []}

    # 3 단계 동시 추가
    ps.add_project_category("P", l1="로그인", l2="OAuth", l3="토큰")
    cats = ps.list_project_categories("P")
    assert "로그인" in cats["l1"]
    assert "OAuth" in cats["l2"]
    assert "토큰" in cats["l3"]

    # l1 만 추가 (다른 단계는 빈 인자)
    ps.add_project_category("P", l1="결제")
    cats = ps.list_project_categories("P")
    assert sorted(cats["l1"]) == ["결제", "로그인"]
    assert "OAuth" in cats["l2"]  # l2 영향 없음

    # 중복 추가는 noop
    ps.add_project_category("P", l1="로그인")
    cats = ps.list_project_categories("P")
    assert cats["l1"].count("로그인") == 1

    # l1 제거 → l2/l3 영향 없음
    ps.remove_project_category("P", l1="로그인")
    cats2 = ps.list_project_categories("P")
    assert "로그인" not in cats2["l1"]
    assert "결제" in cats2["l1"]
    assert "OAuth" in cats2["l2"]
    assert "토큰" in cats2["l3"]

    # 없는 라벨 제거는 noop
    ps.remove_project_category("P", l3="존재안함")
    cats3 = ps.list_project_categories("P")
    assert "토큰" in cats3["l3"]


def test_remove_project_settings(temp_data_dir: Path) -> None:
    """프로젝트 자체 정리 — api_assignee + 모든 카테고리 일괄 제거."""
    from core import project_settings as ps

    ps.set_api_assignee("P", "외부김")
    ps.add_project_category("P", l1="로그인", l2="OAuth")
    assert ps.get_api_assignee("P") == "외부김"
    assert "로그인" in ps.list_project_categories("P")["l1"]

    ps.remove_project_settings("P")

    assert ps.get_api_assignee("P") is None
    cats = ps.list_project_categories("P")
    assert cats == {"l1": [], "l2": [], "l3": []}


def test_project_settings_isolated_per_project(temp_data_dir: Path) -> None:
    """프로젝트 간 설정 격리 — A 변경이 B 에 영향 없음."""
    from core import project_settings as ps

    ps.set_api_assignee("A", "김외부")
    ps.set_api_assignee("B", "이외부")
    ps.add_project_category("A", l1="로그인")
    ps.add_project_category("B", l1="결제")

    assert ps.get_api_assignee("A") == "김외부"
    assert ps.get_api_assignee("B") == "이외부"
    assert ps.list_project_categories("A")["l1"] == ["로그인"]
    assert ps.list_project_categories("B")["l1"] == ["결제"]

    # A 를 정리해도 B 는 그대로
    ps.remove_project_settings("A")
    assert ps.get_api_assignee("B") == "이외부"
    assert ps.list_project_categories("B")["l1"] == ["결제"]


# ---------------------------------------------------------------------------
# api_check 진입 시 자동 assignee 전환
# ---------------------------------------------------------------------------


def test_update_status_api_check_no_auto_assignee(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """api_check 진입해도 담당자는 자동 변경되지 않는다 (개발자가 수동 관리)."""
    from core import project_settings

    # api_assignee 를 설정해 두어도 자동 전환이 일어나지 않아야 한다.
    project_settings.set_api_assignee("PROJ-X", "외부김")

    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "내부이"
    issue = repository.create_issue(project="PROJ-X", **kw)

    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="내부이", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.assignee_reviewed, actor="내부이", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.vendor_wait, actor="내부이", actor_role=Role.developer
    )
    issue2 = repository.update_status(
        issue.id, Status.vendor_request, actor="내부이", actor_role=Role.developer
    )

    # 담당자 유지 — 자동 변경 없음
    assert issue2.assignee == "내부이"
    refreshed = repository.get_issue(issue.id)
    assert refreshed.assignee == "내부이"
    assert refreshed.status == Status.vendor_request

    # 자동 변경 시스템 코멘트가 없어야 함
    comments = repository.list_comments(issue.id)
    assert not any("자동 변경" in c.body for c in comments)


def test_team_stage_full_hop(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """담당팀 단계 전 구간 전이가 동작 (검토완료→대기→확인중→회신→등록자확인요청).

    개발사 단계와 동일 구조 — 담당자는 유지되고 kind 는 dev 그대로다.
    """
    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "담당이"
    issue = repository.create_issue(**kw)
    for _s in (
        Status.assignee_reviewing,
        Status.assignee_reviewed,
        Status.team_wait,
        Status.team_request,
        Status.team_reply,
        Status.author_request,
    ):
        repository.update_status(
            issue.id, _s, actor="담당이", actor_role=Role.developer
        )
    got = repository.get_issue(issue.id)
    assert got.status == Status.author_request
    assert got.assignee == "담당이"  # 담당자 유지
    assert got.kind == "dev"

    # 검토완료에서 개발사·담당팀 둘 다로 갈 수 있어야 한다 (병렬 분기).
    from core.workflow import allowed_transitions

    _opts = allowed_transitions(Status.assignee_reviewed, Role.developer)
    assert Status.vendor_wait in _opts and Status.team_wait in _opts


def test_promote_to_criteria_from_any_kind(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """Temp 로 보내기는 dev 항목 등 어떤 kind 에서도 가능, 이미 Temp 면 거부 (req2)."""
    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "담당이"
    issue = repository.create_issue(**kw)  # kind=dev, status=assignee_request
    moved = repository.promote_to_criteria(issue.id, actor="등록")
    assert moved.kind == "criteria"
    assert moved.status == Status.temp
    assert moved.assignee is None  # 담당자 해제

    # 이미 Temp(criteria) 면 ValueError
    with pytest.raises(ValueError):
        repository.promote_to_criteria(issue.id, actor="등록")


def test_api_check_no_api_assignee(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """프로젝트에 api_assignee 미설정이면 그대로 유지."""
    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "이OO"
    kw["author"] = "dev"

    issue = repository.create_issue(project="PROJ-Y", **kw)
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.assignee_reviewed, actor="dev", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.vendor_wait, actor="dev", actor_role=Role.developer
    )
    issue2 = repository.update_status(
        issue.id, Status.vendor_request, actor="dev", actor_role=Role.developer
    )
    assert issue2.assignee == "이OO"  # 변경 없음

    # 자동 전환 시스템 코멘트가 없어야 함
    comments = repository.list_comments(issue.id)
    assert not any("API 담당자로 자동 변경" in c.body for c in comments)


def test_api_check_assignee_already_matches(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """이미 api_assignee 와 동일한 assignee 면 자동 전환 코멘트/audit 미생성."""
    from core import project_settings

    project_settings.set_api_assignee("PROJ-Z", "외부김")

    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "외부김"  # 처음부터 일치
    kw["author"] = "외부김"

    issue = repository.create_issue(project="PROJ-Z", **kw)
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="외부김", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.assignee_reviewed, actor="외부김", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.vendor_wait, actor="외부김", actor_role=Role.developer
    )
    issue2 = repository.update_status(
        issue.id, Status.vendor_request, actor="외부김", actor_role=Role.developer
    )
    assert issue2.assignee == "외부김"

    comments = repository.list_comments(issue.id)
    assert not any("API 담당자로 자동 변경" in c.body for c in comments)

    # UPDATE_ASSIGNEE auto=True audit 도 없어야 함
    audit_lines = [
        json.loads(line)
        for line in paths.audit_log_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    auto_assignee_audits = [
        a for a in audit_lines
        if a.get("action") == "update_assignee"
        and a.get("item_id") == issue.id
        and (a.get("detail") or {}).get("auto") is True
    ]
    assert auto_assignee_audits == []


def test_api_check_no_project_set(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """project 가 None 이면 자동 전환 로직이 건드리지 않음."""
    kw = dict(sample_issue_kwargs)
    kw["assignee"] = "내부이"
    kw["author"] = "dev"

    issue = repository.create_issue(**kw)  # project 미지정
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.assignee_reviewed, actor="dev", actor_role=Role.developer
    )
    repository.update_status(
        issue.id, Status.vendor_wait, actor="dev", actor_role=Role.developer
    )
    issue2 = repository.update_status(
        issue.id, Status.vendor_request, actor="dev", actor_role=Role.developer
    )
    assert issue2.assignee == "내부이"

    comments = repository.list_comments(issue.id)
    assert not any("API 담당자로 자동 변경" in c.body for c in comments)


# ---------------------------------------------------------------------------
# 확인대기 ↔ 담당자확인요청 (확인요청목록 ↔ 개발목록) 토글
# ---------------------------------------------------------------------------


def test_send_pending_to_dev_flips_kind_and_status(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """확인요청(확인대기) → 담당자확인요청: kind unimplemented→dev, 목록 이동 (1번)."""
    kw = dict(sample_issue_kwargs)
    kw["kind"] = "unimplemented"
    issue = repository.create_issue(**kw)
    # 확인요청 항목은 확인대기로 시작.
    assert issue.kind == "unimplemented"
    assert issue.status == Status.pending_check

    moved = repository.send_pending_to_dev(issue.id, actor="등록자")
    assert moved.kind == "dev"
    assert moved.status == Status.assignee_request
    # status_history 에 담당자확인요청 이벤트가 추가됨.
    assert moved.status_history[-1].status == Status.assignee_request

    # 개발목록(kind=dev)에는 보이고 확인요청목록(kind=unimplemented)에선 빠진다.
    dev_ids = [e.id for e in repository.list_issues(kind="dev")]
    unimpl_ids = [e.id for e in repository.list_issues(kind="unimplemented")]
    assert issue.id in dev_ids
    assert issue.id not in unimpl_ids


def test_send_pending_to_dev_rejects_non_unimplemented(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """dev 항목에 send_pending_to_dev → ValueError."""
    issue = repository.create_issue(**sample_issue_kwargs)  # 기본 kind=dev
    with pytest.raises(ValueError):
        repository.send_pending_to_dev(issue.id, actor="등록자")


def test_image_caption_roundtrip(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """사진 캡션 — 업로드 시 지정 + set_image_caption 수정 + 공백 trim + 범위검증."""
    import io

    from PIL import Image as _PILImage

    issue = repository.create_issue(**sample_issue_kwargs)
    buf = io.BytesIO()
    _PILImage.new("RGB", (20, 16), (10, 120, 200)).save(buf, format="PNG")

    ref = repository.add_image_from_bytes(
        issue.id, buf.getvalue(), "shot.png", "tester",
        kind="request", caption="  로그인 화면  ",
    )
    assert ref.caption == "로그인 화면"  # 저장 시 trim
    assert repository.get_issue(issue.id).images[0].caption == "로그인 화면"

    repository.set_image_caption(issue.id, 0, "에러 메시지", "tester")
    assert repository.get_issue(issue.id).images[0].caption == "에러 메시지"

    with pytest.raises(ValueError):
        repository.set_image_caption(issue.id, 9, "x", "tester")


def test_image_seq_no_reuse_after_delete(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """중간 이미지 삭제 후 추가해도 파일명(seq)이 재사용되지 않아 중복이 안 생긴다.

    옛 버그: seq = count+1 이라 가운데를 지우면 다음 추가가 같은 번호를 재사용해
    파일명이 겹치고 meta 에 중복 file 이 생겼다(상세보기 중복 key 크래시 원인).
    """
    import io

    from PIL import Image as _PILImage

    issue = repository.create_issue(**sample_issue_kwargs)

    def _png(color) -> bytes:
        buf = io.BytesIO()
        _PILImage.new("RGB", (12, 10), color).save(buf, format="PNG")
        return buf.getvalue()

    for color in [(200, 0, 0), (0, 200, 0), (0, 0, 200)]:
        repository.add_image_from_bytes(issue.id, _png(color), "shot.png", "t", kind="request")
    repository.delete_image(issue.id, 1, "t")  # 가운데(002) 삭제
    repository.add_image_from_bytes(issue.id, _png((9, 9, 9)), "shot.png", "t", kind="request")

    files = [r.file for r in repository.get_issue(issue.id).images]
    assert len(files) == 3
    assert len(files) == len(set(files)), f"파일명 중복 발생: {files}"


def test_send_pending_to_dev_sets_assignee(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """assignee 를 주면 담당자로 지정된다 (5번 — 상세보기에서 담당자 필수)."""
    kw = dict(sample_issue_kwargs)
    kw["kind"] = "unimplemented"
    issue = repository.create_issue(**kw)
    moved = repository.send_pending_to_dev(issue.id, actor="등록자", assignee="담당이")
    assert moved.kind == "dev"
    assert moved.status == Status.assignee_request
    assert moved.assignee == "담당이"


def test_send_dev_to_pending_roundtrip(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """담당자확인요청 → 확인대기: kind dev→unimplemented, 담당자 해제, 목록 복귀 (3번)."""
    kw = dict(sample_issue_kwargs)
    kw["kind"] = "unimplemented"
    issue = repository.create_issue(**kw)
    dev = repository.send_pending_to_dev(issue.id, actor="등록자")
    # 담당자를 배정해 둔 상태에서 되돌려도 해제되는지 확인.
    repository.update_assignee(dev.id, "담당이", actor="등록자")

    back = repository.send_dev_to_pending(issue.id, actor="등록자")
    assert back.kind == "unimplemented"
    assert back.status == Status.pending_check
    assert back.assignee is None
    assert back.status_history[-1].status == Status.pending_check

    unimpl_ids = [e.id for e in repository.list_issues(kind="unimplemented")]
    dev_ids = [e.id for e in repository.list_issues(kind="dev")]
    assert issue.id in unimpl_ids
    assert issue.id not in dev_ids


def test_send_dev_to_pending_requires_assignee_request(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """담당자확인요청이 아닌 상태에서 send_dev_to_pending → ValueError."""
    issue = repository.create_issue(**sample_issue_kwargs)  # 기본 kind=dev, 담당자확인요청
    repository.update_status(
        issue.id, Status.assignee_reviewing, actor="dev", actor_role=Role.developer
    )
    with pytest.raises(ValueError):
        repository.send_dev_to_pending(issue.id, actor="등록자")


def test_set_rule_status_roundtrip_and_index(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """성격 라벨 변경 → meta·인덱스 반영, 시스템 코멘트, 검증/무변경/silent (docs/09)."""
    it = repository.create_issue(**sample_issue_kwargs)
    assert repository.get_issue(it.id).rule_status == "unsorted"  # 기본값

    # 잘못된 값 → ValueError
    with pytest.raises(ValueError):
        repository.set_rule_status(it.id, "bogus", actor="a")

    # 변경 → meta + 인덱스 반영 + 시스템 코멘트 발생
    repository.set_rule_status(it.id, "confirmed", actor="a")
    assert repository.get_issue(it.id).rule_status == "confirmed"
    entry = next(e for e in repository.list_issues(kind="dev") if e.id == it.id)
    assert entry.rule_status == "confirmed"
    n_sys = len([c for c in repository.list_comments(it.id) if c.kind == "system"])
    assert n_sys >= 1

    # 같은 값 재설정 → 무변경 (시스템 코멘트 증가 없음)
    repository.set_rule_status(it.id, "confirmed", actor="a")
    n_sys2 = len([c for c in repository.list_comments(it.id) if c.kind == "system"])
    assert n_sys2 == n_sys

    # silent=True → 시스템 코멘트 없이 변경
    repository.set_rule_status(it.id, "needs_check", actor="a", silent=True)
    assert repository.get_issue(it.id).rule_status == "needs_check"
    n_sys3 = len([c for c in repository.list_comments(it.id) if c.kind == "system"])
    assert n_sys3 == n_sys
