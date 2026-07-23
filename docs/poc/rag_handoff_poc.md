# RAG 기반 AI 상담사 핸드오프 PoC

## 개요

A-5 시나리오는 AI가 자체적으로 답변하기 어려운 질문을 받았을 때,
잘못된 정보를 생성(Hallucination)하지 않고 내부 문서(RAG) 또는 연동 API를 우선 조회한 뒤,
필요한 정보를 찾지 못하면 상담사에게 핸드오프(Handoff)하는 기능을 정의한다.

현재 프로젝트에서는 RAG 및 외부 API가 아직 구현되지 않았으므로,
향후 개발을 위한 PoC(Proof of Concept) 문서로 작성한다.

---

## 목적

다음과 같은 상황에서 AI가 추측하여 답변하지 않도록 한다.

- 상품 상세 정보
- 재고 조회
- 주문 상태 조회
- 배송 조회
- 오류 해결
- 내부 문서에 존재하지 않는 질문

---

## 처리 흐름

```text
사용자 질문
      │
      ▼
 AI 응답 요청
      │
      ▼
 RAG 문서 검색
      │
      ├───────────────┐
      │               │
문서 존재         문서 없음
      │               │
      ▼               ▼
신뢰도 확인        API 조회
      │               │
      │         ┌─────┴─────┐
      │         │           │
      ▼         ▼           ▼
신뢰도 높음   조회 성공   조회 실패
      │         │           │
      ▼         ▼           ▼
 AI 응답     AI 응답     상담사 이관
```

---

## 핸드오프 조건

| 조건 | 설명 |
|------|------|
| RAG 검색 결과 없음 | 관련 문서를 찾지 못한 경우 |
| 신뢰도 기준 미달 | 검색 결과는 있으나 신뢰도가 낮은 경우 |
| API 미연동 | 필요한 API가 아직 구현되지 않은 경우 |
| API 조회 실패 | Timeout 또는 Server Error 발생 |
| 동일 오류 2회 이상 | AI가 해결을 시도했지만 해결하지 못한 경우 |

---

## 예시 시나리오

### Case 1 : 재고 조회

**사용자**

> 갤럭시 S26 Ultra 재고 있나요?

처리 순서

1. RAG 검색
2. 검색 결과 없음
3. 재고 API 호출
4. API 미연동
5. 상담사 핸드오프

AI 응답

> 현재 재고 정보를 확인할 수 없습니다.
> 정확한 안내를 위해 상담사에게 연결해드리겠습니다.

---

### Case 2 : 환불 규정

**사용자**

> 환불 규정 알려주세요.

처리 순서

1. RAG 검색
2. 환불 정책 문서 검색 성공
3. AI 답변

---

### Case 3 : 배송 조회

**사용자**

> 주문번호 12345 배송 어디까지 왔나요?

처리 순서

1. 배송 API 조회
2. 조회 성공
3. AI 답변

---

## 향후 구현 방향

예상 디렉터리 구조

```text
app/
├── rag/
│   ├── retriever.py
│   ├── embeddings.py
│   └── vector_store.py
│
├── api/
│   ├── inventory.py
│   └── order.py
│
└── services/
    └── handoff_service.py
```

---

## 의사 코드(Pseudo Code)

```python
result = rag.search(question)

if result.exists and result.score >= 0.7:
    return answer(result)

api = inventory.search(question)

if api.success:
    return answer(api.data)

return handoff_to_agent(reason="RAG_NO_RESULT")
```

---

## 기대 효과

- AI Hallucination 감소
- 정확한 정보 제공
- 상담사 업무 효율 향상
- 향후 RAG 및 외부 API 연동이 쉬운 구조 제공