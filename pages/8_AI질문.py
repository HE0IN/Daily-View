"""AI 질문 — 사내 LLM 에게 프로젝트 현황을 물어보는 채팅 화면.

질문 시점의 현황(개발 단계별/확인대기/Temp/최근 코멘트)을 다이제스트로 만들어
시스템 프롬프트에 싣고, 사내 LLM(OpenAI 호환)에 물어본다. 데이터는 현재
프로젝트 범위, 삭제 항목 제외. 설정(.env: LLM_API_URL/LLM_API_KEY)이 없으면
안내만 표시한다.
"""

from __future__ import annotations

import streamlit as st

from core import llm as llm_mod

user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

# 비(非)상세 페이지 진입 = 상세보기 편집모드 정리 (stale 방지).
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

if current_project:
    st.caption(f"{current_project} / AI 질문")

_hd1, _hd2 = st.columns([4, 1], vertical_alignment="bottom")
with _hd1:
    st.title("AI 질문")
with _hd2:
    if st.button("🧹 대화 초기화", key="ai_reset", width="stretch"):
        st.session_state.pop(f"_ai_chat_{current_project or '(전체)'}", None)
        st.rerun()

st.caption(
    "현재 프로젝트 현황(개발 단계 · 확인대기 · Temp · 최근 코멘트)에 대해 물어보세요. "
    "질문 시점의 데이터 스냅샷으로 답하며, 삭제 표시된 항목은 제외됩니다."
)

if not llm_mod.is_configured():
    st.info(
        "LLM 설정이 없습니다. 프로젝트 루트의 **`.env`** 파일에 아래를 추가한 뒤 "
        "앱을 재시작해주세요 (C-DEP 과 같은 값 사용 가능):\n\n"
        "```\nLLM_API_URL=http://…/v1/chat/completions\nLLM_API_KEY=발급받은-키\n"
        "# 선택: LLM_MODEL=google/gemma-4-31b-it\n```"
    )
    st.stop()

# ---------------------------------------------------------------------------
# 대화 이력 (프로젝트별 분리)
# ---------------------------------------------------------------------------

_chat_key = f"_ai_chat_{current_project or '(전체)'}"
history: list[dict[str, str]] = st.session_state.setdefault(_chat_key, [])

for m in history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

question = st.chat_input(
    "예: 확인대기 몇 건이야? / Temp에 뭐 있어? / 개발사 회신 기다리는 항목은?"
)
if question:
    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("현황을 읽고 답변을 만드는 중…"):
            _dbg: dict = {}
            try:
                answer = llm_mod.ask(
                    question,
                    project=current_project,
                    history=history[:-1],
                    debug=_dbg,
                )
            except llm_mod.LLMError as exc:
                st.error(str(exc))
                history.pop()  # 실패한 질문은 이력에서 제거
            except Exception as exc:  # noqa: BLE001
                st.error(f"답변 생성 중 오류: {exc}")
                history.pop()
            else:
                st.markdown(answer)
                history.append({"role": "assistant", "content": answer})
            st.session_state["_ai_last_debug"] = _dbg

# 진단(디버그) — 답이 비거나 이상할 때 원인 파악용 (finish_reason·토큰 사용량 등).
_last_dbg = st.session_state.get("_ai_last_debug")
if _last_dbg:
    with st.expander("🔍 마지막 응답 진단", expanded=False):
        st.json(_last_dbg)
        if _last_dbg.get("finish_reason") == "length":
            st.warning(
                "응답이 max_tokens 한도에 걸렸습니다. `.env` 의 `LLM_MAX_TOKENS` 를 "
                "더 크게(예: 8192) 설정하고 앱을 재시작해보세요."
            )
