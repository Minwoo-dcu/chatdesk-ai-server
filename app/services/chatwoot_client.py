import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Chatwoot REST API 클라이언트"""

    def __init__(self) -> None:
        self.base_url = settings.chatwoot_api_url.rstrip("/")
        self.headers = {
            "api_access_token": settings.chatwoot_api_token,
            "Content-Type": "application/json",
        }

    def send_message(
        self,
        account_id: int,
        conversation_id: int,
        content: str,
        private: bool = False,
    ) -> dict:
        """
        특정 대화(conversation)에 봇 메시지를 전송합니다.

        Args:
            account_id: Chatwoot 계정 ID (웹훅 페이로드의 account.id)
            conversation_id: 대화 ID
            content: 전송할 메시지 본문
            private: True이면 내부 노트(상담사만 볼 수 있음)
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/messages"
        )
        payload = {
            "content": content,
            "message_type": "outgoing",
            "private": private,
        }
        logger.debug("Chatwoot 메시지 전송 → conv=%d: %s", conversation_id, content[:80])
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_messages(self, account_id: int, conversation_id: int) -> list[dict]:
        """
        특정 대화의 메시지 목록을 조회합니다 (최근 메시지 순, Chatwoot 기본 20건).

        Returns:
            메시지 dict 리스트 (오래된 것 → 최신 순)
        """
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/messages"
        )
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Chatwoot는 {"meta": ..., "payload": [...]} 형태로 응답
        return data.get("payload", []) if isinstance(data, dict) else data


def build_history(
    messages: list[dict],
    exclude_message_id: int | None = None,
    max_turns: int = 20,
) -> list[dict]:
    """
    Chatwoot 메시지 목록을 LLM history 형식으로 변환합니다.

    - incoming(0) → user, outgoing(1) → assistant
    - activity/template, private 노트, 빈 content는 제외
    - exclude_message_id와 일치하는 메시지(방금 수신한 현재 메시지)는 제외
    - 최근 max_turns개만 유지

    Returns:
        [{"role": "user"|"assistant", "content": str}, ...]
    """
    role_map = {0: "user", 1: "assistant", "incoming": "user", "outgoing": "assistant"}
    history = []
    for msg in messages:
        role = role_map.get(msg.get("message_type"))
        content = (msg.get("content") or "").strip()
        if role is None or not content:
            continue
        if msg.get("private"):
            continue
        if exclude_message_id is not None and msg.get("id") == exclude_message_id:
            continue
        history.append({"role": role, "content": content})
    return history[-max_turns:]


chatwoot_client = ChatwootClient()
