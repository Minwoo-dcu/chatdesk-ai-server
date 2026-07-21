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

WEBWIDGET_PAYLOAD = {
    "event": "webwidget_triggered",
    "account": {"id": 3},
}


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def post_webhook(payload: dict) -> "Response":
    return client.post("/webhook/chatwoot", json=payload)


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
def test_webwidget_triggered_is_ignored(mock_verify):
    """webwidget_triggered 이벤트는 무시"""
    res = post_webhook(WEBWIDGET_PAYLOAD)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


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

    res = post_webhook(INCOMING_PAYLOAD)

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # AI 응답 생성 호출 확인
    mock_llm.assert_called_once_with(
        message="안녕하세요, 도움이 필요합니다.",
        conversation_id=42,
        history=[],
    )

    # Chatwoot 전송 호출 확인
    mock_chatwoot.send_message.assert_called_once_with(
        account_id=3,
        conversation_id=42,
        content="안녕하세요! 무엇을 도와드릴까요?",
    )


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, side_effect=Exception("LLM 오류"))
def test_llm_failure_returns_502(mock_llm, mock_verify):
    """LLM 호출 실패 시 502 반환"""
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 502
    assert res.json()["detail"] == "AI service error"


@patch("app.routers.webhook.verify_webhook_signature", return_value=True)
@patch("app.routers.webhook.get_ai_response", new_callable=AsyncMock, return_value="답변")
@patch("app.routers.webhook.chatwoot_client")
def test_chatwoot_send_failure_returns_502(mock_chatwoot, mock_llm, mock_verify):
    """Chatwoot 전송 실패 시 502 반환"""
    mock_chatwoot.send_message.side_effect = Exception("Chatwoot 오류")
    res = post_webhook(INCOMING_PAYLOAD)
    assert res.status_code == 502
    assert res.json()["detail"] == "Chatwoot API error"
