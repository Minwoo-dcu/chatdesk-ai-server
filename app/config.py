from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Chatwoot
    chatwoot_api_url: str
    chatwoot_api_token: str  # User(관리자/상담원) 토큰 — 배정/라벨/우선순위 등 관리 API용
    chatwoot_bot_token: str = ""  # AgentBot access_token — 봇 응답 전송용(봇 명의로 기록). 비우면 api_token으로 폴백
    chatwoot_webhook_secret: str = ""  # 빈 값이면 서명 검증 생략

    # LLM Provider
    llm_provider: str = ""  # groq | gemini
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # Model names
    groq_model_default: str = "llama-3.1-8b-instant"
    groq_model_rag: str = "llama-3.1-8b-instant"
    gemini_model_default: str = "gemini-3.5-flash"
    gemini_model_rag: str = "gemini-3.5-flash"
    gemini_model_quick: str = "gemini-3.5-flash"

    # Test mode: 429 RESOURCE_EXHAUSTED 강제 발생 (로컬 테스트용)
    test_429_force: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
