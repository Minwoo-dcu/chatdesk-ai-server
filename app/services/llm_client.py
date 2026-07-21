"""
llm_client.py — AI 응답 생성 모듈

webhook.py는 아래 함수만 호출합니다:

    async def get_ai_response(
        message: str,
        conversation_id: int,
        history: list[dict],
    ) -> str:

Gemini API(gemini-2.0-flash)로 구현됨.
"""

import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    # TODO: history를 활용한 멀티턴 컨텍스트 반영 (4~5주차)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=message,
    )
    return response.text