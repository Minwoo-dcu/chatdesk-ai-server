from typing import Any, Optional

from pydantic import BaseModel


class ChatwootSender(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    type: Optional[str] = None  # "contact" | "agent" | "bot"
class ChatwootAssignee(BaseModel):
    id: int
    name: Optional[str] = None

class ChatwootMeta(BaseModel):
    assignee: Optional[ChatwootAssignee] = None

class ChatwootConversation(BaseModel):
    id: int
    inbox_id: int
    status: Optional[str] = None
    meta: Optional[ChatwootMeta] = None

class ChatwootWebhookPayload(BaseModel):
    """
    Chatwoot Agent Bot 웹훅 페이로드.

    Agent Bot 웹훅은 message 필드를 중첩 객체로 보내지 않고,
    메시지 관련 필드(content, message_type 등)를 최상위에 flat하게 포함합니다.
    """

    event: str

    # 메시지 필드 (message_created 이벤트 시 최상위에 위치)
    id: Optional[int] = None
    content: Optional[str] = None
    message_type: Optional[str] = None  # "incoming" | "outgoing" | "activity"
    created_at: Optional[Any] = None
    sender: Optional[ChatwootSender] = None
    inbox: Optional[dict[str, Any]] = None
    content_attributes: Optional[dict[str, Any]] = None  # input_select 선택값(submitted_values) 등

    # 대화 / 계정 정보
    conversation: Optional[ChatwootConversation] = None
    account: Optional[dict[str, Any]] = None

    # webwidget_triggered 이벤트 필드 (위젯 오픈 시 최상위에 위치)
    contact: Optional[dict[str, Any]] = None
    current_conversation: Optional[ChatwootConversation] = None  # null이면 첫 방문
    source_id: Optional[str] = None
