# Chatdesk AI Server

Chatwoot 웹훅을 수신해 LLM 기반 자동응답을 전송하는 FastAPI 서버. 핸드오프 규칙과 RAG 지식베이스로 언제 상담원에게 넘길지 판단.

## Quick Start

```bash
# 1. 가상환경 + 패키지
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 열어서 필수값 채우기:
#   CHATWOOT_API_URL, CHATWOOT_API_TOKEN, LLM_PROVIDER, GROQ_API_KEY (or GEMINI_API_KEY)

# 3. 개발 서버 실행
uvicorn app.main:app --reload
# → http://localhost:8000 (Swagger UI: http://localhost:8000/docs)

# 4. 테스트 (선택)
pytest tests/ -v
```

Docker:
```bash
docker compose up --build
# → http://localhost:8000
```

## 동작 흐름

```
고객 메시지 (Chatwoot)
  ↓ POST /webhook/chatwoot (서명 검증)
  ↓ 이미 상담원 배정됨? ──→ 예: 생략
  ↓ 영업시간 외? ──────→ 예: 안내 메시지
  ↓ 핸드오프 규칙 (A-1~A-4)
  │  ├─ 보안/결제 → 우선순위 높게 배정
  │  └─ 상담원 연결 → 배정/대기
  ↓ RAG 지식베이스 (A-5)
  │  ├─ confidence 높음 → 자동 응답
  │  └─ 낮음 → 핸드오프
  ↓ LLM 응답 생성 + 전송
```

**위젯 오픈**: 방문자가 웹 위젯을 열면 봇이 인사 + 문의유형 선택 버튼 전송.

## 환경변수

**필수:**
- `CHATWOOT_API_URL` — Chatwoot 서버 주소 (예: `http://localhost:3000`)
- `CHATWOOT_API_TOKEN` — Chatwoot User 토큰 (Profile Settings > Access Token)
- `LLM_PROVIDER` — `groq` 또는 `gemini`
- `GROQ_API_KEY` — LLM_PROVIDER=groq 선택 시
- `GEMINI_API_KEY` — LLM_PROVIDER=gemini 선택 시

**선택:**
- `CHATWOOT_BOT_TOKEN` — AgentBot 토큰 (없으면 API_TOKEN 사용)
- `CHATWOOT_WEBHOOK_SECRET` — Agent Bot Webhook Secret (없으면 검증 생략, 로컬 개발용)
- `GROQ_MODEL_DEFAULT`, `GROQ_MODEL_RAG` — 기본값: `llama-3.1-8b-instant`
- `GEMINI_MODEL_DEFAULT`, `GEMINI_MODEL_RAG`, `GEMINI_MODEL_QUICK` — 기본값: `gemini-3.5-flash`

자세한 설명은 [.env.example](.env.example) 참고.

## 아키텍처

| 파일 | 역할 |
|------|------|
| `app/routers/webhook.py` | 웹훅 수신 + 전체 오케스트레이션 |
| `app/services/llm_client.py` | Groq/Gemini API (환경변수로 선택) |
| `app/services/handoff_rules.py` | 규칙 A-1~A-4 (보안, 상담원 연결) |
| `app/services/rag_handoff.py` | 규칙 A-5 (지식베이스 검색) |
| `app/services/chatwoot_client.py` | Chatwoot API 래퍼 |
| `app/services/verify.py` | 웹훅 HMAC-SHA256 검증 |
| `app/config.py` | 환경변수 로딩 (Pydantic Settings) |

더 자세한 구조는 [.claude/claude.md](.claude/claude.md) 참고.

## Chatwoot 연동

1. Chatwoot **Settings → Agent Bots → New Agent Bot**
2. Webhook URL: `https://<your-domain>/webhook/chatwoot`
   - 로컬 개발: ngrok 터널링
   ```bash
   ngrok http 8080
   # → https://<random>.ngrok-free.dev 복사해서 Webhook URL에 입력
   ```
3. **Webhook Secret** 복사 → `.env`의 `CHATWOOT_WEBHOOK_SECRET` 붙여넣기
4. **Settings → Inboxes → Configuration → Agent Bot** 에서 봇 연결

## 상세 문서

- [.claude/claude.md](.claude/claude.md) — 아키텍처, 웹훅 이벤트, 테스트 구조, 핸드오프 규칙 A-1~A-5, 문제 해결
- [docs/glossary.md](docs/glossary.md) — 용어/표기 규약
- [.env.example](.env.example) — 환경변수 전체 목록
