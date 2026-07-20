import hashlib
import hmac

from app.config import settings


def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    Chatwoot 웹훅 요청의 HMAC-SHA256 서명을 검증합니다.

    - CHATWOOT_WEBHOOK_SECRET이 비어있으면 검증을 건너뜁니다 (개발 환경).
    - Chatwoot는 'X-Chatwoot-Signature' 헤더에 hex digest를 담아 전송합니다.
    """
    secret = settings.chatwoot_webhook_secret
    if not secret:
        return True

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)
