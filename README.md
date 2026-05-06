# Daily View

> **현재 상태**: M0~M3 완료, 운영 가능 (pytest 75/75 통과)

개발자와 검토자(QA/기획자)가 개발 요청 사항을 주고받기 위한 로컬 호스팅 웹앱.

기존에는 PPT 스크린샷 + 텍스트 코멘트로 관리했지만,
- 항목 정리가 어렵고
- 누가 뭘 처리 중인지 한눈에 파악하기 힘들고
- 긴급도/상태 필터링이 안 되는

문제가 있어 웹앱으로 전환.

## 구성

- **프레임워크**: Python 3.12.7 + Streamlit
- **저장소**: 로컬 폴더 (DB 없음 — JSON + 이미지 파일)
- **호스팅**: 공용 PC 에서 `0.0.0.0:8501` 로 띄워 사내 네트워크 접속
- **사용자 식별**: 로그인 없이 사이드바에서 이름 + 역할(검토자/개발자) 선택
- **동시성**: `filelock` 기반 파일락 + `os.replace` 원자적 쓰기
- **자동 새로고침**: 30 초 간격 (`streamlit-autorefresh`)

## 기능 요약

- 검토자: 스크린샷 + 설명 + 긴급도(상/중/하) 로 새 요청 등록
- 개발자: 요청 보고 상태 변경(확인중/완료/API대기) 및 코멘트
- 검토자: 개발자 답변 후 동작 확인 → "검토완료" 처리
- 대시보드: 긴급도/상태별 카운트, 내 담당 큐 즉시 확인
- 통계 페이지: 분포/트렌드 차트, SLA 위반, 평균 처리 시간
- 모든 변경 이력 audit log 보존

## 빠른 시작

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

브라우저가 자동으로 `http://localhost:8501` 을 연다. 사이드바에서 이름·역할 입력.

자세한 설치/배포는 **[RUNBOOK.md](RUNBOOK.md)** 참고.

## 테스트

```bat
.venv\Scripts\activate
python -m pytest tests/ -v
```

기대 결과: `75 passed`. 카테고리:

- `test_repository.py` — CRUD/상태 전이/이미지/아카이브 (21건)
- `test_locking.py` — 동시 쓰기/락 잔존 (9건)
- `test_workflow.py` — 권한 매트릭스 (34건)
- `test_images.py` — 슬러그/썸네일/한도 (11건)

## 운영 / 호스팅

운영자가 첫 배포 시 따라야 할 모든 명령어와 트러블슈팅은 단일 문서에 정리:

[**RUNBOOK.md**](RUNBOOK.md) — 첫 설치 / NSSM 서비스 등록 / 일일 백업 스케줄 /
업그레이드 절차 / 검증 체크리스트 / 트러블슈팅

## 운영 스크립트 (`scripts/`)

| 스크립트 | 용도 |
|---|---|
| `run.bat` | Streamlit 시작 (NSSM 또는 더블클릭) |
| `backup.bat` | 일일 백업 (작업 스케줄러용, 14일 보관) |
| `seed_dummy.py` | 성능/한글 검증용 더미 데이터 (`--count N`) |
| `rebuild_index.py` | 인덱스 손상 시 강제 재구축 |
| `perf_check.py` | `list_issues` 응답 시간 측정 (1초 이내 SLA) |

## 설계 문서

설계 배경/스키마는 [`docs/`](docs/) 에 있다 (운영자는 RUNBOOK 만 읽으면 충분).

| # | 문서 | 내용 |
|---|---|---|
| 01 | [아키텍처](docs/01_architecture.md) | 폴더 구조, 의존성, 모듈 분할, 동시성 전략 |
| 02 | [저장소 설계](docs/02_storage.md) | JSON 스키마, 인덱스, 백업 |
| 03 | [UI/UX 설계](docs/03_ui_design.md) | 페이지 구성, 와이어프레임 |
| 04 | [워크플로우](docs/04_workflow.md) | 상태 다이어그램, 권한, SLA, 알림 |
| 05 | [설치 및 실행](docs/05_setup.md) | 원본 설치 가이드 (RUNBOOK 의 모태) |
| 06 | [구현 계획](docs/06_implementation_plan.md) | 마일스톤 (M0~M5), 검증 체크리스트 |
| 07 | [시나리오](docs/07_scenarios.md) | 역할별 사용 시나리오 |

## 폴더 구조

```
Daily View\
├── app.py                # 대시보드 (진입점)
├── pages\                # 요청목록/등록/상세/통계
├── core\                 # 도메인 + 저장소 (단일 I/O 진입점)
├── ui\                   # 공용 UI (테마/카드/배지)
├── tests\                # pytest 75건
├── scripts\              # 운영 CLI (run/backup/seed/rebuild/perf)
├── data\                 # 런타임 데이터 (커밋 제외, 백업 대상)
├── docs\                 # 설계 문서
├── prototype\            # 구 프로토타입 (보존용 — 더 이상 동작 보장 안 함)
├── RUNBOOK.md            # 운영 매뉴얼
├── requirements.txt
└── .env.example
```

`prototype/` 디렉토리는 초기 UI 셸 검증용이며, 본 구현 (M0~M3) 과 코드 공유는
없다. 참고용으로만 보존.
