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

def confirm_intent(message: str, prompt: str) -> bool:
    """
    애매한 경우에만 호출: 주어진 판단 기준(prompt)에 따라
    LLM한테 실제 의도가 맞는지 YES/NO로 확인받음
    """
    client = get_client()
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": message},
        ],
        temperature=0,
    )
    answer = response.choices[0].message.content.strip()
    return "YES" in answer.upper()


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
