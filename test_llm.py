import asyncio

from app.services.llm_client import get_ai_response


async def main():
    answer = await get_ai_response(
        message="안녕하세요. 당신은 누구인가요?",
        conversation_id=1,
        history=[],
    )
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())