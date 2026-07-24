"""
conversation_state.py — 대화별 인메모리 상태 관리

webwidget_triggered 중복 인사 방지 및 선택한 문의유형 저장에 사용합니다.

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
