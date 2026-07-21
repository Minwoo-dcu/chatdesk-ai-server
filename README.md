# Chatdesk AI Server

Chatwoot Agent Bot 웹훅을 수신해 AI 응답을 자동 전송하는 FastAPI 서버.

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- Pydantic Settings
- Groq API (LLM)
- Chatwoot Agent Bot (webhook)

## Project Structure

```
app/
├── main.py                 # FastAPI 앱 생성, 라우터 등록
├── config.py               # .env 값 로딩 (pydantic-settings)
├── routers/
│   └── webhook.py          # POST /webhook/chatwoot 엔드포인트
├── services/
│   ├── chatwoot_client.py  # Chatwoot API 호출 (메시지 전송)
│   ├── llm_client.py       # LLM 연동 인터페이스
│   └── verify.py           # 웹훅 HMAC-SHA256 서명 검증
└── models/
    └── schemas.py          # Chatwoot 웹훅 페이로드 Pydantic 모델
tests/
└── test_webhook.py         # 엔드포인트 테스트
```

## Setup

```bash
# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 패키지 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일을 열어 값 채우기
```

## Environment Variables

| 변수명                    | 필수 | 설명                                                                |
| ------------------------- | ---- | ------------------------------------------------------------------- |
| `CHATWOOT_API_URL`        | ✅   | Chatwoot 서버 주소 (예: `http://localhost:3000`)                    |
| `CHATWOOT_API_TOKEN`      | ✅   | Chatwoot Profile Settings의 Access Token                            |
| `CHATWOOT_WEBHOOK_SECRET` | -    | Agent Bot Webhook Secret (비우면 검증 생략)                         |
| `GROQ_API_KEY`            | -    | Groq API 키 ([Groq Console](https://console.groq.com/keys))         |

### 웹훅 서명 검증 방식

Chatwoot는 `X-Chatwoot-Signature`(`sha256=<hex>`), `X-Chatwoot-Timestamp` 헤더를 함께 보냅니다.
서명 대상 메시지는 raw body 단독이 아니라 `"{timestamp}.{raw_body}"` 형식이며,
`app/services/verify.py`가 이 규칙으로 HMAC-SHA256을 재계산해 비교합니다.
`CHATWOOT_WEBHOOK_SECRET`이 비어있으면 검증 자체를 생략합니다(로컬 개발용).

## Run

```bash
# 개발 서버 실행
uvicorn app.main:app --reload

# 포트 지정
uvicorn app.main:app --reload --port 8080
```

## Chatwoot Agent Bot 연동

1. Chatwoot → **Settings → Agent Bots → New Agent Bot**
2. Webhook URL: `https://<your-domain>/webhook/chatwoot`
   - 로컬 개발 시: [localtunnel](https://localtunnel.github.io/) 또는 ngrok으로 터널링
   ```bash
   # --subdomain 으로 고정 URL 사용 (매번 바뀌지 않음)
   npx localtunnel --port 8080 --subdomain chatdesk-ai-nanoiti
   # → https://chatdesk-ai-nanoiti.loca.lt/webhook/chatwoot
   ```
3. 생성된 **Webhook Secret**을 `.env`의 `CHATWOOT_WEBHOOK_SECRET`에 입력
4. **Settings → Inboxes → (Inbox 선택) → Configuration → Agent Bot** 에서 봇 연결

## Webhook Flow

```
고객 메시지
  → Chatwoot Agent Bot
  → POST /webhook/chatwoot
  → 서명 검증 → 이벤트 필터 (incoming만)
  → llm_client.get_ai_response()
  → Chatwoot API 응답 전송
```

## LLM Interface

`app/services/llm_client.py`에서 아래 함수 시그니처를 유지하며 Groq API로 구현:

```python
async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    ...
```

## Branch Strategy

- `main` — 항상 동작 상태 유지
- `feature/*` — 기능 개발 브랜치
- 커밋 prefix: `feat:`, `fix:`, `docs:`
