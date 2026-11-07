# Evaluation results (offline)

Run: 2026-11-07 18:30 | embedding backend: `tfidf (offline fallback)` | 30 inquiries (20 clear, 5 vague, 5 off-scope)

## Extraction field accuracy

| Field | Correct | Accuracy |
|---|---|---|
| Industry | 22/25 | 88% |
| Primary need type detected | 14/22 | 64% |
| Urgency | 24/25 | 96% |
| Budget present | 27/30 | 90% |
| Decision-maker present | 29/30 | 97% |
| Off-scope flag | 29/30 | 97% |

## Retrieval (25 inquiries with a labelled best case study)

| Metric | Value |
|---|---|
| Hit@1 | 88% |
| **Hit@3** | **96%** |
| Hit@3 (20 clear only) | 95% |
| MRR | 0.92 |

### Retrieval ablation (Hit@3)

| Variant | Hit@3 |
|---|---|
| Dense only | 96% |
| BM25 only | 92% |
| Hybrid (RRF) | 96% |
| Hybrid + industry boost (default) | 100% |

## Generation & operations

| Metric | Value |
|---|---|
| Faithfulness (share of draft numbers traceable to sources or the inquiry) | 100% |
| Drafts passing the guardrail (no unverified numbers or invalid citations) | 100% |
| Latency p50 / p95 | 15 ms / 19 ms |
| Mean tokens per request | 0 |
| Mean cost per request (list prices) | $0.00000 |

_No-RAG baseline comparison needs an LLM: set GROQ_API_KEY and re-run `python -m eval.run_eval`._

## Failure cases

- **Q20** (clear): expected ['CS-05'], got []
- **Q01** industry: expected `healthcare`, extracted `None`
- **Q05** industry: expected `fashion`, extracted `ecommerce_retail`
- **Q20** industry: expected `fashion`, extracted `None`

## Per-inquiry results

| ID | Cat. | Top-3 retrieved | Expected | Score | Tier | Route | Faith. |
|---|---|---|---|---|---|---|---|
| Q01 | clear | CS-01, CS-03, CS-09 | CS-01 | 77 | hot | AI & Data Pod | 1.00 |
| Q02 | clear | CS-02, CS-12, CS-01 | CS-02 | 63 | warm | Healthcare & Life Sciences Pod | 1.00 |
| Q03 | clear | CS-03, CS-01, CS-08 | CS-03 | 73 | hot | AI & Data Pod | 1.00 |
| Q04 | clear | CS-04, CS-11, CS-09 | CS-04 | 73 | hot | Platforms & Engineering Pod | 1.00 |
| Q05 | clear | CS-05, CS-10, CS-11 | CS-05 | 80 | hot | Commerce & Retail Pod | 1.00 |
| Q06 | clear | CS-06, CS-11, CS-01 | CS-06 | 53 | warm | Platforms & Engineering Pod | 1.00 |
| Q07 | clear | CS-07, CS-13, CS-01 | CS-07 | 53 | warm | Platforms & Engineering Pod | 1.00 |
| Q08 | clear | CS-08, CS-10, CS-09 | CS-08 | 60 | warm | Platforms & Engineering Pod | 1.00 |
| Q09 | clear | CS-09, CS-03, CS-04 | CS-09 | 69 | warm | Platforms & Engineering Pod | 1.00 |
| Q10 | clear | CS-05, CS-10, CS-07 | CS-10 | 78 | hot | Commerce & Retail Pod | 1.00 |
| Q11 | clear | CS-11, CS-10, CS-03 | CS-11 | 65 | warm | Commerce & Retail Pod | 1.00 |
| Q12 | clear | CS-12, CS-01, CS-02 | CS-12 | 73 | hot | Healthcare & Life Sciences Pod | 1.00 |
| Q13 | clear | CS-13, CS-10, CS-09 | CS-13 | 83 | hot | Fintech & Payments Pod | 1.00 |
| Q14 | clear | CS-02, CS-01, CS-12 | CS-01 | 63 | warm | Healthcare & Life Sciences Pod | 1.00 |
| Q15 | clear | CS-11, CS-10, CS-08 | CS-11 | 65 | warm | Commerce & Retail Pod | 1.00 |
| Q16 | clear | CS-13, CS-09, CS-04 | CS-13 | 83 | hot | Fintech & Payments Pod | 1.00 |
| Q17 | clear | CS-08, CS-07, CS-09 | CS-08 | 62 | warm | Platforms & Engineering Pod | 1.00 |
| Q18 | clear | CS-04, CS-05, CS-10 | CS-04 | 50 | warm | Platforms & Engineering Pod | 1.00 |
| Q19 | clear | CS-03, CS-06, CS-01 | CS-03 | 83 | hot | AI & Data Pod | 1.00 |
| Q20 | clear | - | CS-05 | 0 | cold | Inbound Desk | 1.00 |
| Q21 | vague | CS-12, CS-01, CS-02 | CS-01, CS-02, CS-12 | 32 | cold | Marketing Nurture | 1.00 |
| Q22 | vague | CS-02, CS-08, CS-10 | - | 12 | cold | Marketing Nurture | 1.00 |
| Q23 | vague | CS-11, CS-05, CS-10 | CS-10, CS-11, CS-05 | 32 | cold | Marketing Nurture | 1.00 |
| Q24 | vague | CS-01, CS-03, CS-08 | CS-01, CS-03, CS-08 | 25 | cold | Marketing Nurture | 1.00 |
| Q25 | vague | CS-08, CS-05, CS-07 | CS-08 | 40 | warm | Platforms & Engineering Pod | 1.00 |
| Q26 | off_scope | - | - | 0 | cold | Inbound Desk | 1.00 |
| Q27 | off_scope | - | - | 20 | cold | Inbound Desk | 1.00 |
| Q28 | off_scope | - | - | 0 | cold | Inbound Desk | 1.00 |
| Q29 | off_scope | - | - | 0 | cold | Inbound Desk | 1.00 |
| Q30 | off_scope | - | - | 0 | cold | Inbound Desk | 1.00 |
