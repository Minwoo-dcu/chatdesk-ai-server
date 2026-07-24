import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Chatwoot REST API 클라이언트"""

    def __init__(self) -> None:
        self.base_url = settings.chatwoot_api_url.rstrip("/")
        # User(관리자) 토큰 — 배정/라벨/우선순위/인박스/이력 등 관리 API용.
        # AgentBot 토큰은 이런 관리 API에 401을 반환하므로 반드시 User 토큰을 써야 함.
        self.headers = {
            "api_access_token": settings.chatwoot_api_token,
            "Content-Type": "application/json",
        }
        # AgentBot 토큰 — 봇 응답 전송 전용. 이 토큰으로 보낸 메시지는 sender.type=agent_bot로
        # 봇 명의로 기록됨. 미설정 시 User 토큰으로 폴백(하위호환).
        bot_token = settings.chatwoot_bot_token or settings.chatwoot_api_token
        self.bot_headers = {
            "api_access_token": bot_token,
            "Content-Type": "application/json",
        }

    def send_message(
        self,
        account_id: int,
        conversation_id: int,
        content: str,
        private: bool = False,
    ) -> dict:
        """봇 응답 메시지 전송. AgentBot 토큰(bot_headers)으로 보내 봇 명의로 기록되게 함."""
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
        response = requests.post(url, json=payload, headers=self.bot_headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_messages(self, account_id: int, conversation_id: int) -> list[dict]:
        """특정 대화의 메시지 목록을 조회합니다 (최근 메시지 순, Chatwoot 기본 20건)."""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/messages"
        )
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("payload", []) if isinstance(data, dict) else data

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

    def add_labels(self, account_id: int, conversation_id: int, labels: list[str]) -> None:
        """대화에 라벨 추가"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/labels"
        )
        payload = {"labels": labels}
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()

    def set_priority(self, account_id: int, conversation_id: int, priority: str) -> None:
        """대화 우선순위 설정 (low/medium/high/urgent)"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/toggle_priority"
        )
        payload = {"priority": priority}
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()

    def get_online_agents(self, account_id: int, inbox_id: int) -> list[dict]:
        """해당 인박스에서 배정 가능한 온라인 상담원 목록 조회"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/inboxes/{inbox_id}/assignable_agents"
        )
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        agents = payload.get("payload", payload if isinstance(payload, list) else [])
        return [a for a in agents if a.get("availability_status") == "online"]

    def get_inbox(self, account_id: int, inbox_id: int) -> dict:
        """인박스 설정 조회 (영업시간 포함)"""
        url = f"{self.base_url}/api/v1/accounts/{account_id}/inboxes/{inbox_id}"
        response = requests.get(url, headers=self.headers, timeout=10)
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

    def toggle_status(self, account_id: int, conversation_id: int, status: str) -> dict:
        """대화 상태 전환 (pending/open/resolved/snoozed). 공식 핸드오프 패턴: 상담원 배정 후 pending → open"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/toggle_status"
        )
        payload = {"status": status}
        response = requests.post(url, json=payload, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_conversation(self, account_id: int, conversation_id: int) -> dict:
        """대화 정보를 조회 (현재 담당자가 누구인지 확인하는 용도)"""
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}"
        )
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()


def build_history(
    messages: list[dict],
    exclude_message_id: int | None = None,
    max_turns: int = 20,
) -> list[dict]:
    """
    Chatwoot 메시지 목록을 LLM history 형식으로 변환합니다.
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
