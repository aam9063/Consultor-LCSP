# Feature: Consultor LCSP — Fase 1 (MVP)

Spec: `BRIEF.md` (producto) + `AGENTS.md` (stack, TDD, RDD, Git). Este documento manda sobre el orden de trabajo.
Ejecución: **en paralelo con Radar de Pliegos, por decisión explícita de Albert (L2)**, no como proyecto secundario.

**Objetivo (BRIEF §4, literal):**

> - Respuestas en menos de 10 segundos, donde **cada afirmación** lleva al menos una cita `[art. X.Y]` que existe en el texto recuperado.
> - Abstención correcta: si la pregunta no tiene base en la LCSP, lo dice en vez de inventar.
> - Evaluación con 25 preguntas anotadas: recall@5 del artículo correcto, % de respuestas con todas las citas válidas y % de abstenciones correctas.

**Problema (BRIEF §2, literal):**

> - La LCSP tiene más de 340 artículos más disposiciones adicionales y transitorias. Las dudas del día a día (umbrales, plazos, garantías, penalidades) obligan a buscar a mano o a preguntar a alguien que se la sabe.
> - Un chat genérico responde con seguridad, pero cita artículos que no existen o versiones antiguas, y no dice cuándo no lo sabe.
> - En un equipo jurídico o de licitaciones, una respuesta sin artículo no sirve: hay que poder justificarla.

## Specs

### Requisitos de alcance (BRIEF §5, literal)

- **S1 · Ingesta de la ley.**
  > - Texto consolidado de la LCSP descargado a mano del BOE (identificador `BOE-A-2017-12902`, en HTML o XML) y guardado en `data/lcsp/`.
  > - Comando `uv run python -m app.ingest data/lcsp/<fichero>` que parsea la estructura: libro, título, capítulo, sección, artículo, apartado y disposiciones.
  > - Unidad de recuperación (chunk): el **artículo**; si un artículo supera unos 1.500 tokens, se divide por apartados sin partir ninguno.
  > - Metadatos por chunk: número de artículo, título, ruta jerárquica, apartado si aplica, URL con ancla al BOE y fecha de la versión consolidada.
  > - La ingesta es idempotente: ejecutarla dos veces no duplica nada.
- **S2 · Índice híbrido en Postgres.**
  > - Embeddings con el modelo `qwen3-embedding` de NaN Builders (4.096 dimensiones) guardados con `pgvector`.
  > - Con 4.096 dimensiones los índices HNSW e IVFFlat de pgvector no aplican (su límite es inferior), así que se usa **búsqueda exacta**. Con unos 500 chunks es rápida de sobra.
  > - Búsqueda de texto completo de Postgres con configuración `spanish` sobre el mismo corpus.
  > - Fusión de ambos rankings con Reciprocal Rank Fusion y reordenación final con el modelo `rerank` de NaN. Se quedan los 6 mejores.
  > - Si la pregunta menciona un artículo concreto ("¿qué dice el artículo 107?"), se recupera directamente por número.
- **S3 · Respuesta con citas.**
  > - Generación con `deepseek-v4-flash`. El prompt obliga a responder **solo** con el contexto recuperado y a citar `[art. X]` o `[art. X.Y]` tras cada afirmación.
  > - Salida estructurada (`json_schema`, sin tools): `respuesta`, `citas` (lista de artículo y apartado), `abstencion: bool`, `motivo_abstencion`.
  > - **Validación en código**: toda cita debe corresponder a un chunk recuperado. Una cita inventada provoca un reintento; si persiste, la afirmación se marca como no respaldada y se muestra un aviso.
  > - **Abstención**: si la mejor puntuación del reranker queda por debajo de un umbral configurable, no se llama al LLM y se responde "No encuentro base en la LCSP para responder esto".
  > - Aviso fijo en la interfaz: no es asesoramiento jurídico.
- **S4 · Revisor de cláusulas.**
  > - Entrada: texto de una cláusula (hasta unas 800 palabras).
  > - El sistema recupera los artículos relevantes y devuelve una lista de avisos: `{tipo: posible_incumplimiento | ambiguedad | ok, explicacion, articulos_citados, cita_de_la_clausula}`.
  > - Mismas reglas: solo artículos recuperados y validados; si no hay base, "sin observaciones fundadas".
- **S5 · Frontend.**
  > - Vista de consulta: caja de pregunta, respuesta con las citas como chips y un panel lateral con el texto del artículo citado al pulsar un chip.
  > - Lista de artículos recuperados con su puntuación, plegable, para entender qué ha encontrado el sistema.
  > - Vista del revisor: área de texto para la cláusula y tarjetas de avisos con su artículo.
  > - Historial de consultas de la sesión (en memoria del navegador, sin persistir).
- **S6 · Evaluación.**
  > - `evals/preguntas.yaml` con 25 entradas: pregunta, artículos esperados, respuesta de referencia breve y si debería abstenerse.
  > - 20 preguntas con base en la ley y 5 fuera de ella (por ejemplo, sobre el IVA o sobre derecho laboral).
  > - Comando `uv run python -m evals.run` que genera `evals/results/<fecha>.md` con recall@5, % de citas válidas, % de abstención correcta y los peores casos.
  > - Usa la API real; no corre en el CI por defecto (solo `workflow_dispatch` con el secreto `NAN_API_KEY`).

Nota sobre S6: los ejemplos de partida del BRIEF §5 ("penalidades por demora (art. 193), ...") se **confirman contra el texto del BOE** al anotar, tal como pide el propio BRIEF.

### Criterios de aceptación (BRIEF §10, literal)

- **S7 · AC-01 Arranque.** Dado el repo recién clonado con `.env` copiado de `.env.example`, cuando ejecuto `docker compose up -d`, entonces `api`, `web` y `db` (con la extensión `vector` creada) quedan sanos y `GET /health` devuelve 200.
- **S8 · AC-02 Parser.** Dado un fragmento de la ley en fixture con 3 artículos, uno de ellos con apartados, cuando lo parseo, entonces obtengo los chunks con número, título, apartado y ruta correctos.
- **S9 · AC-03 Idempotencia.** Dada la ley ya ingerida, cuando repito la ingesta, entonces el número de chunks no cambia.
- **S10 · AC-04 Recuperación directa.** Dada la pregunta "¿Qué dice el artículo 107?", cuando consulto, entonces el primer chunk recuperado es el art. 107.
- **S11 · AC-05 Fusión y rerank.** Dados dos rankings falsos, cuando aplico RRF y el reranker falso, entonces el orden final coincide con el esperado en el test.
- **S12 · AC-06 Citas válidas.** Dada una respuesta del LLM (falso) que cita un artículo no recuperado, cuando se valida, entonces se reintenta una vez y, si persiste, la afirmación queda marcada como no respaldada.
- **S13 · AC-07 Abstención.** Dada una pregunta cuya mejor puntuación de rerank queda bajo el umbral, cuando consulto, entonces la respuesta es una abstención y **no** se llama al LLM de generación.
- **S14 · AC-08 Revisor.** Dada una cláusula de prueba, cuando la reviso con el LLM falso, entonces devuelvo avisos tipados y cada artículo citado pertenece a los recuperados.
- **S15 · AC-09 UI de citas.** Dada una respuesta con dos citas, cuando pulso un chip, entonces el panel lateral muestra el texto de ese artículo. (Test de componente con Vitest y un e2e con Playwright.)
- **S16 · AC-10 Evaluación.** Dadas las 25 preguntas, cuando ejecuto `uv run python -m evals.run`, entonces se genera el informe. Objetivos: recall@5 ≥ 85%, citas válidas ≥ 95%, abstención correcta en al menos 4 de 5 preguntas fuera de la ley. Si no se alcanzan, el informe explica por qué. (Prueba manual, con evidencia en el feature document.)
- **S17 · AC-11 CI en verde.** Dado un push a una rama `feat/*`, cuando corre GitHub Actions, entonces pasan lint, tipos, tests de backend (con Postgres + pgvector como servicio) y frontend y build, sin usar `NAN_API_KEY`.
- **S18 · AC-12 README.** Explica cómo arrancar, cómo ingerir la ley y cómo evaluar, en pocos comandos, y muestra las últimas métricas.

## Non-goals (BRIEF §6, aplican como prohibiciones)

Otras leyes o normativa (solo LCSP consolidada); descarga automática del BOE en runtime; multi-turno; autenticación o persistencia del historial; LangChain/LlamaIndex/LangGraph; bases vectoriales externas; fine-tuning; presentar respuestas como asesoramiento jurídico; llamadas reales a la IA en tests de CI.

## Restricciones (BRIEF §7 y AGENTS.md)

- Límites NaN Builders: 60 req/min y 7 concurrentes por clave; rerank hasta 1.000/min. Ingesta de embeddings por lotes con backoff ante 429.
- Stack y versiones fijadas según `AGENTS.md` §2. Sin dependencias nuevas sin justificar aquí una línea.
- Todo LLM detrás del puerto `LLMClient` (`NanLLMClient` real / `FakeLLMClient` de tests).

## Configuración de proceso

- **TDD: activado.** Fuente: `AGENTS.md` §4. Runners: `uv run pytest` (backend), `pnpm vitest run` (frontend), `pnpm playwright test` (e2e). Se anota por tarea: test escrito, salida RED, salida GREEN.
- **RDD: activado** (`gentle-ai review mode status` → on, decidido por global, 2026-11-12). Tras cada work-unit commit: `gentle-ai review assess`. Al cerrar el slice completo: revisión 4R obligatoria.
- **Git:** ramas `feat/cl-xx-*` desde `dev`; nunca commit en `main`/`dev`; push y PR solo con el sí explícito de Albert.

## Tasks

| ID | Tarea | Specs | Ruta | Commit |
| --- | --- | --- | --- | --- |
| CL-01 | Esqueleto del monorepo, Docker Compose con pgvector, `/health`, CI mínimo | S1(parcial), S7, S17 | pendiente | — |
| CL-02 | Parser de la LCSP y modelo `chunk` | S1, S8 | pendiente | — |
| CL-03 | Ingesta idempotente con embeddings y `tsvector` | S1, S2, S9 | pendiente | — |
| CL-04 | Recuperación híbrida, RRF, rerank y búsqueda por número | S2, S10, S11 | pendiente | — |
| CL-05 | Generación con citas, validación y abstención | S3, S12, S13 | pendiente | — |
| CL-06 | Revisor de cláusulas | S4, S14 | pendiente | — |
| CL-07 | Frontend: consulta con chips y panel, revisor, historial | S5, S15 | pendiente | — |
| CL-08 | Set de 25 preguntas y evaluación | S6, S16 | pendiente | — |
| CL-09 | README y cierre de la Fase 1 | S18 | pendiente | — |

## Evidencias de verificación

### CL-01 · Esqueleto, Compose con pgvector, `/health`, CI mínimo

**Slice (bootstrap).** 5 commits en `feat/cl-01-skeleton`, 2.411 líneas autoradas sin lockfiles. El slice excede la guía de ~400 líneas porque es el andamiaje base del monorepo; los slices siguientes vuelven a la guía.

- `2084cfa` feat(api): health endpoint, settings y migración pgvector
- `aaade50` chore(deps): lockfile backend
- `b0477cb` feat(web): shell Vite + Tailwind + estado de API
- `9be8ab0` chore(deps): lockfile frontend
- `029f413` feat(infra): Compose y CI

**TDD (RED → GREEN observados)**

| Regla | RED | GREEN |
| --- | --- | --- |
| `GET /health` → 200 `{"status":"ok"}` | `assert 404 == 200` | 1 passed |
| Defaults de configuración + lectura de entorno | `ModuleNotFoundError: app.config` | 3 passed |
| Shell de la UI: título, aviso legal, API caída | módulo `src/app/App` inexistente | 2 passed |
| Extensión `vector` instalada (integración) | `NoResultFound` en `pg_extension` | pass tras `alembic upgrade head` |

**Checks ejecutados** (todos en verde)

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --strict app tests`
- `uv run pytest` (3) y `uv run pytest tests/integration` (1) contra Postgres 18 + pgvector local
- `pnpm lint`, `pnpm typecheck`, `pnpm vitest run` (2), `pnpm build`, `pnpm format:check`
- `docker compose config`; `docker compose build`; `docker compose up -d --wait` → db/api/web `healthy`; `GET :8001/health` → 200; `GET :8080/` → 200; `GET :8080/api/health` → 200
- `actionlint` (imagen `rhysd/actionlint`) sobre `.github/workflows/ci.yml` sin errores

**Defectos encontrados y corregidos durante la verificación**

- Postgres 18 cambia el punto de montaje: `pgdata:/var/lib/postgresql` (el contenedor salía con código 1).
- `wget http://localhost/` fallaba dentro de nginx (IPv6): healthcheck a `127.0.0.1` y `listen [::]:80`.

**Desviaciones justificadas**

- TypeScript fijado en `6.0.3`: `typescript-eslint` no soporta TS 7.0 (error explícito del plugin).
- Puertos de host `5433` (db), `8001` (api) y `8080` (web) porque Radar de Pliegos ocupa 5432/8000/5173 en esta máquina.
- Job e2e (Playwright) se añade en CL-07, cuando exista la suite.
- `.env.example`: **no se pudo crear** (política de rutas sensibles del harness bloquea el fichero). Compose funciona con valores por defecto; AC-01 pide explícitamente el fichero. Pendiente de decisión.

**RDD**

- `gentle-ai review assess --base-ref 2225e7b --committed-only` → `high` (`process_boundary` en `backend/entrypoint.sh`, `shell_source` en `.github/workflows/ci.yml`).
- Revisión del candidato completo (52 ficheros, 5.106 líneas): **stop nativo** `lens_context_budget_exceeded`; por eso se dividió en 5 commits y se revisa por slice.
- Slice API (`2225e7b..2084cfa`, 565 líneas, lentes `risk` + `resilience`, lineage `review-3d828745be58ead1`): 2 revisores + refutador ejecutados. **1 hallazgo severo corroborado**: `R4-async-singleton-race` (singletons `_engine`/`_session_factory` inicializados lazy sin cerrojo → carrera que puede crear dos engines). Estado nativo: `correction_required`.
- El `STATUS` de esa lineage pide además una decisión de *intended-untracked* sobre dos mockups que no generé yo: `frontend/docs/mock/LcspConsulta.dc.html` y `frontend/docs/mock/LcspRevisor.dc.html`.
- Slices `web` (`aaade50..b0477cb`) e `infra` (`9be8ab0..029f413`) sin revisar todavía: la authority del slice API sigue abierta en `correction_required`.

## Progreso y siguiente paso

- Progreso: 1/9 tareas implementada y verificada (CL-01); RDD abierto con una corrección acotada pendiente.
- RDD pendiente: (a) aplicar la corrección de `R4-async-singleton-race` (cerrojo async en la inicialización del engine, con test), (b) decidir si los dos mockups entran en la candidata, (c) revisar los slices `web` e `infra`.
- Siguiente paso: arrancar CL-02 (parser de la LCSP) en cuanto se cierre la revisión de CL-01.

## Log

- **L1 (solicitud original de Albert, literal):** "Lee el BRIEF.md y el AGENTS.md y aunque en el brief ponga que este proyecto se va a empezar si se acaba primero el de radar de pliegos, no va a ser asi, vas a hacerlo a la vez que se hace el otro"
- **L2 (decisión de alcance, 2026-11-12):** queda anulada la premisa del BRIEF "(Proyecto secundario: se hace solo si Radar de Pliegos tiene la Fase 1 cerrada...)" y la dependencia "Fase 2 · Extensión (solo con la Fase 1 cerrada y en verde)" en lo que respecta al calendario: Consultor LCSP Fase 1 avanza **en paralelo** con Radar de Pliegos. El resto del BRIEF (alcance, non-goals, criterios de aceptación) no cambia.
- **L3 (hecho, 2026-11-12):** leídos `BRIEF.md` y `AGENTS.md` completos; entorno verificado: uv 0.12.10, Python 3.14.5, Node v24.22.1, pnpm 11.4.0, Docker 29.9.3, RDD on. Repo sin commits, sin ramas locales, remoto `github.com/aam9063/Consultor-LCSP` vacío.
- **L4 (decisión de Albert, 2026-11-12):** bootstrap de Git = commit inicial en `main` (AGENTS.md, BRIEF.md, `.gitignore`), luego `dev` y trabajo en `feat/cl-01-skeleton`. Ejecutado: `2225e7b` en `main`, `dev` y `feat/cl-01-skeleton` desde ahí.
- **L5 (hallazgo, 2026-11-12):** aparecen sin commitear `frontend/docs/mock/LcspConsulta.dc.html` y `frontend/docs/mock/LcspRevisor.dc.html` (mockups de la UI, no generados por el agente). Quedan fuera de los commits de CL-01 a la espera de decisión.
