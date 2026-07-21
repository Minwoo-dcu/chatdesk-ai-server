"""
test_history.py — 대화 이력 변환(build_history) / LLM 메시지 조립(build_messages) 단위 테스트
"""
from app.services.chatwoot_client import build_history
from app.services.llm_client import build_messages
from app.services.prompts import SYSTEM_PROMPT


def _msg(id: int, content: str, message_type, private: bool = False) -> dict:
    return {"id": id, "content": content, "message_type": message_type, "private": private}


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------


def test_incoming_outgoing_role_mapping():
    """incoming(0)→user, outgoing(1)→assistant 매핑"""
    messages = [
        _msg(1, "질문", 0),
        _msg(2, "답변", 1),
    ]
    assert build_history(messages) == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
    ]


def test_string_message_type_also_mapped():
    """message_type이 문자열("incoming"/"outgoing")로 와도 매핑"""
    messages = [
        _msg(1, "질문", "incoming"),
        _msg(2, "답변", "outgoing"),
    ]
    assert build_history(messages) == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
    ]


def test_activity_and_unknown_types_excluded():
    """activity(2)/template(3) 등 대화가 아닌 메시지는 제외"""
    messages = [
        _msg(1, "질문", 0),
        _msg(2, "대화가 시작되었습니다", 2),
        _msg(3, "템플릿", 3),
    ]
    assert build_history(messages) == [{"role": "user", "content": "질문"}]


def test_private_note_excluded():
    """상담사 내부 노트(private=True)는 제외"""
    messages = [
        _msg(1, "질문", 0),
        _msg(2, "내부 메모", 1, private=True),
    ]
    assert build_history(messages) == [{"role": "user", "content": "질문"}]


def test_empty_content_excluded():
    """빈 content / None content는 제외"""
    messages = [
        _msg(1, "", 0),
        {"id": 2, "content": None, "message_type": 0, "private": False},
        _msg(3, "실제 질문", 0),
    ]
    assert build_history(messages) == [{"role": "user", "content": "실제 질문"}]


def test_current_message_excluded_by_id():
    """방금 수신한 현재 메시지는 exclude_message_id로 제외 (중복 방지)"""
    messages = [
        _msg(1, "이전 질문", 0),
        _msg(2, "이전 답변", 1),
        _msg(3, "현재 질문", 0),
    ]
    history = build_history(messages, exclude_message_id=3)
    assert history == [
        {"role": "user", "content": "이전 질문"},
        {"role": "assistant", "content": "이전 답변"},
    ]


def test_history_limited_to_max_turns():
    """max_turns 초과 시 최근 것만 유지"""
    messages = [_msg(i, f"메시지 {i}", 0) for i in range(30)]
    history = build_history(messages, max_turns=20)
    assert len(history) == 20
    assert history[0]["content"] == "메시지 10"
    assert history[-1]["content"] == "메시지 29"


def test_empty_messages_returns_empty_history():
    assert build_history([]) == []


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


def test_build_messages_structure():
    """system 프롬프트 → history → 현재 메시지 순서로 조립"""
    history = [
        {"role": "user", "content": "이전 질문"},
        {"role": "assistant", "content": "이전 답변"},
    ]
    messages = build_messages("현재 질문", history)

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1:3] == history
    assert messages[-1] == {"role": "user", "content": "현재 질문"}
    assert len(messages) == 4


def test_build_messages_empty_history():
    """history 없으면 system + 현재 메시지만"""
    messages = build_messages("첫 질문", [])
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "첫 질문"}
