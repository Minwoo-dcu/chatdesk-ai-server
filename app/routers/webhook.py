import logging

from app.config import settings
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.models.schemas import ChatwootWebhookPayload
from app.services.business_hours import is_within_business_hours
from app.services.chatwoot_client import build_history, chatwoot_client
from app.services.llm_client import get_ai_response
from app.services.verify import verify_webhook_signature
from app.services.handoff_complaint import should_handoff as should_handoff_complaint
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

    # ── 3. 인박스 정보 미리 조회 (영업시간 + 온라인 상담원 판단에 공용 사용) ───
    inbox_id = payload.inbox.get("id") if payload.inbox else None
    inbox_data = chatwoot_client.get_inbox(account_id, inbox_id) if inbox_id else {}

    # ── 4. 영업시간 외 체크 (핸드오프보다 먼저) ────────────────────────────────
    if not is_within_business_hours(inbox_data):
        chatwoot_client.add_labels(account_id, conversation_id, ["미배정"])
        chatwoot_client.send_message(
            account_id, conversation_id,
            "현재는 상담 운영 시간이 아닙니다. 남겨주신 문의는 다음 영업일에 확인 후 답변드리겠습니다."
        )
        logger.info("영업시간 외 접수 | conv=%d", conversation_id)
        return {"status": "ok", "action": "out_of_office"}

    # ── 5. 핸드오프 체크 ──────────────────────────────────────────────────────
    is_security_issue = should_handoff_security(user_content)
    is_complaint = should_handoff_complaint(user_content)
    if should_handoff_connection(user_content) or is_security_issue or is_complaint:
        logger.info("핸드오프 트리거 감지 | conv=%d", conversation_id)

        if is_security_issue:
            chatwoot_client.set_priority(account_id, conversation_id, priority="urgent")
            logger.info("보안·금전 이슈 감지 → 우선순위 urgent 설정 | conv=%d", conversation_id)
        if is_complaint:
            chatwoot_client.add_labels(account_id, conversation_id, ["컴플레인"])
            logger.info("컴플레인 감지 → 라벨 추가 | conv=%d", conversation_id)
            # TODO: 새 핸드오프 유형 추가시 여기 chatwoot_client.add_labels(...) 한 줄만 추가

        online_agents = chatwoot_client.get_online_agents(account_id, inbox_id) if inbox_id else []

        if online_agents:
            chosen_agent = online_agents[0]
            chatwoot_client.assign_to_agent(account_id, conversation_id, assignee_id=chosen_agent["id"])
            logger.info("온라인 상담원 배정 | agent_id=%s name=%s", chosen_agent["id"], chosen_agent.get("name"))
            chatwoot_client.send_message(
                account_id, conversation_id,
                "상담원과 연결되었습니다."
            )
            return {"status": "ok", "action": "handoff"}
        else:
            chatwoot_client.add_labels(account_id, conversation_id, ["미배정"])
            chatwoot_client.send_message(
                account_id, conversation_id,
                "현재 상담 가능한 상담원이 없어 순차적으로 연결해드리겠습니다."
            )
            logger.warning("온라인 상담원 없음, 미배정 상태로 접수 | conv=%d", conversation_id)
            return {"status": "ok", "action": "no_agent_available"}

    # ── 6. 대화 이력 조회 (실패해도 응답은 계속 — 빈 history로 폴백) ──────────
    try:
        messages = chatwoot_client.get_messages(account_id, conversation_id)
        history = build_history(messages, exclude_message_id=payload.id)
    except Exception as exc:
        logger.warning("대화 이력 조회 실패, 빈 history로 진행: %s", exc)
        history = []

    # ── 7. AI 응답 생성 (llm_client.py 인터페이스 호출) ───────────────────────
    try:
        reply = await get_ai_response(
            message=user_content,
            conversation_id=conversation_id,
            history=history,
        )
    except Exception as exc:
        logger.exception("AI 응답 생성 실패: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI service error") from exc

    # ── 8. Chatwoot에 응답 전송 ───────────────────────────────────────────────
    try:
        chatwoot_client.send_message(account_id=account_id, conversation_id=conversation_id, content=reply)
        logger.info("응답 전송 완료 | conv=%d reply=%s", conversation_id, reply[:80])
    except Exception as exc:
        logger.exception("Chatwoot 메시지 전송 실패: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Chatwoot API error") from exc

    return {"status": "ok"}
