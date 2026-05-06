"""보안 패치 회귀 방지 테스트.

이 파일이 깨지면 Path Traversal / 입력 검증 보호가 약해진 것이므로
실패를 무시하지 말 것. 자세한 배경은 docs/05_setup.md 의 트러블슈팅 + 보안 감사
보고서 참고.
"""

from __future__ import annotations

import pytest

from core import paths, repository
from core.paths import InvalidItemIdError


# ---------------------------------------------------------------------------
# Path Traversal — paths.item_dir() 입력 검증
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc/passwd",
        "../../../../Windows/System32",
        "..\\..\\..\\Windows",
        "2026-04-28_a3f1b2/../other",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "..",
        ".",
        "",
        "2026-04-28_XYZ123",  # 6자이지만 hex 아님 (대문자/비-hex)
        "2026-04-28_a3f1b2x",  # 7자
        "2026-04-28_a3f1b",  # 5자
        "2026-4-28_a3f1b2",  # 월/일 자릿수 부족
        "abcd-ef-gh_a3f1b2",  # 날짜가 숫자 아님
        "2026-04-28 a3f1b2",  # 언더스코어 아닌 공백
        "2026-04-28_a3f1b2\x00",  # NUL 바이트
        "2026-04-28_a3f1b2\n",  # 개행
        "2026-04-28_a3f1b2/extra",  # 슬래시 포함
    ],
)
def test_item_dir_rejects_invalid_id_formats(bad_id: str) -> None:
    """잘못된 형식의 item_id 는 디스크 경로 결합 전에 차단되어야 한다."""
    with pytest.raises(InvalidItemIdError):
        paths.item_dir(bad_id)


@pytest.mark.parametrize(
    "non_str",
    [None, 123, 12.5, ["2026-04-28_a3f1b2"], {"id": "x"}, b"2026-04-28_a3f1b2"],
)
def test_item_dir_rejects_non_string_id(non_str) -> None:
    """문자열이 아닌 입력도 차단."""
    with pytest.raises(InvalidItemIdError):
        paths.item_dir(non_str)


@pytest.mark.parametrize(
    "good_id",
    [
        "2026-04-28_a3f1b2",
        "2025-12-31_000000",
        "2099-01-01_ffffff",
        "2026-04-28_abcdef",
    ],
)
def test_item_dir_accepts_valid_id(good_id: str, temp_data_dir) -> None:
    """``YYYY-MM-DD_<6 hex>`` 형식은 정상 통과."""
    p = paths.item_dir(good_id)
    assert p.name == good_id
    # 결합된 경로는 반드시 items_dir 하위
    assert paths.items_dir() in p.parents


# ---------------------------------------------------------------------------
# Path Traversal — paths.item_meta_path / item_comments_path / item_images_dir /
# item_log_path 도 item_dir() 를 거치므로 동일하게 차단되어야 한다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        paths.item_meta_path,
        paths.item_comments_path,
        paths.item_images_dir,
        paths.item_log_path,
    ],
)
def test_all_item_path_helpers_validate(fn) -> None:
    """모든 항목별 경로 헬퍼가 traversal 시도를 차단한다."""
    with pytest.raises(InvalidItemIdError):
        fn("../../../etc/passwd")


# ---------------------------------------------------------------------------
# repository 진입점도 동일하게 차단 (paths 를 통하기 때문)
# ---------------------------------------------------------------------------


def test_repository_get_issue_blocks_traversal(temp_data_dir) -> None:
    """``?id=../../...`` 가 그대로 repository.get_issue 에 도달해도 차단."""
    with pytest.raises(InvalidItemIdError):
        repository.get_issue("../../../etc/passwd")


def test_repository_list_comments_blocks_traversal(temp_data_dir) -> None:
    with pytest.raises(InvalidItemIdError):
        repository.list_comments("..\\..\\Windows")


def test_repository_add_comment_blocks_traversal(temp_data_dir) -> None:
    with pytest.raises(InvalidItemIdError):
        repository.add_comment(
            "../escape", author="bad", role="reviewer", body="x"
        )


def test_repository_create_issue_produces_valid_id(temp_data_dir) -> None:
    """create_issue 가 만드는 새 ID 는 검증 정규식을 통과해야 한다."""
    issue = repository.create_issue(
        title="형식 확인",
        description="d",
        urgency="normal",
        author="홍길동",
        author_role="reviewer",
    )
    # 검증 통과해야 함 — 통과 못하면 paths.item_dir() 가 InvalidItemIdError
    paths.item_dir(issue.id)
