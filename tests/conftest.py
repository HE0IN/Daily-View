"""공유 fixture.

`core.paths.data_dir()` 가 호출 시점마다 ``os.environ["DATA_DIR"]`` 을 읽도록
구현되어 있어 (lru_cache 없음), monkeypatch.setenv 만으로 격리된 데이터 루트를
제공할 수 있다. 안전을 위해 fixture 종료 시 환경변수 원상복구 + 사전에
``ensure_data_dirs()`` 로 필수 디렉토리를 만들어 둔다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core import paths


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """함수 단위로 격리된 DATA_DIR 환경.

    - tmp_path 를 DATA_DIR 환경변수로 설정
    - ensure_data_dirs() 호출하여 필수 하위 디렉토리(items, logs, backups, .locks) 생성
    - yield 후 monkeypatch 가 자동으로 환경변수 원상복구
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # data_dir() 가 매 호출마다 환경변수를 읽으므로 캐시 무효화는 불필요.
    # 그래도 회귀 방어로 lru_cache 가 추후 추가될 가능성을 차단하기 위해 시도.
    cache_clear = getattr(paths.data_dir, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

    paths.ensure_data_dirs()

    # data_dir 가 실제로 의도한 경로를 가리키는지 sanity check
    assert paths.data_dir() == tmp_path.resolve(), (
        f"DATA_DIR 환경변수가 fixture 에 반영되지 않음: "
        f"expected={tmp_path.resolve()}, actual={paths.data_dir()}"
    )

    return paths.data_dir()


@pytest.fixture
def sample_issue_kwargs() -> dict:
    """create_issue 에 넣을 기본 인자 dict 반환.

    개별 테스트가 일부만 override 해서 사용할 수 있도록 항상 새 dict 를 반환.
    """
    return {
        "title": "샘플 이슈",
        "description": "기본 설명",
        "urgency": "normal",
        "author": "tester",
        "author_role": "reviewer",
        "assignee": None,
        "tags": [],
    }
