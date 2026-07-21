from app.services.llm_client import generate_response


answer = generate_response(
    "안녕하세요. 당신은 누구인가요?"
)

print(answer)