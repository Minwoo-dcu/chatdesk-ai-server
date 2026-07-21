import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_response(message: str) -> str:
    """
    사용자 메시지를 받아 LLM 응답을 생성하는 함수
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=message
    )

    return response.text