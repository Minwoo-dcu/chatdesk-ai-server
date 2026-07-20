"""
conftest.py — pytest가 app을 import하기 전에 필수 환경변수를 주입합니다.
실제 Chatwoot/Gemini 서버 없이도 테스트가 실행됩니다.
"""
import os

os.environ.setdefault("CHATWOOT_API_URL", "http://mock.chatwoot.local")
os.environ.setdefault("CHATWOOT_API_TOKEN", "mock_token")
os.environ.setdefault("CHATWOOT_WEBHOOK_SECRET", "")
os.environ.setdefault("GEMINI_API_KEY", "")
