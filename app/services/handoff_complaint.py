"""
handoff_complaint.py — 부정 감정·컴플레인 핸드오프 판단 (A-2)
webhook.py는 아래 함수만 호출합니다:
    def should_handoff(message: str) -> bool
"""

COMPLAINT_KEYWORDS = [
    "짜증",
    "화나",
    "화가",
    "너무하네",
    "너무하시네",
    "실망",
    "불만",
    "몇 번째",
    "몇번째",
    "제대로",
    "책임져",
]


def should_handoff(message: str) -> bool:
    return any(keyword in message for keyword in COMPLAINT_KEYWORDS)
