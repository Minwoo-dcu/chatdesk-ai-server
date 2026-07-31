"""
test_handoff_rules.py — 핸드오프 규칙(A-1~A-4) 단위 테스트
"""
from unittest.mock import MagicMock, patch

from app.services.handoff_rules import (
    ALL_RULES,
    COMPLAINT_RULE,
    CONNECTION_RULE,
    SECURITY_RULE,
    apply_actions,
    evaluate,
)


# ---------------------------------------------------------------------------
# SECURITY_RULE — strong_patterns만, LLM 확인 없음
# ---------------------------------------------------------------------------


def test_security_rule_matches_strong_pattern():
    assert SECURITY_RULE.matches("결제가 두 번 됐어요") is True


def test_security_rule_no_match():
    assert SECURITY_RULE.matches("안녕하세요") is False


# ---------------------------------------------------------------------------
# COMPLAINT_RULE — strong_patterns 즉시 매칭 / ambiguous는 LLM 확인
# ---------------------------------------------------------------------------


def test_complaint_rule_matches_strong_pattern_without_llm_call():
    with patch("app.services.handoff_rules.confirm_intent") as mock_confirm:
        assert COMPLAINT_RULE.matches("진짜 화나네요") is True
        mock_confirm.assert_not_called()


def test_complaint_rule_ambiguous_keyword_uses_llm_confirm():
    with patch("app.services.handoff_rules.confirm_intent", return_value=True) as mock_confirm:
        assert COMPLAINT_RULE.matches("이거 몇 번째 물어보는 건지 모르겠어요") is True
        mock_confirm.assert_called_once()


def test_complaint_rule_ambiguous_keyword_llm_rejects():
    with patch("app.services.handoff_rules.confirm_intent", return_value=False):
        assert COMPLAINT_RULE.matches("이거 제대로 작동하는 방법 알려주세요") is False


# ---------------------------------------------------------------------------
# CONNECTION_RULE — "연결"은 즉시 매칭 / 애매한 키워드는 LLM 확인
# ---------------------------------------------------------------------------


def test_connection_rule_matches_strong_pattern_without_llm_call():
    with patch("app.services.handoff_rules.confirm_intent") as mock_confirm:
        assert CONNECTION_RULE.matches("상담원 연결해주세요") is True
        mock_confirm.assert_not_called()


def test_connection_rule_ambiguous_keyword_uses_llm_confirm():
    with patch("app.services.handoff_rules.confirm_intent", return_value=True) as mock_confirm:
        assert CONNECTION_RULE.matches("사람과 얘기하고 싶어요") is True
        mock_confirm.assert_called_once()


def test_connection_rule_certificate_question_not_connection_intent():
    """'상담사 자격증' 같은 예시 — 키워드는 있지만 실제 연결 의도 아님(LLM이 걸러줌)"""
    with patch("app.services.handoff_rules.confirm_intent", return_value=False):
        assert CONNECTION_RULE.matches("상담사 자격증 따고 싶어요") is False


# ---------------------------------------------------------------------------
# evaluate() — 여러 규칙 동시 매칭
# ---------------------------------------------------------------------------


def test_evaluate_returns_multiple_matched_rule_names():
    with patch("app.services.handoff_rules.confirm_intent", return_value=False):
        matched = evaluate("결제 관련해서 너무하시네요")
    assert set(matched) == {"security", "complaint"}


def test_evaluate_returns_empty_when_nothing_matches():
    with patch("app.services.handoff_rules.confirm_intent", return_value=False):
        assert evaluate("안녕하세요, 반갑습니다") == []


# ---------------------------------------------------------------------------
# apply_actions() — 매칭된 규칙의 on_match만 실행
# ---------------------------------------------------------------------------


def test_apply_actions_calls_on_match_for_matched_rules_only():
    client = MagicMock()
    apply_actions(["security"], client, account_id=1, conversation_id=2)
    client.set_priority.assert_called_once_with(1, 2, priority="urgent")
    client.add_labels.assert_not_called()


def test_apply_actions_noop_for_unmatched_rule_name():
    """ALL_RULES에 없는 이름(예: rag)이 섞여 들어와도 조용히 무시"""
    client = MagicMock()
    apply_actions(["rag"], client, account_id=1, conversation_id=2)
    client.set_priority.assert_not_called()
    client.add_labels.assert_not_called()


def test_all_rules_registered():
    assert {rule.name for rule in ALL_RULES} == {"security", "complaint", "connection"}
