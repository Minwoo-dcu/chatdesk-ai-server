"""
business_hours.py — Chatwoot 인박스 설정 기반 영업시간 판단 (A-6)
.env나 하드코딩된 시간값 없이, Chatwoot API 응답만으로 판단합니다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo


def is_within_business_hours(inbox_data: dict) -> bool:
    if not inbox_data.get("working_hours_enabled"):
        return True  # 설정 자체를 안 켰으면 제한 없음

    timezone = inbox_data.get("timezone", "UTC")
    now = datetime.now(ZoneInfo(timezone))
    weekday = (now.weekday() + 1) % 7  # Python 요일 → Chatwoot 요일 변환

    for day in inbox_data.get("working_hours", []):
        if day.get("day_of_week") != weekday:
            continue
        if day.get("closed_all_day"):
            return False
        if day.get("open_all_day"):
            return True
        open_hour = day.get("open_hour")
        close_hour = day.get("close_hour")
        if open_hour is None or close_hour is None:
            return False
        return open_hour <= now.hour < close_hour

    return False


def format_business_hours(inbox_data: dict) -> str:
    """Chatwoot 인박스의 영업시간 설정을 사용자에게 안내할 문장으로 변환."""
    if not inbox_data.get("working_hours_enabled"):
        return "24시간 상담 가능합니다."

    days_kr = ["일", "월", "화", "수", "목", "금", "토"]
    lines = []
    for day in inbox_data.get("working_hours", []):
        idx = day.get("day_of_week")
        if day.get("closed_all_day"):
            continue
        if day.get("open_all_day"):
            lines.append(f"{days_kr[idx]}: 24시간")
        else:
            lines.append(f"{days_kr[idx]}: {day.get('open_hour')}시~{day.get('close_hour')}시")

    return "영업시간 안내\n" + "\n".join(lines) if lines else "영업시간 정보가 설정되어 있지 않습니다."