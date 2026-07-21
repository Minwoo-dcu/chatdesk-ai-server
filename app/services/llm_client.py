import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=message,
    )
    return response.text