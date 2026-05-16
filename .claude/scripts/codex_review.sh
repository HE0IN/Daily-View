#!/bin/bash
# codex_review.sh — OpenAI Codex CLI wrapper
# 목적: Claude Code 작업을 OpenAI Codex로 견제·검증 (이슈#13)
# 사용: bash .claude/scripts/codex_review.sh "<프롬프트>"
# 전제:
#   - OpenAI Codex CLI 설치 (`npm install -g @openai/codex` 또는 공식 방법)
#   - 환경변수 OPENAI_API_KEY 설정 (User 레벨)

set -e

PROMPT="${1:-}"
if [ -z "$PROMPT" ]; then
  echo "[codex_review] Usage: codex_review.sh '<프롬프트>'" >&2
  echo "[codex_review] 예: codex_review.sh 'core.md에 이 규칙 추가가 적절한가? <규칙 내용>'" >&2
  exit 1
fi

# Codex CLI 존재 확인
if ! command -v codex > /dev/null 2>&1; then
  echo "[codex_review] codex CLI not found." >&2
  echo "[codex_review] 설치: npm install -g @openai/codex (또는 OpenAI 공식 안내)" >&2
  echo "[codex_review] 설치 후 재시도 — 또는 사용자에게 견제 도구 미설치 알리기" >&2
  exit 2
fi

# 인증 방식 확인 (codex login: ChatGPT 계정 인증 또는 API key 둘 다 지원)
# 사용자(허영인) 선택: ChatGPT auth 방식 (2026-05-16). OPENAI_API_KEY 강제 체크 제거.
# 인증 실패 시 codex 자체가 안내 메시지 출력하므로 wrapper에서는 강제 차단 안 함.

# Codex 호출
# 모드 선택: 인자로 "review" 줄 수 있음 (코드 리뷰 전용 모드)
# 기본: exec (단발 응답, 비대화형)
MODE="${2:-exec}"

case "$MODE" in
  review)
    # 코드 리뷰 모드: 변경 diff 검토에 최적
    codex review "$PROMPT" 2>&1
    ;;
  exec|*)
    # 일반 단발 실행: 자유 질의
    codex exec "$PROMPT" 2>&1
    ;;
esac

# 종료 코드 보존
exit $?
