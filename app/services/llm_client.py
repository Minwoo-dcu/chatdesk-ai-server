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

import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_client = None


def get_client():
    """
    Groq Client 생성 (최초 호출 시 1회만 생성, 이후 재사용)
    """
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    """
    사용자 메시지를 받아 LLM 응답 생성
    """

    client = get_client()

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "user",
                "content": message,
            }
        ],
    )

    return response.choices[0].message.content