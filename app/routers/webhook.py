import logging

import groq
from google import genai
from app.config import settings
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.models.schemas import ChatwootWebhookPayload
from app.services import conversation_state
from app.services.business_hours import is_within_business_hours
from app.services.chatwoot_client import build_history, chatwoot_client
from app.services.handoff_rules import apply_actions, assign_or_queue, evaluate
from app.services.llm_client import get_ai_response, is_repeated_inquiry
from app.services.prompts import GREETING_MESSAGE, INQUIRY_ITEMS, LLM_FAILURE_MESSAGE, match_inquiry_value
from app.services.rag_handoff import resolve as rag_resolve
from app.services.verify import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


class ReplyError(Exception):
    """AI 응답 생성/전송 단계 실패. detail로 원인을 구분해 호출자가 처리한다."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def _handle_ai_response_background(
    account_id: int,
    conversation_id: int,
    llm_message: str,
    inbox_id: int | None,
    exclude_message_id: int | None = None,
) -> None:
    """
    AI 응답 생성 및 전송을 백그라운드에서 수행.
    실패 시 고객에게 안내 메시지를 보내고 상담원에게 핸드오프.
    모든 예외를 흡수하므로 웹훅 밖으로 나가지 않음.
    """
    try:
        await generate_and_send_reply(account_id, conversation_id, llm_message, exclude_message_id)
    except ReplyError as exc:
        logger.warning("AI 응답 생성 실패 | conv=%d | error=%s", conversation_id, exc.detail)

        # 이미 핸드오프되었으면 중복 메시지 방지
        if conversation_state.has_handoff_triggered(conversation_id):
            logger.info("이미 핸드오프됨, 중복 메시지 생략 | conv=%d", conversation_id)
            return

        conversation_state.mark_handoff_triggered(conversation_id)

        try:
            chatwoot_client.send_message(account_id, conversation_id, LLM_FAILURE_MESSAGE)
            logger.info("AI 실패 안내 메시지 전송 | conv=%d", conversation_id)
        except Exception as send_exc:
            logger.exception("안내 메시지 전송 실패 | conv=%d | error=%s", conversation_id, send_exc)

        try:
            logger.warning("상담원 핸드오프 강제 | conv=%d | reason=llm_failure", conversation_id)
            apply_actions([], chatwoot_client, account_id, conversation_id)
            assign_or_queue(
                chatwoot_client, account_id, conversation_id, inbox_id,
                connected_message="상담원과 연결되었습니다. 문의하실 내용을 남겨주시면 확인 후 답변드리겠습니다.",
                no_agent_message="현재 상담 가능한 상담원이 없어 순차적으로 연결해드리겠습니다.",
            )
        except Exception as handoff_exc:
            logger.exception("핸드오프 실행 실패 | conv=%d | error=%s", conversation_id, handoff_exc)
    except Exception as exc:
        logger.exception("AI 응답 백그라운드 처리 중 예상치 못한 오류 | conv=%d", conversation_id, exc_info=exc)


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

    chatwoot_client.toggle_typing(account_id, conversation_id, status="on")
    try:
        reply = await get_ai_response(
            message=llm_message,
            conversation_id=conversation_id,
            history=history,
        )
    except groq.RateLimitError as exc:
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        logger.warning("AI 응답 생성 실패(429 Rate Limit): %s", exc)
        raise ReplyError("AI service error") from exc
    except genai.errors.ClientError as exc:
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        status_code = exc.code
        if status_code == 400:
            logger.warning("AI 응답 생성 실패(400 Bad Request): %s", exc)
        elif status_code == 429:
            logger.warning("AI 응답 생성 실패(429 Rate Limit): %s", exc)
        else:
            logger.exception("AI 응답 생성 실패(HTTP %s): %s", status_code, exc)
        raise ReplyError("AI service error") from exc
    except Exception as exc:
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        logger.exception("AI 응답 생성 실패: %s", exc)
        raise ReplyError("AI service error") from exc

    try:
        chatwoot_client.send_message(account_id=account_id, conversation_id=conversation_id, content=reply)
        logger.info("응답 전송 완료 | conv=%d reply=%s", conversation_id, reply[:80])
    except Exception as exc:
        chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
        logger.exception("Chatwoot 메시지 전송 실패: %s", exc)
        raise ReplyError("Chatwoot API error") from exc

    chatwoot_client.toggle_typing(account_id, conversation_id, status="off")
    return reply


@router.post(
    "/chatwoot",
    status_code=status.HTTP_200_OK,
    summary="Chatwoot Agent Bot 웹훅 수신",
)
async def chatwoot_webhook(
    request: Request,
    payload: ChatwootWebhookPayload,
    background_tasks: BackgroundTasks,
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
    # 선택값을 저장만 하고 return하지 않음 → 아래 기존 흐름(핸드오프/RAG/LLM)으로 그대로 이어감.
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

    # ── 핸드오프 판단 (A-1~A-4) ───────────────────────────────────────────────
    # 문의유형 버튼 선택값(예: "환불·교환")은 핸드오프 트리거 단어와 겹칠 수 있으므로
    # 버튼 클릭 자체는 핸드오프 대상에서 제외하고 바로 다음 단계(RAG/LLM)로 넘긴다.
    if inquiry_selection:
        matched = []
    else:
        try:
            matched = evaluate(user_content)
        except Exception:
            logger.exception("핸드오프 판단 실패, 매칭 없음으로 처리 | conv=%d", conversation_id)
            matched = []

    # ── RAG(A-5) 판단: A-1~A-4에서 안 걸렸을 때만 ──────────────────────────────
    # 즉답은 핸드오프가 아니라 그 자리에서 바로 끝나는 별개 경로.
    # 핸드오프로 판정되면 matched에 "rag"를 얹어 아래 실행 블록에 합류시킨다.
    if not matched and not inquiry_selection:
        rag_result = rag_resolve(user_content)

        if rag_result["action"] == "answer":
            chatwoot_client.send_message(account_id, conversation_id, rag_result["content"])
            logger.info("RAG 지식베이스 응답 | conv=%d", conversation_id)
            return {"status": "ok", "action": "rag_answer"}

        if rag_result["action"] == "handoff":
            logger.info("RAG 핸드오프 판정 | conv=%d reason=%s", conversation_id, rag_result["reason"])
            chatwoot_client.add_labels(account_id, conversation_id, ["정보조회불가"])
            matched = ["rag"]

        # rag_result["action"] == "llm"이면 matched는 빈 채로 그대로 진행

    # ── A-3(반복 문의) 판단: 핸드오프·RAG 둘 다 안 걸려 LLM으로 넘어가는 경우만 ─────
    # 매 메시지마다 LLM을 호출하면 지연·비용이 두 배가 되므로, 3턴마다 한 번만 체크한다.
    if not matched and not inquiry_selection:
        turn = conversation_state.increment_turn(conversation_id)
        if conversation_state.should_check_repetition(conversation_id, every_n_turns=3):
            try:
                messages_for_check = chatwoot_client.get_messages(account_id, conversation_id)
                history_for_check = build_history(messages_for_check, exclude_message_id=payload.id)
            except Exception as exc:
                logger.warning("A-3 판단용 이력 조회 실패, 판단 생략: %s", exc)
                history_for_check = []

            if history_for_check:
                is_repeat = is_repeated_inquiry(user_content, history_for_check)
                logger.info("A-3 반복 판단 실행 | conv=%d turn=%d result=%s", conversation_id, turn, is_repeat)
                if is_repeat:
                    repeat_count = conversation_state.increment_repeat_confirmed(conversation_id)
                    logger.info("반복 문의 감지 | conv=%d turn=%d repeat_count=%d", conversation_id, turn, repeat_count)
                    if repeat_count >= 2:
                        conversation_state.reset_repeat_confirmed(conversation_id)
                        chatwoot_client.add_labels(account_id, conversation_id, ["반복문의"])
                        matched = ["repeated_inquiry"]

    # ── 핸드오프 실행 (A-1~A-4든 RAG든 A-3든, 여기 한 곳에서만 처리) ────────────────
    if matched:
        logger.info("핸드오프 실행 | conv=%d rules=%s", conversation_id, matched)
        apply_actions(matched, chatwoot_client, account_id, conversation_id)  # "rag"는 ALL_RULES에 없어 조용히 무시됨
        action = assign_or_queue(
            chatwoot_client, account_id, conversation_id, inbox_id,
            connected_message="상담원과 연결되었습니다. 문의하실 내용을 남겨주시면 확인 후 답변드리겠습니다.",
            no_agent_message="현재 상담 가능한 상담원이 없어 순차적으로 연결해드리겠습니다.",
        )
        return {"status": "ok", "action": action, "rules": matched}

    # ── AI 응답 생성 + 전송 (백그라운드) ─────────────────────────────────────
    # 웹훅은 즉시 200을 반환하고, AI 응답 생성/전송/핸드오프는 백그라운드로 처리.
    # 이렇게 하면 Chatwoot이 재전송하지 않으며, 고객 대기 시간도 줄어듦.
    inquiry_type = conversation_state.get_inquiry_type(conversation_id)
    llm_message = f"[문의유형: {inquiry_type}] {user_content}" if inquiry_type else user_content
    background_tasks.add_task(
        _handle_ai_response_background,
        account_id=account_id,
        conversation_id=conversation_id,
        llm_message=llm_message,
        inbox_id=inbox_id,
        exclude_message_id=payload.id,
    )
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