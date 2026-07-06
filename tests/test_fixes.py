"""문제점 리뷰(#1~#16) 수정 회귀 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import index as index_mod
from core import paths, repository
from core.models import Comment


# --- #1 / #6 / #7: 손상(비-UTF-8) 내성 --------------------------------------


def test_rebuild_index_survives_bad_utf8_comments(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """한 항목의 comments.jsonl 이 비-UTF-8 여도 전체 재구축이 죽지 않고 계속된다 (#1)."""
    a = repository.create_issue(**sample_issue_kwargs)
    b = repository.create_issue(**sample_issue_kwargs)
    paths.item_comments_path(b.id).write_bytes(b'{"x":1}\n\xff\xfe torn\n')

    index_mod.rebuild_index()
    ids = {e["id"] for e in index_mod.read_index()}
    assert a.id in ids and b.id in ids  # 손상 파일이 다른 항목 인덱싱을 막지 않음


def test_read_index_survives_bad_utf8(temp_data_dir: Path) -> None:
    """index.json 이 비-UTF-8 로 손상돼도 read_index 는 빈 리스트를 반환(크래시 X, #6)."""
    paths.index_path().write_bytes(b"\xff\xfe{ not valid utf8")
    assert index_mod.read_index() == []


def test_verify_index_survives_bad_utf8_meta(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """meta.json 이 비-UTF-8 여도 verify_index 는 크래시 대신 문제로 리포트한다 (#7)."""
    a = repository.create_issue(**sample_issue_kwargs)
    paths.item_meta_path(a.id).write_bytes(b'{"id":"x","title":"\xff\xfe"}')
    ok, problems = index_mod.verify_index()  # 예외 없이 반환되어야 함
    assert isinstance(problems, list)


# --- #4: 승격 시 카테고리 보존 ----------------------------------------------


def test_promote_preserves_category_when_none(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    kw = dict(sample_issue_kwargs)
    kw.update(kind="unimplemented", category_l1="도면", project="P")
    it = repository.create_issue(**kw)
    assert repository.get_issue(it.id).category_l1 == "도면"

    # 카테고리 None 으로 승격 → 기존값 보존
    moved = repository.promote_unimplemented(
        it.id, title="t", description="d", urgency="normal",
        assignee="담당", actor="a",
        category_l1=None, category_l2=None, category_l3=None,
    )
    assert moved.category_l1 == "도면"


def test_promote_overwrites_category_when_given(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    kw = dict(sample_issue_kwargs)
    kw.update(kind="unimplemented", category_l1="A", project="P")
    it = repository.create_issue(**kw)
    moved = repository.promote_unimplemented(
        it.id, title="t", description="d", urgency="normal",
        assignee="담당", actor="a", category_l1="B",
    )
    assert moved.category_l1 == "B"


# --- #8: naive datetime 좌표계 정규화 ---------------------------------------


def test_comment_naive_at_coerced_to_aware() -> None:
    c1 = Comment(id="1", at="2024-01-01T00:00:00", author="a", role="developer", body="x")
    assert c1.at.tzinfo is not None  # naive → aware 강제

    c2 = Comment(
        id="2", at="2024-01-02T00:00:00+09:00", author="a", role="developer", body="y"
    )
    # naive + aware 혼재 정렬이 TypeError 없이 동작해야 함
    ordered = sorted([c2, c1], key=lambda c: c.at)
    assert [c.id for c in ordered] == ["1", "2"]


# --- #9: 잘못된 입력 시 항목 폴더 leak 없음 ---------------------------------


def test_create_issue_invalid_leaves_no_dir(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    items_dir = paths.items_dir()
    before = {p.name for p in items_dir.iterdir()} if items_dir.exists() else set()

    kw = dict(sample_issue_kwargs)
    kw["urgency"] = "urgent"  # 유효하지 않은 긴급도 → 검증 실패
    with pytest.raises(Exception):
        repository.create_issue(**kw)

    after = {p.name for p in items_dir.iterdir()} if items_dir.exists() else set()
    assert before == after  # 빈 항목 폴더가 생기지 않음


# --- #10: 이미지 seq 4자리 파싱 ---------------------------------------------


def test_next_image_seq_parses_four_digits(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    it = repository.create_issue(**sample_issue_kwargs)
    d = paths.item_images_dir(it.id)
    (d / "1000_x.png").write_bytes(b"x")
    assert repository._next_image_seq(it.id) == 1001  # '100' 이 아니라 '1000' 파싱
