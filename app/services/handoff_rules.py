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

        # 1. 강한 키워드 — 확실한 신호라 LLM 호출 없이 즉시 확정 (토큰 0)
        if any(p.lower() in message_lower for p in self.strong_patterns):
            return True

        # 2. 애매한 키워드 — 이 키워드가 "실제로 걸렸을 때만" LLM을 부름.
        #    대부분의 메시지는 여기 도달조차 안 하므로, LLM 호출 자체가 드물게만 발생함.
        if self.ambiguous_keywords and any(k in message for k in self.ambiguous_keywords):
            if self.llm_confirm_prompt:
                return confirm_intent(message, self.llm_confirm_prompt)
            return True

        return False


def _set_urgent(client, account_id, conversation_id):
    client.set_priority(account_id, conversation_id, priority="urgent")


# ── A-2(컴플레인) 제거됨 ──────────────────────────────────────────────────
# 텍스트만으로 "화났는지"를 판단하는 기준 자체가 신뢰도가 낮고(오탐 잦음),
# 욕설 등 실제 상담원 보호가 필요한 상황은 기존 상담원 보호정책으로 커버되므로
# 별도 핸드오프 규칙으로 유지하지 않기로 함.

SECURITY_RULE = HandoffRule(
    name="security",
    # 그 자체로 이미 "사고 발생"을 의미하는 확실한 표현 — LLM 호출 없이 즉시 핸드오프
    strong_patterns=["이중 결제", "해킹", "도용", "계정 해킹", "계정 탈취"],
    # 중립적인 단어라 문맥에 따라 정보성 질문일 수도, 사고 신고일 수도 있음 — 이 키워드가
    # 걸렸을 때만 LLM 한 번 호출해서 확인 (모든 메시지에 LLM을 쓰는 게 아님)
    ambiguous_keywords=["결제", "개인정보", "비밀번호"],
    llm_confirm_prompt=(
        "사용자 메시지가 실제 보안 사고나 금전적 피해(결제 오류, 개인정보 유출, "
        "계정 도용 등)를 신고하는 것인지 판단하세요. "
        "단순 정보 문의(결제 방법, 개인정보 처리방침, 비밀번호 재설정 등)는 사고가 아닙니다. "
        "실제 사고 신고면 'YES', 아니면 'NO'라고만 답하세요."
    ),
    on_match=_set_urgent,
)

CONNECTION_RULE = HandoffRule(
    name="connection",
    strong_patterns=["연결"],
    ambiguous_keywords=["상담원", "상담사", "사람", "사람과", "직원", "통화"],
    llm_confirm_prompt=(
        "사용자 메시지가 실제로 사람 상담원과 연결하고 싶다는 의도인지 판단하세요. "
        "단순히 '상담사', '상담원' 같은 단어가 포함된 것만으로는 안 됩니다 "
        "(예: '상담사 자격증 따고 싶어요'는 연결 의도가 아님). "
        "실제 연결 의도면 'YES', 아니면 'NO'라고만 답하세요."
    ),
)

ALL_RULES = [SECURITY_RULE, CONNECTION_RULE]


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
    A-1/A-4든 RAG(A-5)든 A-3이든, 핸드오프가 확정된 이후엔 전부 이 함수 하나를 거친다.

    반환값: "handoff" 또는 "no_agent_available" (webhook.py 응답의 action 필드용)
    """
    online_agents = client.get_online_agents(account_id, inbox_id) if inbox_id else []

    if online_agents:
        chosen_agent = online_agents[0]
        client.assign_to_agent(account_id, conversation_id, assignee_id=chosen_agent["id"])

        # 대화가 이미 open이면 toggle_status를 또 부를 필요 없음(불필요한 "다시 열었습니다"
        # 활동 로그 방지). 여러 턴이 오간 뒤(A-3 등) 핸드오프되는 경우 open이 아닐 수 있으므로
        # 무조건 생략하지 않고 현재 상태를 확인해서 필요할 때만 전환한다.
        try:
            current = client.get_conversation(account_id, conversation_id)
            if current.get("status") != "open":
                client.toggle_status(account_id, conversation_id, status="open")
        except Exception:
            client.toggle_status(account_id, conversation_id, status="open")

        client.send_message(account_id, conversation_id, connected_message)
        return "handoff"
    else:
        client.add_labels(account_id, conversation_id, ["미배정"])
        client.send_message(account_id, conversation_id, no_agent_message)
        return "no_agent_available"