from dataclasses import dataclass, field
from typing import Callable, Optional
from app.services.llm_client import confirm_intent

@dataclass
class HandoffRule:
    name: str
    strong_patterns: list[str] = field(default_factory=list)
    ambiguous_keywords: list[str] = field(default_factory=list)
    llm_confirm_prompt: Optional[str] = None
    on_match: Optional[Callable] = None  # (chatwoot_client, account_id, conversation_id) -> None

    def matches(self, message: str) -> bool:
        message_lower = message.lower()
        if any(p.lower() in message_lower for p in self.strong_patterns):
            return True
        if self.ambiguous_keywords and any(k in message for k in self.ambiguous_keywords):
            if self.llm_confirm_prompt:
                return confirm_intent(message, self.llm_confirm_prompt)
            return True
        return False


def _set_urgent(client, account_id, conversation_id):
    client.set_priority(account_id, conversation_id, priority="urgent")


def _add_complaint_label(client, account_id, conversation_id):
    client.add_labels(account_id, conversation_id, ["컴플레인"])


SECURITY_RULE = HandoffRule(
    name="security",
    strong_patterns=["결제", "이중 결제", "환불", "해킹", "도용", "계정 해킹", "계정 탈취", "개인정보", "비밀번호"],
    on_match=_set_urgent,
)

COMPLAINT_RULE = HandoffRule(
    name="complaint",
    strong_patterns=["짜증", "화나", "화가", "너무하네", "너무하시네", "실망", "불만", "몇 번째", "몇번째", "제대로", "책임져"],
    on_match=_add_complaint_label,
)

CONNECTION_RULE = HandoffRule(
    name="connection",
    strong_patterns=["연결"],
    ambiguous_keywords=["상담원", "상담사", "사람", "사람과", "직원"],
    llm_confirm_prompt=(
        "사용자 메시지가 실제로 사람 상담원과 연결하고 싶다는 의도인지 판단하세요. "
        "단순히 '상담사', '상담원' 같은 단어가 포함된 것만으로는 안 됩니다 "
        "(예: '상담사 자격증 따고 싶어요'는 연결 의도가 아님). "
        "실제 연결 의도면 'YES', 아니면 'NO'라고만 답하세요."
    ),
)

ALL_RULES = [SECURITY_RULE, COMPLAINT_RULE, CONNECTION_RULE]


def evaluate(message: str) -> list[str]:
    """매칭된 규칙 이름들을 전부 반환 (여러 개 동시 매칭 가능하게)"""
    return [rule.name for rule in ALL_RULES if rule.matches(message)]


def apply_actions(matched_names: list[str], client, account_id: int, conversation_id: int):
    for rule in ALL_RULES:
        if rule.name in matched_names and rule.on_match:
            rule.on_match(client, account_id, conversation_id)