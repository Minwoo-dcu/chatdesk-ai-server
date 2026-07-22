import logging

from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

# 의도가 명백한 표현 — LLM 확인 없이 즉시 핸드오프
STRONG_PATTERNS = ["연결"]

# 역할 단어만 있어 애매한 경우 — LLM한테 진짜 의도인지 확인
AMBIGUOUS_KEYWORDS = ["상담원", "상담사", "사람", "사람과","직원"]

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def confirm_handoff_intent(message: str) -> bool:
    """애매한 경우에만 호출: 진짜 상담원 연결 의도인지 Groq한테 확인"""
    client = get_client()
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    "사용자 메시지가 실제로 사람 상담원과 연결하고 싶다는 의도인지 판단하세요. "
                    "단순히 '상담사', '상담원' 같은 단어가 포함된 것만으로는 안 됩니다 "
                    "(예: '상담사 자격증 따고 싶어요'는 연결 의도가 아님). "
                    "실제 연결 의도면 'YES', 아니면 'NO'라고만 답하세요."
                ),
            },
            {"role": "user", "content": message},
        ],
        temperature=0,
    )
    answer = response.choices[0].message.content.strip()
    logger.info("Groq 핸드오프 판단 원본 답변: %r", answer)
    return "YES" in answer.upper()


def should_handoff(message: str) -> bool:
    """
    1단계: '연결' 같은 명백한 표현은 LLM 없이 즉시 핸드오프
    2단계: 역할 단어만 있는 애매한 경우만 LLM으로 확인
    """
    if any(pattern in message for pattern in STRONG_PATTERNS):
        logger.info("명백한 핸드오프 패턴 감지 (LLM 미사용)")
        return True

    if any(keyword in message for keyword in AMBIGUOUS_KEYWORDS):
        return confirm_handoff_intent(message)

    return False
