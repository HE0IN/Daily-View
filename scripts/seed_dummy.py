"""성능 검증용 더미 데이터 생성 스크립트.

docs/06_implementation_plan.md 6.4 의 "1년치 2,500건에서 응답시간 1초 이내" 검증을
위한 데이터를 채워 넣는다.

사용:
    python scripts/seed_dummy.py --count 100        # 기본 100건
    python scripts/seed_dummy.py --count 2500       # 1년치 부하 시뮬레이션

특징
----
- 한글 제목/설명/태그를 무작위로 조합 (한글 처리 검증 겸용)
- 일부(약 30%) 항목은 코멘트 1~3개 + 상태 1~2회 변경으로 다양한 분포 생성
- 일부(약 20%) 항목은 1×1 PNG 더미 이미지를 1~2장 첨부 (이미지 한도/슬러그 검증)
- 각 100건마다 진행률 출력
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import time
from pathlib import Path

# Windows 콘솔(cp949) 에서 한글 출력 시 UnicodeEncodeError 방지.
# Python 3.7+ 의 reconfigure 로 utf-8 지정. errors="replace" 로 안전 폴백.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# 프로젝트 루트를 sys.path 에 추가 (scripts/ 에서 직접 실행 대비)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PIL import Image  # noqa: E402

from core import paths, repository  # noqa: E402
from core.models import Role, Status, Urgency  # noqa: E402


# ---------------------------------------------------------------------------
# 무작위 코퍼스 (한글)
# ---------------------------------------------------------------------------

_TITLES = [
    "로그인 후 메인 진입 시 화면 깜빡임",
    "결제 페이지 한글 깨짐 현상",
    "검색 결과 정렬 옵션 누락",
    "관리자 권한 사용자에게 메뉴 미노출",
    "스크롤 시 헤더 배경 투명 처리 오류",
    "모바일 환경에서 폼 제출 후 응답 지연",
    "비밀번호 변경 알림 누락",
    "다국어 한국어 라벨 일부 영문 표기",
    "이미지 업로드 후 미리보기 안 보임",
    "쿠폰 적용 시 합계 잘못 계산",
    "로그아웃 후에도 캐시 데이터 노출",
    "회원가입 약관 페이지 깨짐",
    "장바구니 수량 변경이 새로고침 안 됨",
    "주문 취소 처리가 화면에 미반영",
    "알림 배지 카운트 누락",
    "대시보드 그래프 라벨 짤림",
    "엑셀 다운로드 한글 인코딩 깨짐",
    "iOS Safari 에서 스크롤 잠김",
    "설정 저장 후 페이지 리로드 필요",
    "마이페이지 프로필 사진 업로드 실패",
]

_DESC_TEMPLATES = [
    "재현 절차:\n1. {a}\n2. {b}\n\n기대: {c}\n실제: {d}",
    "{a} 과정에서 {d} 가 발생합니다.\n\n환경: Chrome 120, Windows 11.\n로그: 콘솔에 별다른 에러 없음.",
    "{c} 가 정상 동작이지만 현재는 {d} 입니다. 우회: {b}.",
    "스크린샷 첨부 — {a}.\n관련 데이터 ID: 12345.",
]

_DESC_TOKENS = {
    "a": [
        "특정 사용자 계정으로 로그인",
        "결제 단계까지 진행",
        "관리자 모드 진입",
        "긴 한글 검색어 입력",
        "다중 이미지 업로드",
    ],
    "b": [
        "다른 브라우저에서 재시도",
        "쿠키 삭제 후 재시도",
        "관리자 권한으로 강제 호출",
        "PC 재부팅",
    ],
    "c": [
        "정상 표시되어야 함",
        "에러 토스트가 떠야 함",
        "총 합계가 정확해야 함",
        "관련 메뉴가 보여야 함",
    ],
    "d": [
        "빈 화면이 노출",
        "한글이 ?? 로 깨져 표시",
        "500 에러 발생",
        "페이지가 무한 로딩",
    ],
}

_TAGS = [
    "ui", "ux", "결제", "로그인", "검색", "관리자", "모바일",
    "i18n", "회원", "장바구니", "알림", "성능", "보안", "버그", "개선",
]

_AUTHORS_REVIEWER = ["김검토", "이QA", "박기획", "Sarah Lee", "정수민"]
_AUTHORS_DEVELOPER = ["최개발", "한백엔드", "Mike Park", "유프론트", "Yoon Kim"]


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _make_dummy_png(width: int = 1, height: int = 1) -> bytes:
    """매우 작은 더미 PNG 바이트 생성."""
    img = Image.new("RGB", (width, height), color=(random.randint(0, 255),) * 3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _random_description() -> str:
    template = random.choice(_DESC_TEMPLATES)
    return template.format(
        a=random.choice(_DESC_TOKENS["a"]),
        b=random.choice(_DESC_TOKENS["b"]),
        c=random.choice(_DESC_TOKENS["c"]),
        d=random.choice(_DESC_TOKENS["d"]),
    )


def _random_tags() -> list[str]:
    n = random.randint(0, 3)
    return random.sample(_TAGS, k=n) if n else []


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def seed(count: int) -> None:
    paths.ensure_data_dirs()
    print(f"[seed] 더미 데이터 생성 시작 - 목표 {count}건")
    print(f"  DATA_DIR: {paths.data_dir()}")
    started_at = time.perf_counter()

    created_ids: list[str] = []
    failed = 0

    for i in range(count):
        try:
            title = f"{random.choice(_TITLES)} #{i + 1}"
            description = _random_description()
            urgency = random.choices(
                [Urgency.high, Urgency.normal, Urgency.low],
                weights=[1, 5, 2],
            )[0]
            author = random.choice(_AUTHORS_REVIEWER)
            assignee = (
                random.choice(_AUTHORS_DEVELOPER)
                if random.random() < 0.7
                else None
            )

            issue = repository.create_issue(
                title=title,
                description=description,
                urgency=urgency,
                author=author,
                author_role=Role.reviewer,
                assignee=assignee,
                tags=_random_tags(),
            )
            created_ids.append(issue.id)

            # 30% 확률로 코멘트 1~3개
            if random.random() < 0.3:
                for _ in range(random.randint(1, 3)):
                    speaker = random.choice(_AUTHORS_DEVELOPER + _AUTHORS_REVIEWER)
                    speaker_role = (
                        Role.developer
                        if speaker in _AUTHORS_DEVELOPER
                        else Role.reviewer
                    )
                    repository.add_comment(
                        issue.id,
                        speaker,
                        speaker_role,
                        f"확인 중입니다 — {random.choice(['추가 정보 부탁', '재현 됨', '수정 진행', '완료 처리'])}.",
                    )

            # 30% 확률로 상태 1~2회 진행
            if random.random() < 0.3:
                # requested -> in_progress
                dev = assignee or random.choice(_AUTHORS_DEVELOPER)
                repository.update_status(
                    issue.id, Status.in_progress, dev, Role.developer
                )
                if random.random() < 0.5:
                    # in_progress -> reviewing (개발자가 검토 요청)
                    repository.update_status(
                        issue.id, Status.reviewing, dev, Role.developer
                    )
                    _r = random.random()
                    if _r < 0.5:
                        # reviewing -> closed (검토자 완료)
                        repository.update_status(
                            issue.id, Status.closed, author, Role.reviewer
                        )
                    elif _r < 0.7:
                        # reviewing -> needs_recheck (추가확인필요)
                        repository.update_status(
                            issue.id, Status.needs_recheck, author, Role.reviewer
                        )
                    elif _r < 0.85:
                        # reviewing -> rejected (반려)
                        repository.update_status(
                            issue.id, Status.rejected, author, Role.reviewer
                        )

            # 20% 확률로 더미 이미지 첨부
            if random.random() < 0.2:
                for j in range(random.randint(1, 2)):
                    try:
                        repository.add_image_from_bytes(
                            issue.id,
                            _make_dummy_png(),
                            f"더미_{j + 1}.png",
                            author,
                        )
                    except ValueError:
                        # 한도 초과 등은 무시
                        pass

        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [경고] {i + 1}번째 항목 생성 실패: {exc}")

        # 진행률
        if (i + 1) % 100 == 0 or (i + 1) == count:
            elapsed = time.perf_counter() - started_at
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(
                f"  진행: {i + 1}/{count} ({(i + 1) / count * 100:.0f}%) "
                f"| 경과 {elapsed:.1f}s | {rate:.1f} item/s"
            )

    elapsed = time.perf_counter() - started_at
    print()
    print(f"[seed] 완료: {len(created_ids)}건 생성, {failed}건 실패, 총 {elapsed:.1f}s")
    if created_ids:
        print(f"  마지막 생성 id: {created_ids[-1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily View 더미 데이터 생성")
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=100,
        help="생성할 항목 수 (기본 100)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="random.seed 값 (재현성 필요할 때)",
    )
    args = parser.parse_args()

    if args.count <= 0:
        print("--count 는 양수여야 합니다.")
        return 1

    if args.seed is not None:
        random.seed(args.seed)

    seed(args.count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
