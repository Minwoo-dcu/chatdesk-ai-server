"""
llm_client.py — AI 응답 생성 모듈 (Groq/Gemini 지원)

webhook.py는 아래 함수만 호출합니다:

    async def get_ai_response(
        message: str,
        conversation_id: int,
        history: list[dict],
    ) -> str:

LLM_PROVIDER 환경변수 (groq | gemini)로 선택됨.
"""

from groq import Groq
from google import genai

from app.config import settings
from app.services.prompts import SYSTEM_PROMPT

_groq_client = None
_gemini_client = None


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.groq_api_key)
    return _groq_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def _gemini_convert_messages(messages: list[dict]) -> list:
    """
    OpenAI 형식 → google-genai 형식 변환

    - role "assistant" → "model" 변환
    - system은 별도로 처리되므로 제외
    """
    contents = []
    for msg in messages:
        role = msg["role"]
        if role == "system":
            continue
        role_mapped = "model" if role == "assistant" else "user"
        contents.append({
            "role": role_mapped,
            "parts": [{"text": msg["content"]}]
        })
    return contents


def _call_groq(system: str, messages: list[dict], model: str, temperature: float = 0) -> str:
    """Groq API 호출"""
    client = _get_groq_client()
    full_messages = [
        {"role": "system", "content": system},
        *messages,
    ]
    response = client.chat.completions.create(
        model=model,
        messages=full_messages,
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


def _call_gemini(system: str, messages: list[dict], model: str) -> str:
    """Gemini API 호출"""
    client = _get_gemini_client()
    contents = _gemini_convert_messages(messages)

    config = genai.types.GenerateContentConfig(systemInstruction=system)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    return response.text.strip()


def build_messages(message: str, history: list[dict]) -> list[dict]:
    """
    system 프롬프트 + 대화 이력 + 현재 메시지를 messages 배열로 조립합니다.

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
    messages = [{"role": "user", "content": message}]

    if settings.llm_provider == "gemini":
        answer = _call_gemini(prompt, messages, model=settings.gemini_model_quick)
    else:
        answer = _call_groq(prompt, messages, model=settings.groq_model_default, temperature=0)

    return "YES" in answer.upper()


def is_repeated_inquiry(message: str, history: list[dict]) -> bool:
    """
    A-3(반복 문의) 판단: 직전 대화 이력을 보고, 이번 메시지가 아직 해결되지 않은
    질문을 다른 표현으로 반복하는 것인지 확인한다. 자연스러운 새 질문·화제 전환은 반복이 아님.
    판단 작업이므로 일관성을 유지한다.
    """
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])
    prompt = (
        "아래는 고객과 AI 상담봇의 최근 대화 이력이야. "
        "고객의 마지막 메시지가, 앞서 이미 물어봤지만 만족스럽게 해결되지 않은 질문을 "
        "다른 표현으로 반복하는 것인지 판단해. 자연스러운 새 질문이나 화제 전환이면 반복이 아니야. "
        "반복이면 'YES', 아니면 'NO'라고만 답해."
    )
    user_content = f"대화 이력:\n{history_text}\n\n판단 대상 메시지: {message}"
    messages = [{"role": "user", "content": user_content}]

    if settings.llm_provider == "gemini":
        answer = _call_gemini(prompt, messages, model=settings.gemini_model_quick)
    else:
        answer = _call_groq(prompt, messages, model=settings.groq_model_default, temperature=0)

    return "YES" in answer.upper()


def generate_rag_answer(question: str, data: dict) -> str:
    """
    A-5(RAG) 응답 생성: 지식베이스에서 찾은 값 데이터(data)를 근거로
    질문에 자연스러운 문장으로 답변을 생성한다. data에 없는 내용은 지어내지 않는다.
    """
    def fmt(v):
        return ", ".join(v) if isinstance(v, list) else str(v)

    data_text = "\n".join(f"- {k}: {fmt(v)}" for k, v in data.items())

    prompt = (
        "너는 상담 챗봇이야. 아래 '참고 정보'만 근거로 고객 질문에 자연스러운 한국어 문장으로 답변해. "
        "참고 정보에 없는 내용은 절대 지어내지 말고, 참고 정보 범위 내에서만 답해. "
        "친절하고 간결하게 1~3문장으로 답변해."
    )
    user_content = f"참고 정보:\n{data_text}\n\n고객 질문: {question}"
    messages = [{"role": "user", "content": user_content}]

    if settings.llm_provider == "gemini":
        answer = _call_gemini(prompt, messages, model=settings.gemini_model_rag)
    else:
        answer = _call_groq(prompt, messages, model=settings.groq_model_rag, temperature=0.3)

    return answer


async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    """
    사용자 메시지와 대화 이력을 받아 LLM 응답 생성
    """
    messages = build_messages(message, history)
    system = messages[0]["content"]
    user_messages = messages[1:]

    if settings.llm_provider == "gemini":
        answer = _call_gemini(system, user_messages, model=settings.gemini_model_default)
    else:
        answer = _call_groq(system, user_messages, model=settings.groq_model_default, temperature=0)

    return answer