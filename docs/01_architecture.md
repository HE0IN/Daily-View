# 01. 아키텍처

## 1.1 기술 스택

| 항목 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.12.7 | 사용자 지정 |
| 프레임워크 | Streamlit ≥ 1.39 | UI 코드 작성량 최소화, 멀티페이지 지원 |
| 저장소 | 로컬 파일 (JSON + 이미지) | DB 미사용 요구사항 |
| 동시성 보호 | filelock | 다중 사용자 동시 쓰기 방지 |
| 데이터 검증 | pydantic v2 | meta.json 스키마 일관성 보장 |
| 이미지 처리 | Pillow | 썸네일 생성, 회전 보정 |
| 환경 변수 | python-dotenv | 포트/데이터 경로 외부화 |
| 자동 새로고침 | streamlit-autorefresh (옵션) | 다른 사용자가 변경한 내용 반영 |

## 1.2 전체 폴더 구조

```
Daily View/
├── app.py                      # 진입점: 사이드바 사용자 식별 + 대시보드
├── pages/                      # Streamlit 멀티페이지 (자동 라우팅)
│   ├── 1_요청목록.py
│   ├── 2_새요청등록.py
│   ├── 3_상세보기.py            # ?id=... query param으로 진입
│   └── 4_통계.py
├── core/
│   ├── __init__.py
│   ├── models.py               # pydantic 모델: Issue, Comment, StatusHistory
│   ├── repository.py           # 항목 CRUD (파일 I/O 캡슐화)
│   ├── index.py                # index.json 갱신/조회
│   ├── locking.py              # FileLock 헬퍼 + atomic write
│   ├── workflow.py             # 상태 전이 규칙, 권한 체크
│   └── logger.py               # audit log 기록
├── ui/
│   ├── __init__.py
│   ├── components.py           # 카드, 배지, 색상 매핑 등 재사용 컴포넌트
│   ├── theme.py                # 긴급도/상태 색상 상수
│   └── auth.py                 # 사이드바 사용자 식별 위젯
├── data/                       # 런타임 생성 (gitignore 대상)
│   ├── index.json
│   ├── items/
│   │   └── {YYYY-MM-DD}_{shortid}/
│   │       ├── meta.json
│   │       ├── images/
│   │       └── item.log
│   ├── logs/
│   │   └── audit.log
│   ├── backups/
│   └── .locks/
├── tests/                      # (선택) pytest 단위 테스트
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## 1.3 모듈 책임 분담

- **app.py**: 페이지 진입점. 사이드바에서 사용자 정보 받아 `st.session_state["user"]`에 저장. 대시보드(긴급도/상태별 카운트 + 내 담당 큐) 렌더.
- **pages/**: 각 페이지는 `core` 모듈의 함수만 호출. UI 코드는 가능한 `ui/components.py`로 추출.
- **core/repository.py**: 모든 디스크 I/O의 단일 진입점. `list_issues()`, `get_issue(id)`, `create_issue()`, `update_status()`, `add_comment()` 등 인터페이스 제공. **향후 DB 마이그레이션 시 이 파일만 교체**.
- **core/index.py**: 항목 단건 변경 시 `index.json`을 동기 갱신. 리스트 페이지가 N개의 meta.json을 매번 파싱하지 않도록 캐시 역할.
- **core/locking.py**: `FileLock` 컨텍스트 매니저 + `atomic_write_json()` 함수.
- **core/workflow.py**: 현재 상태 + 사용자 역할 → 가능한 다음 상태 목록 반환. 잘못된 전이는 예외 발생.
- **core/logger.py**: `audit_log(actor, action, item_id, detail)` JSONL append.

## 1.4 핵심 의존성 (`requirements.txt` 초안)

```
streamlit>=1.39,<2.0
pydantic>=2.7,<3.0
Pillow>=10.4
filelock>=3.15
python-dotenv>=1.0
pandas>=2.2          # 대시보드 필터/정렬
streamlit-autorefresh>=1.0  # 옵션
```

## 1.5 다중 사용자 동시 접속 — Race Condition 대응

Streamlit은 세션마다 별도 스레드에서 스크립트를 재실행함. 같은 공용 PC에서 띄운 단일 인스턴스에 여러 브라우저(=여러 사용자)가 붙으면 동일 프로세스 내 다중 스레드. 만약 다른 PC에서 같은 인스턴스를 띄우면 별도 프로세스. 두 경우 모두 안전하게 처리하려면 **OS 레벨 파일 잠금**이 필요.

### 잠금 단위
- **항목별 잠금**: `data/.locks/{item_id}.lock` — 같은 항목의 코멘트 동시 작성 시
- **인덱스 잠금**: `data/.locks/index.lock` — index.json 갱신 시
- **글로벌 잠금**: `data/.locks/global.lock` — 백업 등 전체 일관성 필요할 때만

### Atomic Write 패턴

```python
from filelock import FileLock
from pathlib import Path
import json, os, tempfile

def atomic_write_json(path: Path, data: dict, *, timeout: float = 5.0):
    lock_path = path.with_suffix(path.suffix + ".lock")
    with FileLock(str(lock_path), timeout=timeout):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8",
            dir=str(path.parent), delete=False, suffix=".tmp"
        )
        try:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, path)  # POSIX/Windows 모두 원자적
        except Exception:
            tmp.close()
            try: os.unlink(tmp.name)
            except OSError: pass
            raise
```

### 코멘트는 append-only JSONL
코멘트마다 meta.json 전체를 다시 쓰면 충돌 가능성이 높아짐. `comments.jsonl`에 한 줄씩 append하면 OS의 append 원자성을 활용해 잠금 비용을 낮출 수 있음. (단, 한 줄이 PIPE_BUF=4096 바이트 이내일 때만 보장 — 코멘트가 길면 그래도 lock 사용 권장.)

## 1.6 향후 DB 마이그레이션 경로

`core/repository.py`를 인터페이스화 해두면 SQLite/PostgreSQL로 무중단 전환 가능:

```python
# core/repository.py - 추상 인터페이스
class IssueRepository(Protocol):
    def list_issues(self, *, status: str | None = None,
                          urgency: str | None = None) -> list[Issue]: ...
    def get_issue(self, id: str) -> Issue: ...
    def create_issue(self, issue: Issue) -> str: ...
    def update_status(self, id: str, new_status: str, actor: str) -> None: ...
    def add_comment(self, id: str, comment: Comment) -> None: ...

# 현재: FileRepository 구현
# 향후: SqliteRepository 구현 + 마이그레이션 스크립트로 data/items/* INSERT
```

마이그레이션 시점에 `data/items/` 전체를 순회하며 INSERT만 하면 끝. UI 코드는 변경 없음.
