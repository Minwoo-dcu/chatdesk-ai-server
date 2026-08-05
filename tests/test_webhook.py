"""
Chatdesk AI Server — 웹훅 엔드포인트 테스트

실제 Chatwoot / Gemini API 없이 mock으로 전체 흐름을 검증합니다.
실행: pytest tests/ -v

구성:
  1. 공통 payload / 헬퍼 / fixture
  2. 기본 동작 (health check, 서명 검증, 이벤트 라우팅)
  3. 기능 테스트 (F-01, F-02, F-03, F-05 등에 대응)
  4. 에러/예외 테스트 (E-01 ~ E-10, 통합테스트케이스 문서 순서 기준)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import groq
from google import genai
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# 공통 payload (Chatwoot Agent Bot flat 구조)
# ---------------------------------------------------------------------------

INCOMING_PAYLOAD = {
    "event": "message_created",
    "id": 1,
    "content": "안녕하세요, 도움이 필요합니다.",
    "message_type": "incoming",
    "created_at": "2026-07-20T00:00:00.000Z",
    "sender": {"id": 10, "name": "홍길동"},
    "conversation": {"id": 42, "inbox_id": 1, "status": "open"},
    "account": {"id": 3, "name": "테스트"},
}

OUTGOING_PAYLOAD = {
    **INCOMING_PAYLOAD,
    "message_type": "outgoing",  # 봇 답장 — 무시해야 함
}

EMPTY_CONTENT_PAYLOAD = {
    **INCOMING_PAYLOAD,
    "content": "",
}

OTHER_EVENT_PAYLOAD = {
    "event": "conversation_created",
    "account": {"id": 3},
}

# webwidget: 첫 방문(current_conversation 없음) → 대화 생성 후 인사
WEBWIDGET_FIRST_OPEN_PAYLOAD = {
    "event": "webwidget_triggered",
    "account": {"id": 3},
    "inbox": {"id": 1},
    "source_id": "src-abc-123",
    "current_conversation": None,
}

# webwidget: 재오픈(current_conversation 존재)
WEBWIDGET_REOPEN_PAYLOAD = {
    "event": "webwidget_triggered",
    "account": {"id": 3},
    "inbox": {"id": 1},
    "source_id": "src-abc-123",
    "current_conversation": {"id": 42, "inbox_id": 1},
}

# 문의유형 버튼 선택 (실제 Chatwoot: input_select 클릭은 message_updated로 옴)
INQUIRY_SELECT_UPDATED_PAYLOAD = {
    "event": "message_updated",
    "id": 5,
    "message_type": "outgoing",
    "content": "안녕하세요, 나노아이티 AI 상담원입니다. 어떤 도움이 필요하신가요?",
    "content_attributes": {
        "items": [{"title": "환불·교환", "value": "환불·교환"}],
        "submitted_values": [{"title": "환불·교환", "value": "환불·교환"}],
    },
    "conversation": {"id": 42, "inbox_id": 1, "status": "open"},
    "account": {"id": 3, "name": "테스트"},
}

# 문의유형을 자유 텍스트로 입력한 경우(message_created) — 프리픽스 컨텍스트 검증용
INQUIRY_SELECT_PAYLOAD = {
    **INCOMING_PAYLOAD,
    "id": 2,
    "content": "환불·교환",
}

# E-03: 웹훅 payload 필드 누락
NO_ACCOUNT_PAYLOAD = {
    "event": "message_created",
    "id": 1,
    "content": "테스트 메시지",
    "message_type": "incoming",
    "conversation": {"id": 42, "inbox_id": 1, "status": "open"},
}

NO_CONVERSATION_PAYLOAD = {
    "event": "message_created",
    "id": 1,
    "content": "테스트 메시지",
    "message_type": "incoming",
    "account": {"id": 3, "name": "테스트"},
}

BOTH_MISSING_PAYLOAD = {
    "event": "message_created",
    "id": 1,
    "content": "테스트 메시지",
    "message_type": "incoming",
}

# ---------------------------------------------------------------------------
# 헬퍼 / fixture
# ---------------------------------------------------------------------------

def post_webhook(payload: dict) -> "Response":
    return client.post("/webhook/chatwoot", json=payload)


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    """인메모리 상태를 테스트마다 초기화 (테스트 간 오염 방지)"""
    from app.services import conversation_state
    conversation_state._greeted.clear()
    conversation_state._inquiry_type.clear()
    conversation_state._selection_handled.clear()
    yield
    conversation_state._greeted.clear()
    conversation_state._inquiry_type.clear()
    conversation_state._selection_handled.clear()


# ===========================================================================
# 2. 기본 동작 (health check / 서명 검증 / 이벤트 라우팅)
# ===========================================================================

def test_health_check():
    """GET / — 서버 상태 확인"""
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@patch("app.routers.webhook.verify_webhook_signature", return_value=False)
def test_invalid_signature_returns_401(mock_verify):
    """서명 검증 실패 시 401 반환"""
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid webhook signature"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_non_message_created_event_is_ignored(mock_verify):
    """message_created 이외 이벤트는 무시 (200 + ignored)"""
    res = post_webhook(OTHER_EVENT_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# ===========================================================================
# 3. 기능 테스트 (F-01, F-02, F-03/F-04, F-10 관련)
# ===========================================================================

@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_webwidget_first_open_sends_greeting(mock_chatwoot, mock_verify):
    """[F-01] 위젯 첫 오픈(current_conversation=null) → 대화 생성 + 인사/문의유형 버튼 전송"""
    mock_chatwoot.create_conversation.return_value = {"id": 77}

    res = post_webhook(WEBWIDGET_FIRST_OPEN_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "action": "greeting_sent"}

    mock_chatwoot.create_conversation.assert_called_once_with(3, "src-abc-123", 1)
    _, kwargs = mock_chatwoot.send_message.call_args
    assert kwargs["account_id"] == 3
    assert kwargs["conversation_id"] == 77
    assert kwargs["content_type"] == "input_select"
    assert "items" in kwargs["content_attributes"]


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_webwidget_reopen_no_duplicate_greeting(mock_chatwoot, mock_verify):
    """[F-02] 위젯 재오픈 → 이미 인사 보냈으면 재전송 안 함"""
    res1 = post_webhook(WEBWIDGET_REOPEN_PAYLOAD)
    assert res1.json() == {"status": "ok", "action": "greeting_sent"}
    assert mock_chatwoot.send_message.call_count == 1
    mock_chatwoot.create_conversation.assert_not_called()

    res2 = post_webhook(WEBWIDGET_REOPEN_PAYLOAD)
    assert res2.json()["status"] == "ignored"
    assert res2.json()["reason"] == "already greeted"
    assert mock_chatwoot.send_message.call_count == 1


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="환불 안내드릴게요.")
@patch("app.routers.webhook.chatwoot_client")
def test_inquiry_type_selection_goes_to_llm(mock_chatwoot, mock_llm, mock_verify):
    """[F-04] 문의유형 버튼 클릭(자유 텍스트) → 선택값 저장 + LLM 파이프라인 전달"""
    mock_chatwoot.get_messages.return_value = []

    res = post_webhook(INQUIRY_SELECT_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    _, kwargs = mock_llm.call_args
    assert kwargs["message"] == "[문의유형: 환불·교환] 환불·교환"
    assert kwargs["conversation_id"] == 42


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="환불 안내드릴게요.")
@patch("app.routers.webhook.chatwoot_client")
def test_input_select_click_triggers_ai_response(mock_chatwoot, mock_llm, mock_verify):
    """[F-03] input_select 버튼 클릭(message_updated + submitted_values) → 바로 AI 응답 전송"""
    mock_chatwoot.get_messages.return_value = []

    res = post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "action": "inquiry_selection_answered"}
    _, kwargs = mock_llm.call_args
    assert "환불·교환" in kwargs["message"]
    assert kwargs["conversation_id"] == 42
    mock_chatwoot.send_message.assert_called_once_with(
        account_id=3, conversation_id=42, content="환불 안내드릴게요."
    )


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_message_updated_without_submitted_values_ignored(mock_verify):
    """[F-03 보조] 선택 이전의 message_updated(submitted_values 없음)는 무시"""
    payload = {
        "event": "message_updated",
        "id": 5,
        "message_type": "outgoing",
        "content": "인사",
        "content_attributes": {"items": [{"title": "제품 문의", "value": "제품 문의"}]},
        "conversation": {"id": 42, "inbox_id": 1},
        "account": {"id": 3},
    }
    res = post_webhook(payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_inquiry_context_prefixed_to_llm(mock_chatwoot, mock_llm, mock_verify):
    """[F-04 보조] 유형 선택 후 자유 텍스트 → [문의유형: ...] 프리픽스 포함 확인"""
    mock_chatwoot.get_messages.return_value = []

    post_webhook(INQUIRY_SELECT_PAYLOAD)
    followup = {**INCOMING_PAYLOAD, "id": 3, "content": "제 성함은 홍길동입니다."}
    post_webhook(followup)

    _, kwargs = mock_llm.call_args
    assert kwargs["message"] == "[문의유형: 환불·교환] 제 성함은 홍길동입니다."


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="안녕하세요! 무엇을 도와드릴까요?")
@patch("app.routers.webhook.chatwoot_client")
def test_incoming_message_triggers_full_pipeline(mock_chatwoot, mock_llm, mock_verify):
    """[정상 파이프라인] 일반 incoming 메시지 → AI 호출 → Chatwoot 전송까지 전체 검증"""
    mock_chatwoot.send_message.return_value = {"id": 99}
    mock_chatwoot.get_messages.return_value = [
        {"id": 100, "content": "이전 질문입니다.", "message_type": 0, "private": False},
        {"id": 101, "content": "이전 답변입니다.", "message_type": 1, "private": False},
        {"id": 1, "content": "안녕하세요, 도움이 필요합니다.", "message_type": 0, "private": False},
    ]

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    mock_chatwoot.get_messages.assert_called_once_with(3, 42)
    mock_llm.assert_called_once_with(
        message="안녕하세요, 도움이 필요합니다.",
        conversation_id=42,
        history=[
            {"role": "user", "content": "이전 질문입니다."},
            {"role": "assistant", "content": "이전 답변입니다."},
        ],
    )
    mock_chatwoot.send_message.assert_called_once_with(
        account_id=3,
        conversation_id=42,
        content="안녕하세요! 무엇을 도와드릴까요?",
    )


# ===========================================================================
# 4. 에러/예외 테스트 (E-01 ~ E-10, 문서 순서 기준)
# ===========================================================================

@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, side_effect=Exception("LLM 오류"))
@patch("app.routers.webhook.chatwoot_client")
def test_llm_failure_triggers_handoff(mock_chatwoot, mock_llm, mock_verify):
    """[E-01] LLM 호출 실패(일반 예외) → 웹훅 200 즉시 반환, 실제 안내/핸드오프는 백그라운드"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.get_online_agents.return_value = [{"id": 1, "name": "agent"}]
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 200


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_400_bad_request_error_logging(mock_chatwoot, mock_verify, caplog):
    """[E-01 보조] 400 Bad Request 에러가 구분되게 로깅되는지 확인 (google-genai)"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.get_online_agents.return_value = [{"id": 1, "name": "agent"}]
    error = genai.errors.ClientError(code=400, response_json={"error": "bad request"})
    with patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, side_effect=error):
        res = post_webhook(INCOMING_PAYLOAD)
        assert res.status_code == 200
        assert "400 Bad Request" in caplog.text


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_429_rate_limit_error_logging(mock_chatwoot, mock_verify, caplog):
    """[E-01 보조] 429 Rate Limit 에러가 구분되게 로깅되는지 확인 (groq)"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.get_online_agents.return_value = [{"id": 1, "name": "agent"}]
    response = MagicMock()
    response.status_code = 429
    error = groq.RateLimitError("rate limit exceeded", response=response, body=None)
    with patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, side_effect=error):
        res = post_webhook(INCOMING_PAYLOAD)
        assert res.status_code == 200
        assert "429 Rate Limit" in caplog.text


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_chatwoot_send_failure_with_agent_available(mock_chatwoot, mock_llm, mock_verify):
    """[E-02, 온라인 상담원 있는 분기] Chatwoot 전송 실패 → 200 반환 + 백그라운드 핸드오프 시도
    (참고: 아래 no_agent 버전과 세트 — assign_or_queue의 두 분기를 각각 커버)
    """
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.send_message.side_effect = Exception("Chatwoot 오류")
    mock_chatwoot.get_online_agents.return_value = [{"id": 1, "name": "agent"}]
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 200


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="안녕하세요! 무엇을 도와드릴까요?")
@patch("app.routers.webhook.chatwoot_client")
def test_chatwoot_send_failure_no_agent_available(mock_chatwoot, mock_llm, mock_verify):
    """[E-02, 온라인 상담원 없는 분기] 예외 흡수 + handoff_triggered 상태 전환까지 검증"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.get_online_agents.return_value = []
    mock_chatwoot.send_message.side_effect = Exception("Chatwoot API 502")

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert mock_chatwoot.send_message.call_count >= 1

    from app.services import conversation_state
    assert conversation_state.has_handoff_triggered(42) is True


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_missing_account_id_is_ignored(mock_verify):
    """[E-03] account_id 누락 시 무시 (200 + ignored, reason=missing ids)"""
    res = post_webhook(NO_ACCOUNT_PAYLOAD)
    assert res.status_code == 200
    assert res.json() == {"status": "ignored", "reason": "missing ids"}


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_missing_conversation_id_is_ignored(mock_verify):
    """[E-03] conversation_id 누락 시 무시"""
    res = post_webhook(NO_CONVERSATION_PAYLOAD)
    assert res.status_code == 200
    assert res.json() == {"status": "ignored", "reason": "missing ids"}


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_missing_both_ids_is_ignored(mock_verify):
    """[E-03] account_id, conversation_id 둘 다 누락 시 무시"""
    res = post_webhook(BOTH_MISSING_PAYLOAD)
    assert res.status_code == 200
    assert res.json() == {"status": "ignored", "reason": "missing ids"}


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_empty_content_is_ignored(mock_verify):
    """[E-04] content가 빈 문자열인 경우 무시"""
    res = post_webhook(EMPTY_CONTENT_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert res.json()["reason"] == "empty content"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_outgoing_message_is_ignored(mock_verify):
    """[E-05] 봇/상담사 발신 메시지(outgoing)는 무시 — 무한루프 방지"""
    res = post_webhook(OUTGOING_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert res.json()["reason"] == "not an incoming message"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.evaluate", side_effect=Exception("판단 로직 오류"))
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="안녕하세요! 무엇을 도와드릴까요?")
@patch("app.routers.webhook.chatwoot_client")
def test_evaluate_failure_falls_back_to_no_match(mock_chatwoot, mock_llm, mock_evaluate, mock_verify):
    """[E-06] evaluate() 자체 오류 - 예외를 던져도 매칭 없음으로 처리되어 정상 파이프라인 진행"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.send_message.return_value = {"id": 99}

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # evaluate가 실제로 호출됐고(예외를 던졌고) 서버는 안 죽었는지 확인
    mock_evaluate.assert_called_once()

    # 예외에도 불구하고 핸드오프 없이 정상적으로 RAG→LLM 파이프라인까지 이어졌는지 확인
    mock_llm.assert_called_once()
    mock_chatwoot.send_message.assert_called_once()

@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="안녕하세요! 무엇을 도와드릴까요?")
@patch("app.routers.webhook.chatwoot_client")
def test_get_messages_failure_falls_back_to_empty_history(mock_chatwoot, mock_llm, mock_verify):
    """[E-07] get_messages 실패 시 예외를 흡수하고 빈 history로 정상 진행"""
    mock_chatwoot.get_messages.side_effect = Exception("Chatwoot API timeout")
    mock_chatwoot.send_message.return_value = {"id": 99}

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    mock_llm.assert_called_once_with(
        message="안녕하세요, 도움이 필요합니다.",
        conversation_id=42,
        history=[],
    )
    mock_chatwoot.send_message.assert_called_once()


# [E-08] Gemini quota 초과 — pytest 대상 아님(실측)
# [E-09] knowledge_base 키워드 오탐 — pytest 대상 아님(수동 확인)


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_input_select_duplicate_update_no_double_response(mock_chatwoot, mock_llm, mock_verify):
    """[E-10] 중복 message_updated → AI 응답은 1회만"""
    mock_chatwoot.get_messages.return_value = []

    post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)
    post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)  # 중복

    assert mock_llm.call_count == 1
    assert mock_chatwoot.send_message.call_count == 1