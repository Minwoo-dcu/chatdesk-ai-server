"""
llm_client.py — AI 응답 생성 모듈

webhook.py는 아래 함수만 호출합니다:

    async def get_ai_response(
        message: str,
        conversation_id: int,
        history: list[dict],
    ) -> str:

Groq API 기반 LLM 응답 생성
"""

from groq import Groq

from app.config import settings
from app.services.prompts import SYSTEM_PROMPT

_client = None


def get_client():
    """
    Groq Client 생성 (최초 호출 시 1회만 생성, 이후 재사용)
    """
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def build_messages(message: str, history: list[dict]) -> list[dict]:
    """
    system 프롬프트 + 대화 이력 + 현재 메시지를 Groq messages 배열로 조립합니다.

    Args:
        message: 방금 수신한 사용자 메시지
        history: [{"role": "user"|"assistant", "content": str}, ...]
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": message},
    ]


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    """
    사용자 메시지와 대화 이력을 받아 LLM 응답 생성
    """

    client = get_client()

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=build_messages(message, history),
    )

    return response.choices[0].message.content
