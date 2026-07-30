from dataclasses import dataclass, field
from typing import Callable, Optional

from app.services.llm_client import confirm_intent


@dataclass
class HandoffRule:
    name: str
    strong_patterns: list[str] = field(default_factory=list)
    ambiguous_keywords: list[str] = field(default_factory=list)
    llm_confirm_prompt: Optional[str] = None
    detector: Optional[Callable[[str], bool]] = None  # 키워드 매칭 밖의 커스텀 판단(예: 비속어 탐지)
    on_match: Optional[Callable] = None  # (chatwoot_client, account_id, conversation_id) -> None

    def matches(self, message: str) -> bool:
        message_lower = message.lower()

        if any(p.lower() in message_lower for p in self.strong_patterns):
            return True

        if self.detector and self.detector(message):
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
    strong_patterns=["결제", "이중 결제", "해킹", "도용", "계정 해킹", "계정 탈취", "개인정보", "비밀번호"],
    on_match=_set_urgent,
)

COMPLAINT_RULE = HandoffRule(
    name="complaint",
    strong_patterns=["짜증", "화나", "화가", "너무하네", "너무하시네", "실망", "책임져"],
    ambiguous_keywords=["불만", "몇 번째", "몇번째", "제대로"],
    llm_confirm_prompt=(
        "사용자 메시지가 서비스에 대한 실제 불만/컴플레인 표현인지 판단하세요. "
        "단순 정보 문의나 일반적인 대화는 컴플레인이 아닙니다 "
        "(예: '이거 몇 번째 눌러야 되나요?'는 컴플레인이 아니라 사용법 질문). "
        "실제 컴플레인이면 'YES', 아니면 'NO'라고만 답하세요."
    ),
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


def assign_or_queue(client, account_id: int, conversation_id: int, inbox_id: int | None,
                     connected_message: str, no_agent_message: str) -> str:
    """
    핸드오프가 결정된 뒤 실행되는 공통 로직: 온라인 상담원이 있으면 배정,
    없으면 미배정 라벨 붙이고 대기 안내.
    A-1~A-4든 RAG(A-5)든, 핸드오프가 확정된 이후엔 전부 이 함수 하나를 거친다.

    반환값: "handoff" 또는 "no_agent_available" (webhook.py 응답의 action 필드용)
    """
    online_agents = client.get_online_agents(account_id, inbox_id) if inbox_id else []

    if online_agents:
        chosen_agent = online_agents[0]
        client.assign_to_agent(account_id, conversation_id, assignee_id=chosen_agent["id"])
        client.toggle_status(account_id, conversation_id, status="open")
        client.send_message(account_id, conversation_id, connected_message)
        return "handoff"
    else:
        client.add_labels(account_id, conversation_id, ["미배정"])
        client.send_message(account_id, conversation_id, no_agent_message)
        return "no_agent_available"