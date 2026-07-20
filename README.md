# Chatdesk AI Server

## Overview
Chatwoot와 LLM 사이에서 AI 기능을 담당하는 서버.

## Role
- 사용자 메시지 처리
- LLM API 연동
- 자동 응답 생성
- 상담원 연결 판단
- 대화 분석

## Architecture

User 
↓
Chatwoot
↓
AI Server(FastAPI)
↓
LLM
↓
Response

