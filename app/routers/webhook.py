import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.models.schemas import ChatwootWebhookPayload
from app.services.chatwoot_client import chatwoot_client
from app.services.llm_client import get_ai_response
from app.services.verify import verify_webhook_signature

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
):
    # ── 1. 서명 검증 ──────────────────────────────────────────────────────────
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, x_chatwoot_signature):
        logger.warning("웹훅 서명 검증 실패")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    logger.info("웹훅 수신 | event=%s", payload.event)

    # ── 2. message_created 이벤트만 처리 ─────────────────────────────────────
    if payload.event != "message_created":
        logger.debug("이벤트 무시: %s", payload.event)
        return {"status": "ignored", "reason": "event not handled"}

    message = payload.message
    if message is None or message.message_type != 0:  # 0 = incoming (고객 메시지)
        return {"status": "ignored", "reason": "not an incoming message"}

    user_content = (message.content or "").strip()
    if not user_content:
        return {"status": "ignored", "reason": "empty content"}

    # ── 3. 컨텍스트 추출 ──────────────────────────────────────────────────────
    account = payload.account or {}
    account_id: int | None = account.get("id")
    conversation = payload.conversation
    conversation_id: int | None = conversation.id if conversation else None

    if not account_id or not conversation_id:
        logger.error(
            "account_id 또는 conversation_id 누락 | account=%s conversation=%s",
            account_id,
            conversation_id,
        )
        return {"status": "ignored", "reason": "missing ids"}

    logger.info(
        "처리 시작 | account=%d conv=%d sender=%s msg=%s",
        account_id,
        conversation_id,
        message.sender.name if message.sender else "unknown",
        user_content[:80],
    )

    # ── 4. AI 응답 생성 (llm_client.py 인터페이스 호출) ───────────────────────
    try:
        reply = await get_ai_response(
            message=user_content,
            conversation_id=conversation_id,
            history=[],  # TODO: 대화 이력 조회 추가 예정
        )
    except Exception as exc:
        logger.exception("AI 응답 생성 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service error",
        ) from exc

    # ── 5. Chatwoot에 응답 전송 ───────────────────────────────────────────────
    try:
        chatwoot_client.send_message(
            account_id=account_id,
            conversation_id=conversation_id,
            content=reply,
        )
        logger.info("응답 전송 완료 | conv=%d reply=%s", conversation_id, reply[:80])
    except Exception as exc:
        logger.exception("Chatwoot 메시지 전송 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chatwoot API error",
        ) from exc

    return {"status": "ok"}
