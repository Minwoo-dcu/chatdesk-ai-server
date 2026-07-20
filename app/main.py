import logging

from fastapi import FastAPI

from app.routers import webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

app = FastAPI(
    title="Chatdesk AI Server",
    version="0.1.0",
    description="Chatwoot Agent Bot 웹훅을 수신해 AI 응답을 자동 전송하는 서버",
)

app.include_router(webhook.router)


@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "message": "Chatdesk AI Server is running!"}
