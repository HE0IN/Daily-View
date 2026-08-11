"""core/llm.py — 설정/호출/다이제스트/질문 조립 테스트 (네트워크 없음)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import llm, repository
from core.models import Role, Status


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("LLM_API_URL", "LLM_API_KEY", "API_URL", "API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    assert llm.is_configured() is False

    monkeypatch.setenv("LLM_API_URL", "http://x/v1/chat/completions")
    assert llm.is_configured() is False  # key 없음
    monkeypatch.setenv("LLM_API_KEY", "k")
    assert llm.is_configured() is True

    # C-DEP 식 변수명(API_URL/API_KEY) fallback 도 동작
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_URL", "http://y")
    monkeypatch.setenv("API_KEY", "k2")
    assert llm.is_configured() is True


def test_call_llm_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    with pytest.raises(llm.LLMError):
        llm.call_llm([{"role": "user", "content": "hi"}])


class _FakeResp:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_call_llm_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_URL", "http://fake/v1/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "k")

    captured: dict = {}

    def _fake_post(url, json=None, headers=None, proxies=None, timeout=None):
        captured.update(url=url, payload=json, headers=headers)
        return _FakeResp(
            200, {"choices": [{"message": {"content": "  답변입니다  "}}]}
        )

    monkeypatch.setattr(llm.requests, "post", _fake_post)
    out = llm.call_llm([{"role": "user", "content": "질문"}])
    assert out == "답변입니다"  # strip 확인
    assert captured["payload"]["stream"] is False
    assert captured["headers"]["Authorization"] == "Bearer k"

    # HTTP 오류 → LLMError
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **kw: _FakeResp(500, text="boom")
    )
    with pytest.raises(llm.LLMError):
        llm.call_llm([{"role": "user", "content": "질문"}])


def test_call_llm_reasoning_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """추론 모델 대응 — <think> 제거, reasoning 폴백, 빈 응답은 명확한 에러."""
    monkeypatch.setenv("LLM_API_URL", "http://fake/v1/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "k")

    # <think>...</think> 블록은 제거하고 최종답만
    monkeypatch.setattr(
        llm.requests, "post",
        lambda *a, **kw: _FakeResp(
            200, {"choices": [{"message": {"content": "<think>고민중</think>\n최종답"}}]}
        ),
    )
    assert llm.call_llm([{"role": "user", "content": "q"}]) == "최종답"

    # content 가 비면 reasoning_content 로 폴백
    monkeypatch.setattr(
        llm.requests, "post",
        lambda *a, **kw: _FakeResp(
            200, {"choices": [{"message": {"content": "", "reasoning_content": "이유"}}]}
        ),
    )
    assert llm.call_llm([{"role": "user", "content": "q"}]) == "이유"

    # 완전 빈 응답 + finish_reason=length → 조용한 blank 대신 명확한 LLMError
    monkeypatch.setattr(
        llm.requests, "post",
        lambda *a, **kw: _FakeResp(
            200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        ),
    )
    _dbg: dict = {}
    with pytest.raises(llm.LLMError, match="max_tokens"):
        llm.call_llm([{"role": "user", "content": "q"}], debug=_dbg)
    assert _dbg["finish_reason"] == "length"


# ---------------------------------------------------------------------------
# 다이제스트
# ---------------------------------------------------------------------------


def test_build_project_digest(
    temp_data_dir: Path, sample_issue_kwargs: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    kw = dict(sample_issue_kwargs)
    kw["project"] = "P1"

    # 개발 진행 1건 (+사람 코멘트), 확인대기 1건, Temp 1건, 완료 1건, 보관 1건
    dev = repository.create_issue(**{**kw, "title": "개발중인 항목", "assignee": "담당"})
    repository.add_comment(dev.id, "담당", Role.developer, "진행 상황 코멘트")

    repository.create_issue(
        **{**kw, "title": "확인대기 항목", "kind": "unimplemented", "assignee": None}
    )
    t = repository.create_issue(
        **{**kw, "title": "confirm전 항목", "kind": "unimplemented", "assignee": None}
    )
    repository.promote_to_criteria(t.id, actor="등록")  # → Temp

    done = repository.create_issue(**{**kw, "title": "끝난 항목", "assignee": "담당"})
    for s in (
        Status.assignee_reviewing,
        Status.assignee_reviewed,
        Status.author_request,
    ):
        repository.update_status(done.id, s, actor="담당", actor_role=Role.developer)
    repository.update_status(
        done.id, Status.author_reviewing, actor="tester", actor_role=Role.reviewer
    )
    repository.update_status(
        done.id, Status.closed, actor="tester", actor_role=Role.reviewer
    )

    arch = repository.create_issue(**{**kw, "title": "삭제된 항목"})
    repository.delete_issue(arch.id, actor="등록")

    digest = llm.build_project_digest("P1")

    assert "프로젝트: P1" in digest
    assert "개발중인 항목" in digest
    assert "확인대기 항목" in digest
    assert "confirm전 항목" in digest  # Temp 섹션
    assert "완료: 1건" in digest
    assert "삭제된 항목" not in digest  # 삭제 표시 항목 제외
    assert "진행 상황 코멘트" in digest  # 최근 코멘트 포함
    assert "확인대기(확인요청목록): 1건" in digest
    assert "Temp(확정 보류): 1건" in digest


def test_ask_composes_messages(
    temp_data_dir: Path, sample_issue_kwargs: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ask() 가 [system(다이제스트 포함), (이력), user(질문)] 순으로 조립하는지."""
    repository.create_issue(**dict(sample_issue_kwargs))

    seen: dict = {}

    def _fake_call(messages, **kw):
        seen["messages"] = messages
        return "OK"

    monkeypatch.setattr(llm, "call_llm", _fake_call)
    out = llm.ask(
        "확인대기 몇 건이야?",
        project=None,
        history=[
            {"role": "user", "content": "이전 질문"},
            {"role": "assistant", "content": "이전 답"},
        ],
    )
    assert out == "OK"
    msgs = seen["messages"]
    assert msgs[0]["role"] == "system"
    assert "<현황데이터>" in msgs[0]["content"]  # 인젝션 방지용 펜스 마커
    assert msgs[1] == {"role": "user", "content": "이전 질문"}
    assert msgs[2] == {"role": "assistant", "content": "이전 답"}
    assert msgs[-1] == {"role": "user", "content": "확인대기 몇 건이야?"}
