# Daily View 작업 지침

전역 지침(데스크톱 `~/.codex/AGENTS.md`·`~/.claude/CLAUDE.md`)을 따르고, 여기엔 이 레포만의 것만 둔다.
`CLAUDE.md`는 `@AGENTS.md` 한 줄이다.

## 진입점
- 위키: [[Daily View]] (허영인/1. 프로젝트/Daily View/Daily View.md) — 일의 상태·결정·자료
- 코드 상태: `STATUS.md` · 실수 기록: `docs/MISTAKES.md`(없으면 만든다)
- 운영 절차: `RUNBOOK.md`

## 이 레포
- 개발자와 검토자(QA·기획)가 개발 요청을 주고받는 로컬 호스팅 웹앱. Python 3.12 + Streamlit, 저장소는 로컬 폴더(JSON + 이미지, DB 없음)
- 상태: M0~M3 완료·운영 가능. 남은 일: 공용 PC 배포(`0.0.0.0:8501`, 사내 네트워크)
- 원격 `HE0IN/Daily-View`. 내 레포 — `dev`에서 작업, PR로 main

## 명령
- 설치: `pip install -r requirements.txt`
- 실행: `streamlit run app.py --server.address 0.0.0.0 --server.port 8501`
- 테스트: `pytest` (pytest.ini)

## 규칙
- 사진 붙여넣기는 HTTP 환경 대응 코드를 유지한다(2026-08-21 수정)
- 데이터 폴더(`data/`)는 실제 요청이 들어 있으니 테스트에서 건드리지 않는다
