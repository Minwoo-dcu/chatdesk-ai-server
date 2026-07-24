import logging

from app.config import settings
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.models.schemas import ChatwootWebhookPayload
from app.services import conversation_state
from app.services.business_hours import is_within_business_hours
from app.services.chatwoot_client import build_history, chatwoot_client
from app.services.handoff_rules import apply_actions, evaluate
from app.services.llm_client import get_ai_response
from app.services.prompts import GREETING_MESSAGE, INQUIRY_ITEMS, match_inquiry_value
from app.services.verify import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


class ReplyError(Exception):
    """AI 응답 생성/전송 단계 실패. detail로 원인을 구분해 호출자가 처리한다."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def generate_and_send_reply(
    account_id: int,
    conversation_id: int,
    llm_message: str,
    exclude_message_id: int | None = None,
) -> str:
    """대화 이력 조회 → get_ai_response → Chatwoot 전송. 응답 텍스트 반환.

    실패 시 ReplyError를 던지며, 호출자가 상황(502 raise / 200 return)에 맞게 처리한다.
    이력 조회 실패는 치명적이지 않으므로 빈 history로 진행한다.
    """
    try:
        messages = chatwoot_client.get_messages(account_id, conversation_id)
        history = build_history(messages, exclude_message_id=exclude_message_id)
    except Exception as exc:
        logger.warning("대화 이력 조회 실패, 빈 history로 진행: %s", exc)
        history = []

    try:
        reply = await get_ai_response(
            message=llm_message,
            conversation_id=conversation_id,
            history=history,
        )
    except Exception as exc:
        logger.exception("AI 응답 생성 실패: %s", exc)
        raise ReplyError("AI service error") from exc

    try:
        chatwoot_client.send_message(account_id=account_id, conversation_id=conversation_id, content=reply)
        logger.info("응답 전송 완료 | conv=%d reply=%s", conversation_id, reply[:80])
    except Exception as exc:
        logger.exception("Chatwoot 메시지 전송 실패: %s", exc)
        raise ReplyError("Chatwoot API error") from exc

    return reply


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
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, x_chatwoot_signature, x_chatwoot_timestamp):
        logger.warning("웹훅 서명 검증 실패")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    # 모든 이벤트에 대한 수신 로그는 노이즈가 크므로 DEBUG. 실제 처리 시점은 각 핸들러가 INFO로 남김.
    logger.debug("웹훅 수신 | event=%s", payload.event)

    if payload.event == "webwidget_triggered":
        return handle_webwidget_triggered(payload)

    # input_select 버튼 클릭은 새 메시지가 아니라 봇 메시지 업데이트(message_updated)로 오며,
    # 선택값은 content_attributes.submitted_values에 담겨 온다.
    if payload.event == "message_updated":
        return await handle_inquiry_selection(payload)

    if payload.event != "message_created":
        logger.debug("이벤트 무시 | event=%s", payload.event)
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

    # ── 문의유형 버튼 선택값 저장 (버튼 클릭도 incoming 메시지로 옴) ──────────────
    # 선택값을 저장만 하고 return하지 않음 → 아래 기존 흐름(핸드오프/LLM)으로 그대로 이어감.
    # 이후 get_ai_response 호출 시 message에 컨텍스트로 주입됨.
    inquiry_selection = match_inquiry_value(user_content)
    if inquiry_selection:
        conversation_state.set_inquiry_type(conversation_id, inquiry_selection)
        logger.info("문의유형 선택 저장 | conv=%d type=%s", conversation_id, inquiry_selection)

    # ── 이미 사람이 담당 중인지 체크 (핸드오프 체크보다 반드시 먼저) ──────────
    if payload.conversation and payload.conversation.meta and payload.conversation.meta.assignee:
        logger.info("이미 사람 담당 중, AI 응답 생략 | conv=%d", conversation_id)
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        return {"status": "ignored", "reason": "already assigned to human"}

    # ── 인박스 정보 미리 조회 ─────────────────────────────────────────────────
    inbox_id = payload.inbox.get("id") if payload.inbox else None
    inbox_data = chatwoot_client.get_inbox(account_id, inbox_id) if inbox_id else {}

    # ── 영업시간 외 체크 ──────────────────────────────────────────────────────
    if not is_within_business_hours(inbox_data):
        chatwoot_client.add_labels(account_id, conversation_id, ["미배정"])
        chatwoot_client.send_message(
            account_id, conversation_id,
            "현재는 상담 운영 시간이 아닙니다. 남겨주신 문의는 다음 영업일에 확인 후 답변드리겠습니다."
        )
        logger.info("영업시간 외 접수 | conv=%d", conversation_id)
        return {"status": "ok", "action": "out_of_office"}

    # ── 핸드오프 체크 ──────────────────────────────────────────────────────
    # 문의유형 버튼 선택값(예: "환불·교환")은 핸드오프 트리거 단어와 겹칠 수 있으므로
    # 버튼 클릭 자체는 핸드오프 대상에서 제외하고 바로 LLM으로 넘긴다.
    # (실제 상담 내용이 escalation이면 이후 자유 텍스트에서 핸드오프가 걸림)
    matched = [] if inquiry_selection else evaluate(user_content)
    if matched:
        logger.info("핸드오프 트리거 감지 | conv=%d rules=%s", conversation_id, matched)
        apply_actions(matched, chatwoot_client, account_id, conversation_id)

        online_agents = chatwoot_client.get_online_agents(account_id, inbox_id) if inbox_id else []

        if online_agents:
            chosen_agent = online_agents[0]
            chatwoot_client.assign_to_agent(account_id, conversation_id, assignee_id=chosen_agent["id"])
            chatwoot_client.toggle_status(account_id, conversation_id, status="open")
            logger.info("온라인 상담원 배정 | agent_id=%s name=%s", chosen_agent["id"], chosen_agent.get("name"))
            chatwoot_client.send_message(
                account_id, conversation_id,
                "상담원과 연결되었습니다. 문의하실 내용을 남겨주시면 확인 후 답변드리겠습니다."
            )
            return {"status": "ok", "action": "handoff", "rules": matched}
        else:
            chatwoot_client.add_labels(account_id, conversation_id, ["미배정"])
            chatwoot_client.send_message(
                account_id, conversation_id,
                "현재 상담 가능한 상담원이 없어 순차적으로 연결해드리겠습니다."
            )
            logger.warning("온라인 상담원 없음, 미배정 상태로 접수 | conv=%d", conversation_id)
            return {"status": "ok", "action": "no_agent_available", "rules": matched}

    # ── AI 응답 생성 + 전송 ────────────────────────────────────────────────────
    # 선택했던 문의유형이 있으면 message에 컨텍스트로 주입 (LLM 시그니처는 불변).
    inquiry_type = conversation_state.get_inquiry_type(conversation_id)
    llm_message = f"[문의유형: {inquiry_type}] {user_content}" if inquiry_type else user_content
    try:
        await generate_and_send_reply(account_id, conversation_id, llm_message, exclude_message_id=payload.id)
    except ReplyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.detail) from exc

    return {"status": "ok"}


def handle_webwidget_triggered(payload: ChatwootWebhookPayload) -> dict:
    """위젯 오픈 시 인사 + 문의유형 선택 버튼(input_select)을 먼저 전송.

    Chatwoot API 실패 시 예외로 서버가 죽지 않도록 로깅 후 200 반환
    (5xx면 Chatwoot가 재전송하므로 중복 인사 위험).
    """
    account = payload.account or {}
    account_id: int | None = account.get("id")
    inbox_id = payload.inbox.get("id") if payload.inbox else None

    if not account_id:
        logger.error("webwidget: account_id 누락")
        return {"status": "ignored", "reason": "missing account_id"}

    # ── conversation 확보: 이미 있으면 재사용, 없으면 생성 ──────────────────────
    conversation_id: int | None = (
        payload.current_conversation.id if payload.current_conversation else None
    )
    if conversation_id is None:
        if not payload.source_id or not inbox_id:
            logger.error("webwidget: source_id 또는 inbox_id 누락 | source_id=%s inbox_id=%s", payload.source_id, inbox_id)
            return {"status": "ignored", "reason": "missing source_id or inbox_id"}
        try:
            conv = chatwoot_client.create_conversation(account_id, payload.source_id, inbox_id)
            conversation_id = conv.get("id")
            logger.info("webwidget: 새 대화 생성 | conv=%s", conversation_id)
        except Exception as exc:
            logger.exception("webwidget: 대화 생성 실패: %s", exc)
            return {"status": "error", "reason": "create_conversation failed"}

    if not conversation_id:
        logger.error("webwidget: conversation_id 확보 실패")
        return {"status": "ignored", "reason": "no conversation_id"}

    # ── 중복 인사 방지 ─────────────────────────────────────────────────────────
    if conversation_state.has_greeted(conversation_id):
        logger.info("webwidget: 이미 인사 보냄, 생략 | conv=%d", conversation_id)
        return {"status": "ignored", "reason": "already greeted"}

    # ── 인사 + 문의유형 선택 버튼 전송 ─────────────────────────────────────────
    try:
        chatwoot_client.send_message(
            account_id=account_id,
            conversation_id=conversation_id,
            content=GREETING_MESSAGE,
            content_type="input_select",
            content_attributes={"items": INQUIRY_ITEMS},
        )
        conversation_state.mark_greeted(conversation_id)
        logger.info("webwidget: 인사+문의유형 버튼 전송 완료 | conv=%d", conversation_id)
    except Exception as exc:
        logger.exception("webwidget: 인사 전송 실패: %s", exc)
        return {"status": "error", "reason": "send greeting failed"}

    return {"status": "ok", "action": "greeting_sent"}


async def handle_inquiry_selection(payload: ChatwootWebhookPayload) -> dict:
    """input_select 문의유형 버튼 클릭(message_updated) 처리.

    선택값(content_attributes.submitted_values)을 문의유형으로 저장하고,
    그 값을 바로 get_ai_response로 넘겨 AI가 응답하게 한다.
    message_updated는 중복 발생 가능하므로 대화당 1회만 응답한다.
    Chatwoot API 실패 시 예외로 죽지 않도록 로깅 후 200 반환.
    """
    attrs = payload.content_attributes or {}
    submitted = attrs.get("submitted_values") or []
    if not submitted:
        # 선택 이전의 message_updated(버튼 목록만 있는 상태) — 무시
        return {"status": "ignored", "reason": "no submitted_values"}

    raw_value = (submitted[0].get("value") or submitted[0].get("title") or "").strip()
    value = match_inquiry_value(raw_value) or raw_value
    if not value:
        return {"status": "ignored", "reason": "empty submitted value"}

    account = payload.account or {}
    account_id: int | None = account.get("id")
    conversation = payload.conversation
    conversation_id: int | None = conversation.id if conversation else None
    if not account_id or not conversation_id:
        logger.error("문의유형 선택: id 누락 | account=%s conv=%s", account_id, conversation_id)
        return {"status": "ignored", "reason": "missing ids"}

    conversation_state.set_inquiry_type(conversation_id, value)

    # 중복 message_updated 방어 — 대화당 1회만 AI 응답
    if conversation_state.is_selection_handled(conversation_id):
        logger.info("문의유형 선택 이미 처리됨, 응답 생략 | conv=%d", conversation_id)
        return {"status": "ignored", "reason": "selection already handled"}
    conversation_state.mark_selection_handled(conversation_id)

    logger.info("문의유형 선택 → AI 응답 시작 | conv=%d type=%s", conversation_id, value)

    # 사람이 이미 담당 중이면 봇 응답 생략
    if payload.conversation and payload.conversation.meta and payload.conversation.meta.assignee:
        logger.info("이미 사람 담당 중, AI 응답 생략 | conv=%d", conversation_id)
        return {"status": "ignored", "reason": "already assigned to human"}

    llm_message = f"[문의유형: {value}] {value}에 대해 문의드려요."
    try:
        await generate_and_send_reply(account_id, conversation_id, llm_message)
    except ReplyError as exc:
        # 버튼 클릭 실패는 5xx로 올리지 않고 200으로 흡수(Chatwoot 재전송 방지)
        return {"status": "error", "reason": exc.detail}

    return {"status": "ok", "action": "inquiry_selection_answered"}