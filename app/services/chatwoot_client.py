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
    def assign_to_agent(self, account_id: int, conversation_id: int, assignee_id: int) -> dict:
        """대화를 특정 상담원에게 배정 (assignee_agent_bot을 nil로 만들어 봇 파이프라인에서 완전히 뺌)"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/assignments"
        )
        payload = {"assignee_id": assignee_id, "assignee_type": "User"}
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()
    def toggle_typing(self, account_id: int, conversation_id: int, status: str = "off") -> None:
        """타이핑 인디케이터를 강제로 끄는 API 호출"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/toggle_typing_status"
        )
        payload = {"typing_status": status, "is_private": False}
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()
    def get_conversation(self, account_id: int, conversation_id: int) -> dict:
        """대화 정보를 조회 (현재 담당자가 누구인지 확인하는 용도)"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}"
        )
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

chatwoot_client = ChatwootClient()
