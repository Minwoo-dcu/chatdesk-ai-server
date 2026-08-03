# Chatdesk AI Server

Chatwoot Agent Bot 웹훅을 수신해 AI 응답을 자동 전송하는 FastAPI 서버.

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- Pydantic Settings
- Groq API / Gemini API (LLM, .env로 선택)
- Chatwoot Agent Bot (webhook)

## Project Structure

```
app/
├── main.py                    # FastAPI 앱 생성, 라우터 등록
├── config.py                  # .env 값 로딩 (pydantic-settings)
├── routers/
│   └── webhook.py             # POST /webhook/chatwoot 엔드포인트, 전체 오케스트레이션
├── services/
│   ├── chatwoot_client.py     # Chatwoot API 호출 (메시지 전송/조회/배정/라벨 등)
│   ├── llm_client.py          # Groq/Gemini LLM 연동 (get_ai_response, confirm_intent)
│   ├── verify.py              # 웹훅 HMAC-SHA256 서명 검증
│   ├── handoff_rules.py       # 핸드오프 규칙(A-1~A-4): 보안/컴플레인/상담원 연결
│   ├── rag_handoff.py         # RAG 지식베이스 기반 즉답/핸드오프 판단(A-5)
│   ├── knowledge_base.py      # 지식베이스(JSON) 키워드 검색
│   ├── business_hours.py      # Chatwoot 인박스 설정 기반 영업시간 판단
│   ├── conversation_state.py  # 인사/문의유형 상태 (인메모리)
│   └── prompts.py             # 시스템 프롬프트, 인사말, 문의유형 버튼 정의
└── models/
    └── schemas.py             # Chatwoot 웹훅 페이로드 Pydantic 모델
docs/
├── glossary.md                # 용어/표기 규약
└── poc/                       # RAG 지식베이스 등 PoC 문서
tests/
├── test_webhook.py            # 웹훅 엔드포인트 통합 테스트
└── test_history.py            # 대화 이력 변환(build_history) 단위 테스트
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
| `CHATWOOT_API_TOKEN`      | ✅   | User 토큰 (Profile Settings > Access Token). 배정·라벨·우선순위 등 관리 API용 |
| `CHATWOOT_BOT_TOKEN`      | -    | AgentBot access_token (Settings > Bots). 봇 응답을 봇 명의로 전송. 비우면 API_TOKEN 폴백 |
| `CHATWOOT_WEBHOOK_SECRET` | -    | Agent Bot Webhook Secret (비우면 검증 생략)                         |
| `LLM_PROVIDER`            | ✅   | LLM 선택 (`groq` 또는 `gemini`)                                     |
| `GROQ_API_KEY`            | -    | Groq API 키 ([Groq Console](https://console.groq.com/keys)). LLM_PROVIDER=groq 시 필수 |
| `GEMINI_API_KEY`          | -    | Gemini API 키 ([Google AI Studio](https://aistudio.google.com/app/apikey)). LLM_PROVIDER=gemini 시 필수 |
| `GROQ_MODEL_DEFAULT`      | -    | Groq 기본 모델 (기본값: `llama-3.1-8b-instant`)                     |
| `GROQ_MODEL_RAG`          | -    | Groq RAG 모델 (기본값: `llama-3.1-8b-instant`)                      |
| `GEMINI_MODEL_DEFAULT`    | -    | Gemini 기본 모델 (기본값: `gemini-3.5-flash`)                       |
| `GEMINI_MODEL_RAG`        | -    | Gemini RAG 모델 (기본값: `gemini-3.5-flash`)                        |
| `GEMINI_MODEL_QUICK`      | -    | Gemini 빠른 응답 모델 (기본값: `gemini-3.5-flash`)                  |

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

### Docker로 실행

```bash
# .env 준비 (Setup 단계와 동일)
docker compose up --build
```

`docker-compose.yml`이 `.env`를 그대로 컨테이너에 주입하고 8000 포트로 서비스합니다.
`.dockerignore`로 `.env`/`.venv`/`.git`/tests 등은 이미지 빌드에서 제외됩니다.

## Chatwoot Agent Bot 연동

1. Chatwoot → **Settings → Agent Bots → New Agent Bot**
2. Webhook URL: `https://<your-domain>/webhook/chatwoot`
   - 로컬 개발 시: **ngrok**으로 터널링 (localtunnel은 응답이 느려 Chatwoot 웹훅 dispatch가
     `Net::OpenTimeout`으로 실패하는 경우가 있어 비권장)
   ```bash
   # 최초 1회: https://dashboard.ngrok.com/get-started/your-authtoken 에서 발급
   ngrok config add-authtoken <YOUR_AUTHTOKEN>

   # 서버 실행 후 별도 터미널에서
   ngrok http 8080
   # → 출력된 https://<random>.ngrok-free.dev 를 Webhook URL에 사용
   ```
   - ngrok 무료 플랜은 재시작할 때마다 URL이 바뀜 — 재시작 때마다 Chatwoot Agent Bot의
     Webhook URL을 새 주소로 다시 저장해야 함
   - 자체호스팅 Chatwoot는 웹훅 URL이 사설 IP/내부 도메인으로 resolve되면
     SSRF 방지 로직에 의해 강제로 거부됨(`Hostname ... has no public ip addresses`).
     같은 도커 네트워크에 붙여 내부 호스트네임으로 직접 호출하는 방식은 동작하지 않으므로
     반드시 공인 도메인(ngrok 등)을 통해야 함
3. 생성된 **Webhook Secret**을 `.env`의 `CHATWOOT_WEBHOOK_SECRET`에 입력
4. **Settings → Inboxes → (Inbox 선택) → Configuration → Agent Bot** 에서 봇 연결

## Webhook Flow

```
고객 메시지
  → Chatwoot Agent Bot → POST /webhook/chatwoot
  → 서명 검증 → 이벤트 필터 (incoming만)
  → 이미 사람이 담당 중? ─── 예 → AI 응답 생략, 종료
  → 영업시간 외? ────────── 예 → 안내 메시지, 종료
  → 핸드오프 규칙 매칭? (A-1~A-4: 보안/컴플레인/연결) ─ 예 → 온라인 상담원 배정 또는 대기 라벨, 종료
  → RAG 지식베이스 매칭? (A-5)
      ├─ confidence 높음 → 즉답, 종료
      └─ 낮음/DB조회 필요 → 핸드오프, 종료
  → 위 전부 해당 없음 → llm_client.get_ai_response() → Chatwoot API 응답 전송
```

### 위젯 오픈 시 선제 인사 (webwidget_triggered)

방문자가 웹 위젯을 열면 `webwidget_triggered` 이벤트가 수신되며, 봇이 먼저
인사 메시지와 문의유형 선택 버튼(`input_select`)을 전송합니다. 인사 문구/버튼 항목은
`app/services/prompts.py`(`GREETING_MESSAGE`, `INQUIRY_ITEMS`)에 정의되어 있습니다.
중복 인사 방지 상태는 `app/services/conversation_state.py`의 인메모리 저장소로 관리하며,
**서버 재시작 시 초기화**됩니다(영구성 필요 시 Redis 등으로 교체).
선택한 문의유형은 이후 `get_ai_response` 호출 시 메시지 컨텍스트로 주입됩니다.

## LLM Interface

`app/services/llm_client.py`에서 아래 함수 시그니처를 유지하며 Groq/Gemini API로 구현:

```python
async def get_ai_response(
    message: str,
    conversation_id: int,
    history: list[dict],
) -> str:
    ...
```

`.env`의 `LLM_PROVIDER`로 LLM 선택:
- `groq` — Groq API (Llama 모델)
- `gemini` — Google Gemini API (google-genai 라이브러리)

각 LLM별 모델명도 `.env`에서 설정 가능하여, 코드 수정 없이 모델 변경 가능.

## 참고 문서

- [docs/glossary.md](docs/glossary.md) — 용어/표기 규약 (핸드오프, 문의유형, 인텐트 분류 정의)
- [docs/poc/](docs/poc/) — RAG 지식베이스 PoC 관련 문서

## Branch Strategy

- `main` — 항상 동작 상태 유지
- `feature/*` — 기능 개발 브랜치
- 커밋 prefix: `feat:`, `fix:`, `docs:`
