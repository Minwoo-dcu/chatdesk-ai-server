import hashlib
import hmac

from app.config import settings


def verify_webhook_signature(
    payload_body: bytes, signature_header: str, timestamp_header: str
) -> bool:
    """
    Chatwoot 웹훅 요청의 HMAC-SHA256 서명을 검증합니다.

    - CHATWOOT_WEBHOOK_SECRET이 비어있으면 검증을 건너뜁니다 (개발 환경).
    - 서명 대상 메시지는 '{timestamp}.{raw_body}' 형식이며,
      timestamp는 'X-Chatwoot-Timestamp' 헤더값입니다.
    - Chatwoot는 'X-Chatwoot-Signature' 헤더에 'sha256=<hex digest>' 형식으로 전송합니다.
    """
    secret = settings.chatwoot_webhook_secret
    if not secret:
        return True

    if not timestamp_header:
        return False

    message = timestamp_header.encode("utf-8") + b"." + payload_body
    expected = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")

    return hmac.compare_digest(expected, received)
