"""
llm_client.py — AI 응답 생성 모듈 (팀원 담당)

## 인터페이스 계약

webhook.py는 아래 함수만 호출합니다:

    async def get_ai_response(
        message: str,
        conversation_id: int,
        history: list[dict],
    ) -> str:

### 파라미터
- message (str): 고객이 보낸 메시지 원문
- conversation_id (int): Chatwoot 대화 ID (문맥 추적용)
- history (list[dict]): 최근 대화 이력
    예시: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

### 반환값
- str: 봇이 고객에게 전송할 응답 텍스트

## 현재 상태: MOCK (에코 응답)
아래 구현은 임시 목업입니다. 실제 Gemini API 연동으로 교체해주세요.
config.py의 `gemini_api_key` (환경변수 GEMINI_API_KEY) 를 사용하면 됩니다.
"""


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    # TODO: Gemini API 연동으로 교체 (팀원 담당)
    return f"[ECHO] {message}"
