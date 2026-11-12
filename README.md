# Consultor LCSP

An assistant that answers questions about the **Ley 9/2017, de Contratos del Sector Público**
(LCSP) citing the exact article for every claim, and that refuses to answer when the statute
does not support an answer. It also reviews a clause from a tender document and flags possible
conflicts with the law, each one with its article.

> This is a learning project inspired by Themia (Crata AI). **It is not legal advice**: always
> check the consolidated text at the BOE.

## What it does

- **Consulta** — ask in natural language; the answer carries `[art. X]` / `[art. X.Y]` citations
  as chips, and clicking one opens the article text in a side panel.
- **Revisor de cláusulas** — paste a clause (up to ~800 words) and get typed warnings
  (`posible_incumplimiento`, `ambiguedad`, `ok`) with the articles that support them and the
  literal fragment of the clause they refer to.
- **Abstention** — if nothing relevant is retrieved, or the best rerank score is below the
  calibrated threshold, the answer is exactly `No encuentro base en la LCSP para responder esto`
  and the generation model is never called.

Everything the model asserts is validated in code: a citation that does not belong to a retrieved
article triggers one retry, and if it persists the answer becomes an abstention.

## Stack

Backend: Python 3.14, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 18 with `pgvector`.
Frontend: React 19, Vite, TypeScript strict, TanStack Query, Tailwind CSS.
AI: NaN Builders through the official `openai` SDK — `qwen3-embedding` (4096 dims), `rerank`,
`deepseek-v4-flash` for generation. No RAG framework: SQL and a typed port.

## Quick start

```bash
cp .env.example .env          # then put your NAN_API_KEY in it
docker compose up -d --wait   # db, api and web, all with healthchecks
curl localhost:8001/health    # {"status":"ok"}
```

The web UI is at `http://localhost:8080`. Host ports are `5433` for Postgres, `8001` for the API
and `8080` for the UI so the stack can run alongside other local projects.

## Ingest the statute

The consolidated text is downloaded per machine, never committed (see `data/lcsp/README.md`):

```bash
mkdir -p data/lcsp
curl -L -H 'Accept: application/xml' \
  https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-2017-12902/texto \
  -o data/lcsp/lcsp-consolidada.xml

uv run --project backend python -m app.ingest data/lcsp/lcsp-consolidada.xml --dry-run
uv run --project backend python -m app.ingest data/lcsp/lcsp-consolidada.xml
```

Ingestion is idempotent: re-running it inserts nothing, re-embeds nothing, and reports the
skipped count. With the current file it produces **580 chunks** from 428 preceptos, in 37
embedding batches.

## Evaluate

```bash
# score spread of the reranker, no generation spent (calibration)
uv run --project backend python -m evals.run --calibrate

# full run: 25 annotated questions, writes evals/results/<date>.md and .json
uv run --project backend python -m evals.run
```

The run uses the real API, so it spends quota; it never runs in the normal CI.

## Latest metrics

Definitive run over the real corpus (580 chunks, real embeddings, real rerank and generation),
25 annotated questions — 20 with a basis in the statute, 5 outside it:

| Metric | Result | Goal |
| --- | --- | --- |
| Recall@5 | **97.5%** | ≥ 85% ✅ |
| Answers with every citation valid | **100%** | ≥ 95% ✅ |
| Correct abstention | **5/5** | ≥ 4/5 ✅ |

**Where the hybrid layer pays off.** Recall@5 is identical for both modes (97.5%), but that metric
is blind to ordering. Measuring the retrieval itself, without generation, over the same 20 questions:

| Mode | Recall@5 | Hit@1 | MRR |
| --- | --- | --- | --- |
| Hybrid (vector + full text + RRF + rerank) | 97.5% | **95.0%** | **0.967** |
| Embeddings only | 97.5% | 80.0% | 0.892 |

So Reciprocal Rank Fusion and the reranker buy **position**, not coverage: the right article is first
in 95% of questions instead of 80%, which is exactly what a citation-first interface needs. This
corrects an earlier conclusion drawn from `recall@5` alone. The full history of the runs — including
two measurement defects found and fixed — is in `odd/tasks/consultor-lcsp-mvp.md`.

## Data

- Questions are processed by NaN Builders' API in the **European Union**. According to the
  provider's FAQ, prompts and responses are not logged, the key is personal and non-transferable,
  and no model is trained with your data.
- What this application stores itself: the **votes** you submit on an answer (question, answer,
  citations, model, vote, optional comment), so an annotated evaluation set can be grown. Nothing
  else is persisted: no accounts, no session history.

## Configuration that matters

- `RERANK_THRESHOLD` (default **0.85**): the abstention cut-off, **calibrated** against real
  scores. Answerable questions scored at least ~0.96 in every run; out-of-law questions never went
  past ~0.76, so there is a gap of about 0.20 and the cut-off sits inside it. The reranker moves a
  few thousandths between runs, so what makes 0.85 safe is that gap, not a single exact number.
  The original 0.35 was a guess and abstained on 5 of 20 valid questions while letting 4 of 5
  out-of-law ones through.
- `RETRIEVAL_TOP_K` (default 6), `EMBEDDING_BATCH_SIZE` (default 16),
  `EMBEDDING_DIMENSIONS` (4096 — with that many dimensions the HNSW/IVFFlat indexes do not apply,
  so the vector scan is exact).

## Architecture

```
backend/app/
├── domain/      pure rules: parser, ranking (RRF), citations, clause validation
├── services/    retrieval, answers, ingestion, evaluation
├── adapters/    LLMClient port + NanLLMClient (retry, batching, typed errors)
├── api/         /health, /consultas, /revisiones, /buscar, /articulos/{numero}
└── db/          models, async session
```

`domain/` imports nothing from FastAPI, SQLAlchemy or the AI SDK: the rules that decide what is a
valid citation, how rankings fuse or when a clause warning is malformed are pure functions with
tests. Every model call goes through the `LLMClient` port, so tests use a deterministic fake and
never touch the real API.

## Commands

```bash
# backend
cd backend && uv sync
uv run alembic upgrade head
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict app tests
uv run ruff check ../evals && uv run mypy --strict ../evals
uv run pytest && uv run pytest tests/integration && uv run pytest tests/data

# frontend
cd frontend && pnpm install
pnpm lint && pnpm typecheck && pnpm vitest run && pnpm build && pnpm e2e
```

`tests/integration` needs the compose database running; `tests/data` needs the real statute in
`data/lcsp/` and validates the parser against it.

## Known limits

- Single-turn: each query is independent, there is no conversation memory.
- No authentication and no persisted history; the session history lives in browser memory.
- The e2e job runs only on pull requests, and its suite stubs the API.
- Retrieval is limited to the LCSP; no other statute, regulation or case law.

## Documentation

- `BRIEF.md` — the product specification and acceptance criteria.
- `AGENTS.md` — stack, workflow, testing and review rules.
- `odd/tasks/consultor-lcsp-mvp.md` — the feature document: tasks, evidence, every defect found.
- `docs/aprendizaje/` — one learning document per implementation: what was built, why that way,
  which errors appeared and how they were solved.
- `evals/results/` — the evaluation reports and per-question audits.
