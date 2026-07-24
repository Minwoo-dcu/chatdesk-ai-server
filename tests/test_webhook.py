"""
Chatdesk AI Server — 웹훅 엔드포인트 테스트

실제 Chatwoot / Gemini API 없이 mock으로 전체 흐름을 검증합니다.
실행: pytest tests/ -v
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# 공통 페이로드 (Chatwoot Agent Bot flat 구조)
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


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


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


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_webwidget_first_open_sends_greeting(mock_chatwoot, mock_verify):
    """위젯 첫 오픈(current_conversation=null) → 대화 생성 + 인사/문의유형 버튼 전송"""
    mock_chatwoot.create_conversation.return_value = {"id": 77}

    res = post_webhook(WEBWIDGET_FIRST_OPEN_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "action": "greeting_sent"}

    mock_chatwoot.create_conversation.assert_called_once_with(3, "src-abc-123", 1)
    # 인사 + input_select 버튼 전송 확인
    _, kwargs = mock_chatwoot.send_message.call_args
    assert kwargs["account_id"] == 3
    assert kwargs["conversation_id"] == 77
    assert kwargs["content_type"] == "input_select"
    assert "items" in kwargs["content_attributes"]


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.chatwoot_client")
def test_webwidget_reopen_no_duplicate_greeting(mock_chatwoot, mock_verify):
    """위젯 재오픈 → 이미 인사 보냈으면 재전송 안 함"""
    # 1차: current_conversation 있음(id=42) → 인사 전송
    res1 = post_webhook(WEBWIDGET_REOPEN_PAYLOAD)
    assert res1.json() == {"status": "ok", "action": "greeting_sent"}
    assert mock_chatwoot.send_message.call_count == 1
    # create_conversation은 호출 안 됨 (이미 대화 존재)
    mock_chatwoot.create_conversation.assert_not_called()

    # 2차: 같은 대화 재오픈 → 인사 생략
    res2 = post_webhook(WEBWIDGET_REOPEN_PAYLOAD)
    assert res2.json()["status"] == "ignored"
    assert res2.json()["reason"] == "already greeted"
    assert mock_chatwoot.send_message.call_count == 1  # 증가 없음


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="환불 안내드릴게요.")
@patch("app.routers.webhook.chatwoot_client")
def test_inquiry_type_selection_goes_to_llm(mock_chatwoot, mock_llm, mock_verify):
    """문의유형 버튼 클릭 → 선택값 저장 + 바로 LLM 파이프라인으로 전달 (canned 응답 없음)"""
    mock_chatwoot.get_messages.return_value = []

    res = post_webhook(INQUIRY_SELECT_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    # 선택값이 LLM에 전달됨 (첫 선택이므로 프리픽스 붙어서 전달)
    _, kwargs = mock_llm.call_args
    assert kwargs["message"] == "[문의유형: 환불·교환] 환불·교환"
    assert kwargs["conversation_id"] == 42


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="환불 안내드릴게요.")
@patch("app.routers.webhook.chatwoot_client")
def test_input_select_click_triggers_ai_response(mock_chatwoot, mock_llm, mock_verify):
    """input_select 버튼 클릭(message_updated + submitted_values) → 바로 AI 응답 전송"""
    mock_chatwoot.get_messages.return_value = []

    res = post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "action": "inquiry_selection_answered"}
    # 선택값이 LLM에 전달됨
    _, kwargs = mock_llm.call_args
    assert "환불·교환" in kwargs["message"]
    assert kwargs["conversation_id"] == 42
    # AI 응답이 Chatwoot로 전송됨
    mock_chatwoot.send_message.assert_called_once_with(
        account_id=3, conversation_id=42, content="환불 안내드릴게요."
    )


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_input_select_duplicate_update_no_double_response(mock_chatwoot, mock_llm, mock_verify):
    """중복 message_updated → AI 응답은 1회만"""
    mock_chatwoot.get_messages.return_value = []

    post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)
    post_webhook(INQUIRY_SELECT_UPDATED_PAYLOAD)  # 중복

    assert mock_llm.call_count == 1
    assert mock_chatwoot.send_message.call_count == 1


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_message_updated_without_submitted_values_ignored(mock_verify):
    """선택 이전의 message_updated(submitted_values 없음)는 무시"""
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
    """유형 선택 후 자유 텍스트 → get_ai_response에 [문의유형: ...] 프리픽스 포함"""
    mock_chatwoot.get_messages.return_value = []

    # 1) 유형 선택
    post_webhook(INQUIRY_SELECT_PAYLOAD)
    # 2) 이후 자유 텍스트
    followup = {**INCOMING_PAYLOAD, "id": 3, "content": "주문번호는 12345입니다."}
    post_webhook(followup)

    _, kwargs = mock_llm.call_args
    assert kwargs["message"] == "[문의유형: 환불·교환] 주문번호는 12345입니다."


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_outgoing_message_is_ignored(mock_verify):
    """봇/상담사 발신 메시지(outgoing)는 무시 — 무한루프 방지"""
    res = post_webhook(OUTGOING_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert res.json()["reason"] == "not an incoming message"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
def test_empty_content_is_ignored(mock_verify):
    """content가 빈 문자열인 경우 무시"""
    res = post_webhook(EMPTY_CONTENT_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert res.json()["reason"] == "empty content"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="안녕하세요! 무엇을 도와드릴까요?")
@patch("app.routers.webhook.chatwoot_client")
def test_incoming_message_triggers_full_pipeline(mock_chatwoot, mock_llm, mock_verify):
    """
    정상 incoming 메시지 → AI 호출 → Chatwoot 전송까지 전체 파이프라인 검증
    """
    mock_chatwoot.send_message.return_value = {"id": 99}
    # 이력 조회: 이전 1턴 + 방금 수신한 현재 메시지(id=1, 중복 제외 대상)
    mock_chatwoot.get_messages.return_value = [
        {"id": 100, "content": "이전 질문입니다.", "message_type": 0, "private": False},
        {"id": 101, "content": "이전 답변입니다.", "message_type": 1, "private": False},
        {"id": 1, "content": "안녕하세요, 도움이 필요합니다.", "message_type": 0, "private": False},
    ]

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # 이력 조회 호출 확인
    mock_chatwoot.get_messages.assert_called_once_with(3, 42)

    # AI 응답 생성 호출 확인 — 현재 메시지(id=1)는 history에서 제외
    mock_llm.assert_called_once_with(
        message="안녕하세요, 도움이 필요합니다.",
        conversation_id=42,
        history=[
            {"role": "user", "content": "이전 질문입니다."},
            {"role": "assistant", "content": "이전 답변입니다."},
        ],
    )

    # Chatwoot 전송 호출 확인
    mock_chatwoot.send_message.assert_called_once_with(
        account_id=3,
        conversation_id=42,
        content="안녕하세요! 무엇을 도와드릴까요?",
    )


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, side_effect=Exception("LLM 오류"))
@patch("app.routers.webhook.chatwoot_client")
def test_llm_failure_returns_502(mock_chatwoot, mock_llm, mock_verify):
    """LLM 호출 실패 시 502 반환"""
    mock_chatwoot.get_messages.return_value = []
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 502
    assert res.json()["detail"] == "AI service error"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_chatwoot_send_failure_returns_502(mock_chatwoot, mock_llm, mock_verify):
    """Chatwoot 전송 실패 시 502 반환"""
    mock_chatwoot.get_messages.return_value = []
    mock_chatwoot.send_message.side_effect = Exception("Chatwoot 오류")
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 502
    assert res.json()["detail"] == "Chatwoot API error"
