"""
rag_handoff.py — A-5(RAG 기반 정보조회 핸드오프) 처리 흐름

docs/poc의 RAG PoC 문서에 정의된 흐름을 구현:
    사용자 질문 → RAG 문서 검색 → 신뢰도 확인 → (높음) AI 응답 / (낮음·없음) 핸드오프

재고/주문상태/배송조회처럼 실시간 DB 조회가 필요한 카테고리는
아직 그 API가 없으므로, 지식베이스에 handoff_only=True로 등록해두고
매칭되면 무조건 핸드오프 처리한다 (Hallucination 방지).
"""
from app.services.knowledge_base import search
from app.services.business_hours import format_business_hours

CONFIDENCE_THRESHOLD = 0.7


def resolve(question: str, inbox_data: dict | None = None) -> dict:
    result = search(question)

    if result is None:
        return {"action": "llm", "content": None}

    if result.get("handoff_only"):
        return {"action": "handoff", "reason": result.get("handoff_reason", "DB_API_NOT_CONNECTED")}

    if result.get("dynamic") == "business_hours" and inbox_data is not None:
        return {"action": "answer", "content": format_business_hours(inbox_data)}

    if result["confidence"] >= CONFIDENCE_THRESHOLD:
        return {"action": "answer", "content": result["answer"]}

    return {"action": "handoff", "reason": "RAG_LOW_CONFIDENCE"}