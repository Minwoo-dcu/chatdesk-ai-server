"""
conversation_state.py — 대화별 인메모리 상태 관리
webwidget_triggered 중복 인사 방지, 선택한 문의유형 저장, A-3(반복 문의) 판단에 사용합니다.
⚠️ 한계: 프로세스 메모리에만 저장됩니다. 서버 재시작 시 전부 초기화되며,
여러 워커/인스턴스로 스케일아웃하면 워커 간 상태가 공유되지 않습니다.
영구성이 필요해지면 Redis 등 외부 스토어로 교체해야 합니다.
"""

# 인사(인사+문의유형 버튼)를 이미 보낸 conversation_id 집합
_greeted: set[int] = set()

# conversation_id → 사용자가 선택한 문의유형 value
_inquiry_type: dict[int, str] = {}

# 문의유형 선택에 대해 이미 AI 응답을 보낸 conversation_id
# (input_select 클릭은 message_updated로 오며 중복 발생 가능 → 1회만 응답)
_selection_handled: set[int] = set()

# A-3(반복 문의): 대화별 누적 메시지(턴) 수 — 몇 턴마다 반복 판단을 실행할지 계산용
_turn_count: dict[int, int] = {}

# A-3(반복 문의): LLM이 "반복"으로 확정 판정한 횟수 — 기준치 넘으면 핸드오프
_repeat_confirmed_count: dict[int, int] = {}


def has_greeted(conversation_id: int) -> bool:
    """해당 대화에 이미 인사를 보냈는지 여부"""
    return conversation_id in _greeted


def mark_greeted(conversation_id: int) -> None:
    """해당 대화를 인사 완료로 표시"""
    _greeted.add(conversation_id)


def set_inquiry_type(conversation_id: int, value: str) -> None:
    """해당 대화의 선택한 문의유형 저장"""
    _inquiry_type[conversation_id] = value


def get_inquiry_type(conversation_id: int) -> str | None:
    """해당 대화의 선택한 문의유형 조회 (없으면 None)"""
    return _inquiry_type.get(conversation_id)


def is_selection_handled(conversation_id: int) -> bool:
    """해당 대화의 문의유형 선택에 이미 AI 응답을 보냈는지 여부"""
    return conversation_id in _selection_handled


def mark_selection_handled(conversation_id: int) -> None:
    """해당 대화의 문의유형 선택 응답 완료로 표시"""
    _selection_handled.add(conversation_id)


def increment_turn(conversation_id: int) -> int:
    """해당 대화의 누적 메시지 수를 1 늘리고 반환"""
    _turn_count[conversation_id] = _turn_count.get(conversation_id, 0) + 1
    return _turn_count[conversation_id]


def should_check_repetition(conversation_id: int, every_n_turns: int = 3) -> bool:
    """이번 턴이 반복 판단을 실행할 차례인지 (every_n_turns의 배수번째 턴일 때만 True)"""
    return _turn_count.get(conversation_id, 0) % every_n_turns == 0


def increment_repeat_confirmed(conversation_id: int) -> int:
    """LLM이 반복으로 확정 판정한 횟수를 1 늘리고 반환"""
    _repeat_confirmed_count[conversation_id] = _repeat_confirmed_count.get(conversation_id, 0) + 1
    return _repeat_confirmed_count[conversation_id]


def reset_repeat_confirmed(conversation_id: int) -> None:
    """반복 확정 카운트 초기화 (핸드오프되거나 새 문의유형 선택 시 호출)"""
    _repeat_confirmed_count[conversation_id] = 0