import logging

from app.config import settings
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.models.schemas import ChatwootWebhookPayload
from app.services.chatwoot_client import build_history, chatwoot_client
from app.services.llm_client import get_ai_response
from app.services.verify import verify_webhook_signature
from app.services.handoff_connection import should_handoff as should_handoff_connection
from app.services.handoff_security import should_handoff as should_handoff_security

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post(
    "/chatwoot",
    status_code=status.HTTP_200_OK,
    summary="Chatwoot Agent Bot 웹훅 수신",
)
async def chatwoot_webhook(
    request: Request,
    payload: ChatwootWebhookPayload,
    x_chatwoot_signature: str = Header(default=""),
    x_chatwoot_timestamp: str = Header(default=""),
):
    # ── 1. 서명 검증 ──────────────────────────────────────────────────────────
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, x_chatwoot_signature, x_chatwoot_timestamp):
        logger.warning("웹훅 서명 검증 실패")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    logger.info("웹훅 수신 | event=%s", payload.event)

    if payload.event != "message_created":
        logger.debug("이벤트 무시: %s", payload.event)
        return {"status": "ignored", "reason": "event not handled"}

    if payload.message_type != "incoming":
        return {"status": "ignored", "reason": "not an incoming message"}

    user_content = (payload.content or "").strip()
    if not user_content:
        return {"status": "ignored", "reason": "empty content"}

    account = payload.account or {}
    account_id: int | None = account.get("id")
    conversation = payload.conversation
    conversation_id: int | None = conversation.id if conversation else None

    if not account_id or not conversation_id:
        logger.error("account_id 또는 conversation_id 누락 | account=%s conversation=%s", account_id, conversation_id)
        return {"status": "ignored", "reason": "missing ids"}

    logger.info(
        "처리 시작 | account=%d conv=%d sender=%s msg=%s",
        account_id, conversation_id,
        payload.sender.name if payload.sender else "unknown",
        user_content[:80],
    )

    # ── 2. 이미 사람이 담당 중인지 체크 (핸드오프 체크보다 반드시 먼저) ────────
    if payload.conversation and payload.conversation.meta and payload.conversation.meta.assignee:
        logger.info("이미 사람 담당 중, AI 응답 생략 | conv=%d", conversation_id)
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        return {"status": "ignored", "reason": "already assigned to human"}

    # ── 3. 핸드오프 체크 ──────────────────────────────────────────────────────
    if should_handoff_connection(user_content) or should_handoff_security(user_content):
        logger.info("핸드오프 트리거 감지 | conv=%d", conversation_id)
        inbox_id = payload.inbox.get("id") if payload.inbox else None
        online_agents = chatwoot_client.get_online_agents(account_id, inbox_id) if inbox_id else []

        if online_agents:
            chosen_agent = online_agents[0]
            chatwoot_client.assign_to_agent(account_id, conversation_id, assignee_id=chosen_agent["id"])
            logger.info("온라인 상담원 배정 | agent_id=%s name=%s", chosen_agent["id"], chosen_agent.get("name"))
        else:
            chatwoot_client.assign_to_agent(account_id, conversation_id, assignee_id=settings.default_agent_id)
            logger.warning("온라인 상담원 없음, 기본 상담원(%s)으로 폴백", settings.default_agent_id)

        chatwoot_client.send_message(
            account_id, conversation_id,
            "상담원을 연결해드릴게요. 잠시만 기다려주세요."
        )
        return {"status": "ok", "action": "handoff"}

    # ── 4. 대화 이력 조회 (실패해도 응답은 계속 — 빈 history로 폴백) ──────────
    try:
        messages = chatwoot_client.get_messages(account_id, conversation_id)
        history = build_history(messages, exclude_message_id=payload.id)
    except Exception as exc:
        logger.warning("대화 이력 조회 실패, 빈 history로 진행: %s", exc)
        history = []

    # ── 5. AI 응답 생성 (llm_client.py 인터페이스 호출) ───────────────────────
    try:
        reply = await get_ai_response(
            message=user_content,
            conversation_id=conversation_id,
            history=history,
        )
    except Exception as exc:
        logger.exception("AI 응답 생성 실패: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI service error") from exc

    # ── 6. Chatwoot에 응답 전송 ───────────────────────────────────────────────
    try:
        chatwoot_client.send_message(account_id=account_id, conversation_id=conversation_id, content=reply)
        logger.info("응답 전송 완료 | conv=%d reply=%s", conversation_id, reply[:80])
    except Exception as exc:
        logger.exception("Chatwoot 메시지 전송 실패: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Chatwoot API error") from exc

    return {"status": "ok"}
