"""개발사 요청 PDF 생성(pdf_export) 스모크 테스트 — 가로 레이아웃 + 코멘트 + 이미지.

실제 렌더 내용까지 검증하긴 어렵지만, 새 코드 경로(최근 코멘트 조회 +
이미지 grid 배치 + landscape 페이지)가 예외 없이 PDF bytes 를 만드는지 확인한다.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from core import pdf_export, repository
from core.models import Role


def _png_bytes(w: int = 40, h: int = 30, color=(200, 60, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_build_issues_pdf_landscape_with_comment_and_images(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """제목/설명 + 사람 코멘트 + 이미지 여러 장 → landscape PDF bytes."""
    kw = dict(sample_issue_kwargs)
    kw["title"] = "개발사 요청 항목"
    kw["description"] = "설명입니다.\n여러 줄로 된 설명."
    issue = repository.create_issue(**kw)

    # 사람 코멘트(최근) + 시스템 코멘트가 섞여 있어도 사람 것만 실려야 한다.
    repository.add_comment(issue.id, "담당이", Role.developer, "개발사에 전달할 내용")

    # 크기가 제각각인 이미지 여러 장 (grid 배치 경로).
    for i, (w, h) in enumerate([(40, 30), (30, 60), (80, 20)], start=1):
        repository.add_image_from_bytes(
            issue.id, _png_bytes(w, h), f"shot{i}.png", "담당이", kind="request"
        )

    data = pdf_export.build_issues_pdf([repository.get_issue(issue.id)])
    assert data[:4] == b"%PDF", "PDF 시그니처여야 함"
    assert len(data) > 1000


def test_build_issues_pdf_single_image_enlarged(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """이미지가 1장이면 단일 이미지 경로(업스케일 배치)로도 PDF 가 만들어진다 (2번)."""
    kw = dict(sample_issue_kwargs)
    kw["title"] = "한 장짜리"
    issue = repository.create_issue(**kw)
    # 작은 이미지 1장(+캡션) → 가용 영역에 맞게 키우고 사진 밑에 캡션 표시.
    repository.add_image_from_bytes(
        issue.id, _png_bytes(24, 18), "only.png", "담당이",
        kind="request", caption="로그인 화면",
    )
    data = pdf_export.build_issues_pdf([repository.get_issue(issue.id)])
    assert data[:4] == b"%PDF"
    assert len(data) > 1000


def test_build_issues_pdf_empty_and_no_attachments(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """이미지/코멘트 없는 항목, 그리고 빈 입력도 안전하게 PDF 를 만든다."""
    issue = repository.create_issue(**sample_issue_kwargs)
    data = pdf_export.build_issues_pdf([repository.get_issue(issue.id)])
    assert data[:4] == b"%PDF"

    # 빈 입력 → 빈(흰) 페이지 1장.
    empty = pdf_export.build_issues_pdf([])
    assert empty[:4] == b"%PDF"
