from typing import Any, Optional

from pydantic import BaseModel


class ChatwootSender(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    type: Optional[str] = None  # "contact" | "agent" | "bot"


class ChatwootConversation(BaseModel):
    id: int
    inbox_id: int
    status: Optional[str] = None


class ChatwootMessage(BaseModel):
    id: int
    content: Optional[str] = None
    message_type: int  # 0 = incoming (고객), 1 = outgoing (상담사/봇)
    created_at: int
    conversation_id: Optional[int] = None
    sender: Optional[ChatwootSender] = None


class ChatwootWebhookPayload(BaseModel):
    event: str
    message_type: Optional[str] = None
    message: Optional[ChatwootMessage] = None
    conversation: Optional[ChatwootConversation] = None
    account: Optional[dict[str, Any]] = None
