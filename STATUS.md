# Status

> PC 간 작업 상태 동기화 파일.
> 작업 끝낼 때 `/wrapup` 입력하면 자동 갱신됨.
> 작업 시작할 때 SessionStart hook 이 이 내용을 자동으로 보여줌.

## 마지막 작업
2026-05-05 — M0~M3 본 구현 완료 (코어 데이터 계층 + UI 5페이지 + 운영 스크립트).
pytest 75/75 통과. 운영 시작 가능 상태.

산출물:
- `scripts/run.bat`, `scripts/backup.bat` — 시작/일일 백업
- `scripts/seed_dummy.py`, `scripts/rebuild_index.py`, `scripts/perf_check.py` — 성능/복구 CLI
- `RUNBOOK.md` — 운영자 단일 매뉴얼 (NSSM, 방화벽, 백업, 트러블슈팅)
- `app.py`, `pages/1_요청목록.py` — 30초 자동 새로고침 (graceful degradation)
- `app.py` 부트스트랩 — 디렉토리 실패 시 st.error+stop, 인덱스 점검 실패 시 강제 rebuild fallback

## 진행 중 (WIP)
- 없음

## 다음에 할 것
- 사내 공용 PC 에 배포 (RUNBOOK.md 의 NSSM 등록 절차 따라)
- 검토자 1명 + 개발자 1명이 각자 PC 에서 1주 실사용 후 피드백 수집
- 필요 시 M4 (통계 고도화, 스마트 필터 칩, 자동 아카이브 강화 등)
