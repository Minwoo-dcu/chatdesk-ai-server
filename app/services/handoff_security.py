"""
handoff_security.py — 금전·보안 이슈 핸드오프 판단

webhook.py는 아래 함수만 호출합니다:
    def should_handoff(message: str) -> bool
"""


SECURITY_KEYWORDS = [
    "결제",
    "이중 결제",
    "환불",
    "해킹",
    "도용",
    "계정 해킹",
    "계정 탈취",
    "개인정보",
    "비밀번호",
]


def should_handoff(message: str) -> bool:
    message = message.lower()

    return any(
        keyword in message
        for keyword in SECURITY_KEYWORDS
    )