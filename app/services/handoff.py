HANDOFF_KEYWORDS = ["상담원", "사람이랑", "사람과", "직원 연결", "상담사"]

def should_handoff(message: str) -> bool:
    """방문자 메시지에 핸드오프 트리거 키워드가 있으면 True"""
    return any(keyword in message for keyword in HANDOFF_KEYWORDS)
