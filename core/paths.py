"""경로 단일 출처 모듈.

저장소 디렉토리·파일 위치는 모두 이 모듈을 통해 노출한다.
환경변수 ``DATA_DIR`` 이 설정되어 있으면 그 경로를, 없으면 프로젝트 루트의
``data/`` 디렉토리를 사용한다. ``.env`` 가 존재하면 python-dotenv 로 자동 로드.

자세한 디렉토리 트리는 docs/02_storage.md 2.2 절 참고.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트의 .env 를 1회만 로드. 이미 로드된 환경변수는 덮어쓰지 않는다.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)

# Item ID 형식 검증 정규식.
# repository._new_item_id() 가 만드는 형식: ``{YYYY-MM-DD}_{6-hex}`` 만 허용.
# 외부 입력(예: ?id= 쿼리 파라미터)이 path traversal 페이로드를 끼워넣지 못하도록
# 모든 디스크 경로 진입점(item_dir / item_meta_path / 등)이 이 검증을 통과해야 한다.
# ``\A`` / ``\Z`` 앵커를 써서 trailing newline 까지 거부 (Python re 의 ``$`` 는
# 기본적으로 마지막 개행 직전을 허용하므로 ``\n`` 바이트 주입이 통과될 수 있다).
_ITEM_ID_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}_[0-9a-f]{6}\Z")


class InvalidItemIdError(ValueError):
    """``item_id`` 형식이 ``YYYY-MM-DD_xxxxxx`` (6자 hex) 가 아닐 때 발생."""


def _validate_item_id(item_id: str) -> str:
    """item_id 형식 검증. 통과하면 그대로 반환, 실패하면 ``InvalidItemIdError``.

    Path traversal (``../`` / 절대경로 / 백슬래시 / NULL 문자 등) 을 한 곳에서 차단.
    """
    if not isinstance(item_id, str) or not _ITEM_ID_RE.match(item_id):
        raise InvalidItemIdError(f"잘못된 item_id 형식: {item_id!r}")
    return item_id


def project_root() -> Path:
    """리포지토리 루트 (Daily View/) 절대경로 반환."""
    return _PROJECT_ROOT


def data_dir() -> Path:
    """데이터 루트 디렉토리.

    환경변수 ``DATA_DIR`` 우선, 없으면 ``{project_root}/data``.
    호출 시점에 mkdir 하지 않는다 — 생성은 :func:`ensure_data_dirs` 또는
    하위 함수에서 처리.
    """
    env_value = os.environ.get("DATA_DIR")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return _PROJECT_ROOT / "data"


def items_dir() -> Path:
    """``{data_dir}/items``."""
    return data_dir() / "items"


def item_dir(item_id: str) -> Path:
    """``{items_dir}/{item_id}``. 디렉토리 생성은 호출자 책임.

    형식 검증을 통과한 item_id 만 받는다 — path traversal 차단.
    """
    return items_dir() / _validate_item_id(item_id)


def index_path() -> Path:
    """``{data_dir}/index.json``."""
    return data_dir() / "index.json"


def audit_log_path() -> Path:
    """``{data_dir}/logs/audit.log``."""
    return data_dir() / "logs" / "audit.log"


def backups_dir() -> Path:
    """``{data_dir}/backups``."""
    return data_dir() / "backups"


def locks_dir() -> Path:
    """``{data_dir}/.locks`` — 글로벌/인덱스 락 보관소."""
    return data_dir() / ".locks"


def item_meta_path(item_id: str) -> Path:
    """``{item_dir}/meta.json``."""
    return item_dir(item_id) / "meta.json"


def item_comments_path(item_id: str) -> Path:
    """``{item_dir}/comments.jsonl``."""
    return item_dir(item_id) / "comments.jsonl"


def item_images_dir(item_id: str) -> Path:
    """``{item_dir}/images``."""
    return item_dir(item_id) / "images"


def item_log_path(item_id: str) -> Path:
    """``{item_dir}/item.log`` — 항목별 audit 로그."""
    return item_dir(item_id) / "item.log"


def ensure_data_dirs() -> None:
    """앱 시작 시 1회 호출. 필수 디렉토리들을 미리 생성한다.

    개별 쓰기 경로(meta.json, audit.log 등)는 atomic_write_json / 락 헬퍼가
    부모 디렉토리를 자동 생성하므로 본 함수는 보조적 안전장치다.
    """
    for path in (
        data_dir(),
        items_dir(),
        data_dir() / "logs",
        backups_dir(),
        locks_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)


__all__ = [
    "InvalidItemIdError",
    "project_root",
    "data_dir",
    "items_dir",
    "item_dir",
    "index_path",
    "audit_log_path",
    "backups_dir",
    "locks_dir",
    "item_meta_path",
    "item_comments_path",
    "item_images_dir",
    "item_log_path",
    "ensure_data_dirs",
]
