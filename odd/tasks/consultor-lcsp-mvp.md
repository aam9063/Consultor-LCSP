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
| CL-02 | Parser de la LCSP y modelo `chunk` | S1, S8 | `1c301ec`, `ada8854` | hecho |
| CL-03 | Ingesta idempotente con embeddings y `tsvector` | S1, S2, S9 | `9d03d4a`, `b39c8c6` | hecho |
| CL-04 | Recuperación híbrida, RRF, rerank y búsqueda por número | S2, S10, S11 | `032859d`, `6a68022` | hecho |
| CL-05 | Generación con citas, validación y abstención | S3, S12, S13 | `0e8f1ff`, `19ee890` | hecho |
| CL-06 | Revisor de cláusulas | S4, S14 | `76bad65`, `2968a8b` | hecho |
| CL-07 | Frontend: consulta con chips y panel, revisor, historial | S5, S15 | `cca1d58`, `1fc24af`, `b27bd43`, `4341dab` | hecho |
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
- **Corrección aplicada** (2026-11-12): `fix(api)` guarda la inicialización del engine con `threading.Lock`. RED: con el cerrojo neutralizado se crean 4 engines para 4 hilos; GREEN: 1 engine y la misma factory (`tests/unit/test_db_session.py`, 2 tests). Checks en verde de nuevo.
- La lineage `review-3d828745be58ead1` quedó **stale**: al volver a la rama, el candidato pasó a ser todo el andamiaje (53 ficheros) y el `STATUS` respondió `action: recover`, `action_disposition: scope_changed`. Revisar slices por checkout detached no es compatible con la proyección de workspace que exige el revisor; el slice API no pudo cerrarse nativamente.

### CL-02 · Parser de la LCSP y modelo `chunk`

Slice de 2 commits (~1.300 líneas), delegado a `gentle-ai-worker` y verificado por el orquestador.

- `1c301ec` feat(domain): parser puro (solo stdlib) → `LcspChunk` con número, título, ruta, apartado, URL con ancla y fecha de versión; un chunk por artículo; corte por apartado solo si supera ~1.500 tokens.
- `ada8854` feat(db): modelos `Fuente`/`Chunk`, migraciones `0002` y `0003`, `tsv` generado, `vector(4096)` y clave única de expresión `(fuente_id, articulo, coalesce(apartado,''))`.

**TDD observado** (RED del worker): `ModuleNotFoundError: app.domain.lcsp_parser`, `ImportError: app.db.models`, y en mi verificación `assert 0 == 1` para la configuración `spanish_unaccent`. GREEN: 16 unitarios, 3 de integración, 1 de datos.

**Verificación del orquestador (no delegada)**

- `ruff`, `ruff format --check`, `mypy --strict`: en verde (27 ficheros).
- `uv run pytest` → 16; `uv run pytest tests/integration` → 3; `uv run pytest tests/data` → 1.
- Migraciones aplicadas contra Postgres 18 real: `alembic upgrade head` + `alembic downgrade 0002` + `upgrade head` limpios. `\d chunk` confirma `tsv` generado con `to_tsvector('spanish_unaccent', texto)`, índice GIN, `vector(4096)` y la clave única.
- Ingesta completa de los 580 chunks en la base real: 580 filas, 580 con `tsv` generado, duplicado rechazado por la clave única (idempotencia lista para CL-03), limpieza posterior a 0 filas.
- Parser sobre el fichero real: 580 chunks, 180 con apartado, 0 duplicados `(articulo, apartado)`, art. 107 → ancla `#a1-19`, fecha `2018-03-09`.

**RDD:** `assess --base-ref 0c4138b --committed-only` → **`medium`** (926 líneas, `review_due: false`, `under_budget`; motivo `executable_change` en `backend/app/db/models.py`). Según AGENTS §5 se difiere al cierre del slice de la feature.

**Hallazgos de la verificación y qué se hizo**

- **Codificación:** el XML del BOE es **UTF-8 válido** (verificado byte a byte: 0 bytes `0xF3`, 16.693 secuencias `ó` correctas). Mi diagnóstico previo de «latin-1» era un artefacto de la consola. Corregido `data/lcsp/README.md` y el docstring del parser; el fallback latin-1 queda solo como red de seguridad.
- **Defecto real corregido:** la configuración `spanish` de Postgres stematiza `garantía` → `garant` y `garantia` → `garanti`, así que una pregunta sin tildes devolvía 0 resultados. Migración `0003` crea `unaccent` + configuración `spanish_unaccent` (`COPY = spanish` con mapeo `unaccent, spanish_stem`) y el `tsv` pasa a usarla. Fijado con 2 tests de integración (configuración instalada y consulta sin tildes contra texto acentuado).
- **Anclas:** los `id` del BOE no son correlativos (`art. 107` = `a1-19`); el parser usa el `id` del bloque, nunca un número construido.
- **Disposiciones:** identidad sintética `DA1…DA58`, `DT1-6`, `DD1`, `DF1-16` por orden documental, con el ordinal completo en `titulo`. Aceptado: AC-04 solo exige recuperación por número de artículo.

### CL-03 · Ingesta idempotente con embeddings

Slice de 2 commits, delegado a `gentle-ai-worker` y verificado a escala real por el orquestador.

- `9d03d4a` feat(adapters): puerto `LLMClient` (`Protocol`) + `NanLLMClient` (lotes de `EMBEDDING_BATCH_SIZE`, semáforo 5, timeout 60 s, backoff exponencial con jitter ante 429/5xx, validación de 4.096 dimensiones, sin loguear la clave) + `FakeLLMClient` determinista en tests.
- `b39c8c6` feat(ingest): `ingest_chunks` idempotente por `(articulo, apartado)` contra la clave única, embebiendo solo lo nuevo o cambiado; CLI `python -m app.ingest <xml>` con `--dry-run` (cero escrituras, cero llamadas, no construye el cliente real) y error tipado si falta `NAN_API_KEY`.

**TDD observado** (RED del worker): `ModuleNotFoundError` de `app.adapters.llm`, `app.ingest` y `app.services.ingest`. GREEN: 27 unitarios, 7 de integración, 1 de datos.

**Verificación del orquestador a escala real** (no el fixture del worker, el XML de 580 chunks)

- `--dry-run` desde la raíz con la forma literal del BRIEF: `uv run --project backend python -m app.ingest data/lcsp/lcsp-consolidada.xml --dry-run` → `{"chunks": 580, "embedding_batches": 37}`, exit 0.
- Doble ingesta real contra Postgres con `FakeLLMClient`: run 1 `inserted=580, embedded=580`; run 2 `inserted=0, updated=0, skipped=580, embedded=0`; filas 580 → 580. **AC-03 cumplido** con el corpus completo.
- Gates: `ruff`, `ruff format --check`, `mypy --strict` (35 ficheros), `pytest` 27, `pytest tests/integration` 7, `pytest tests/data` 1.

**RDD:** `assess --base-ref 0424e60 --committed-only` → **`medium`** (815 líneas, `executable_change` en `backend/app/adapters/llm.py`), diferido al cierre del slice según AGENTS §5.

**Limitaciones conocidas (no corregidas acá)**

- `NanLLMClient` reintenta 429/5xx pero no `APIConnectionError` ni timeouts de red: en la carga real de 37 lotes conviene decidirlo antes de CL-04.
- El semáforo es por llamada a `embed()`, no global entre ingestas concurrentes.

### CL-04 · Recuperación híbrida, RRF, rerank y búsqueda por número

Slice de 2 commits, delegado y verificado a escala real.

- `032859d` feat(retrieval): RRF puro y estable + extracción de número de artículo en español; servicio con búsqueda vectorial exacta (`<=>`), FTS `spanish_unaccent`, fusión RRF, rerank del top `top_k*2` y ruta directa por número. El puerto `rerank` se implementa contra `POST /rerank` (contrato verificado en la documentación de NaN: `results[{index, relevance_score}]`), **sin confiar** en el orden ni la completitud del proveedor: reconstruye el orden y falla con error tipado.
- `6a68022` feat(api): `GET /buscar` y `GET /articulos/{numero}`, y mapeo de errores del LLM a respuestas tipadas.

**TDD observado** (RED del worker): `ModuleNotFoundError` de `app.domain.ranking` y `app.services.retrieval`, `ImportError: RerankResponseError`. RED propio (corrección del orquestador): la clave ausente escapaba como excepción sin manejar.

**Verificación del orquestador a escala real** (580 chunks ingeridos con el fake)

- AC-04: `"¿Qué dice el artículo 107?"` → primera posición `articulo=107`, rama `direct`, URL `#a1-19`.
- Consulta temática → `top_k=6` con `best_score` poblado (0.9057).
- API: `/buscar` 200 con 6 resultados; `/articulos/107` 200; `/articulos/9999` 404 con cuerpo `article_not_found` tipado.
- Gates: ruff, formato, `mypy --strict` (44 ficheros), 63 unitarios, 16 de integración, 1 de datos.

**Defecto propio corregido (encontrado en la verificación)**

- Sin `NAN_API_KEY`, `/buscar` devolvía un 500 con traza: un fallo previsible de configuración, prohibido por AGENTS §10. Ahora `MissingAPIKeyError` → **503 `llm_not_configured`** y el resto de `LLMError` → **502 `llm_unavailable`**, con el mismo sobre tipado que el 404. Cubierto por `tests/unit/test_api_errors.py`.
- `hybrid_search` siempre embebe la pregunta, incluso cuando la ruta directa por número ya resuelve: una llamada extra por consulta. Anotado, no corregido.

**RDD:** `assess --base-ref cabbdff --committed-only` → **`medium`** (1.145 líneas, `executable_change` en `backend/app/adapters/llm.py`), diferido al cierre del slice.

### CL-05 · Generación con citas, validación y abstención

Slice de 2 commits, delegado y verificado a escala real.

- `0e8f1ff` feat(answers): dominio de citas (`[art. X]` / `[art. X.Y]`, separación en afirmaciones, respaldo contra los chunks recuperados) y servicio que abstiene **antes** de generar, valida en código y reintenta una sola vez con el feedback de validación.
- `19ee890` feat(api): `POST /consultas` con respuesta, citas validadas, afirmaciones no respaldadas, aviso, modelo y chunks.

**TDD observado** (RED del worker): `ModuleNotFoundError: app.domain.citations`, `ImportError: ChatResponseError`, `AttributeError: generate_json` y `TypeError: unexpected keyword 'generation_responses'`. GREEN: 94 unitarios, 21 de integración.

**Verificación del orquestador con los 580 chunks reales**

- AC-07: rerank forzado a 0,05 (< umbral 0,35) → `abstencion=True`, texto exacto `No encuentro base en la LCSP para responder esto` y **0** llamadas al modelo de generación.
- AC-06: guion con `[art. 999]` y luego `[art. 998.2]` → **2** llamadas (una sola reintentada), 0 citas válidas, 2 afirmaciones marcadas como no respaldadas y aviso presente.
- Camino feliz con `[art. 107]` sobre una consulta que sí recupera el 107 → 1 llamada, cita válida, `warning=None`.
- `POST /consultas`: 200 con todas las claves; 422 sin cuerpo.
- Gates: ruff, `mypy --strict` (50 ficheros), 94 unitarios, 21 integración.

**Decisiones del worker aceptadas**

- Una afirmación **sin ninguna cita** también se marca como no respaldada (la spec solo habla de citas inválidas; el criterio es más estricto y no oculta texto sin respaldo).
- `citas` en la respuesta son solo las validadas: el chip de la UI debe apuntar a un artículo que existe. Las inventadas salen por `advertencia`/`afirmaciones_no_respaldadas`.

**RDD:** `assess --base-ref 48e50d6 --committed-only` → **`medium`** (1.179 líneas), diferido al cierre del slice.

### AC-11 · CI en verde (evidencia acumulada)

- Run `43223603050` sobre `feat/lcsp-mvp` (`32cb185`): **success** en los tres jobs.
- Backend: `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy --strict` (50 ficheros), `alembic upgrade head` (aplica `0003` con la extensión `unaccent` contra el servicio pgvector) y los dos suites de pytest (unitarios + integración).
- Frontend: `pnpm install --frozen-lockfile`, `lint`, `typecheck`, `test`, `build`.
- Docker: `docker compose build` con las dos imágenes.
- Incidente previo (run `43222982952`): `astral-sh/setup-uv@v10` no existe como ref; el action solo mantiene mayores flotantes hasta `v7`. Corregido fijando `@v10.3.3` en `32cb185`.

### CL-06 · Revisor de cláusulas

Slice de 2 commits, delegado y verificado a escala real.

- `76bad65` feat(clauses): dominio puro con los tres `tipo` de la spec, citas parseadas con el **mismo** parser que las respuestas (sin duplicar lógica) y motivos de rechazo estables (`tipo_no_valido`, `sin_articulos_citados`, `articulo_no_recuperado`, `cita_no_encontrada`, `aviso_mal_formado`). Cláusula de más de 800 palabras → error tipado.
- `2968a8b` feat(clauses): `review_clause` + `POST /revisiones`.

**TDD observado** (RED del worker): `ModuleNotFoundError: app.domain.clauses` y 404 en lugar de 422 en los tests de API. GREEN: 112 unitarios, 26 de integración, `mypy --strict` limpio en 56 ficheros.

**Verificación del orquestador con los 580 chunks reales** (cláusula con garantía del 3%, que choca con el 5% del art. 107)

- AC-08: aviso `posible_incumplimiento` citando `[art. 306]` — artículo efectivamente recuperado — valida con 1 llamada y 0 descartes.
- Cita inventada `[art. 999]` → **2** llamadas (un solo reintento) y aviso descartado con motivo `articulo_no_recuperado`; nunca se muestra una cita inexistente.
- Sin base (rerank 0,02 < 0,35) → `sin_observaciones=True`, texto exacto `sin observaciones fundadas`, `model_called=False` y 0 llamadas.
- `POST /revisiones`: 200 con `avisos`/`avisos_invalidos`/`chunks`; 801 palabras → 422 `clausula_demasiado_larga`; sin cláusula → 422 `clausula_ausente`.
- Observación del caso real: para esa cláusula el recuperador devolvió `306, 266, DA23, 268, 347, DA3` y **no** el 107. Con embeddings reales (CL-08) hay que comprobar que el artículo correcto entra en el top-6; con el fake la similitud no es semántica.

**Decisiones del worker aceptadas**

- Cláusula ausente devuelve 422 tipado `clausula_ausente` en el propio endpoint, en vez de un handler global que habría cambiado el sobre de 422 de `/consultas`.
- `chunks` se exponen también en el camino sin base, para que la UI pueda explicar por qué no hay observaciones.
- `articulos_citados` viaja como `[art. X]`/`[art. X.Y]` (formato exigido en el prompt) y se parsea con `parse_citations`.

**RDD:** `assess --base-ref b039278 --committed-only` → **`medium`** (1.049 líneas), diferido al cierre del slice.

### CL-07 · Frontend: consulta, revisor e historial

Slice de 4 commits, delegado y verificado con capturas por el orquestador.

- `cca1d58` feat(web): vistas de consulta (chips → panel lateral vía `GET /articulos/{numero}`, tabla plegable de recuperados con rerank, estados de abstención y avisos) y de revisor (tarjetas tipadas con artículo y cita literal, `sin observaciones fundadas`, lista de descartados), historial de sesión en memoria y paleta de los mockups como tokens de Tailwind.
- `1fc24af` test(web): 9 tests de Vitest/Testing Library + 2 de Playwright, con la red stubbeada (`fetch` y `page.route`), sin backend ni clave.
- `b27bd43` ci: job e2e solo en PR hacia `dev`/`main`, con el stack de compose y subida del informe si falla.
- `4341dab` chore: `.gitattributes` con `eol=lf`.

**TDD observado** (RED del worker): imports no resueltos de `ConsultaView`/`RevisorView` y `Unable to find a label`. GREEN: 9 unitarios, 2 e2e.

**Verificación del orquestador**

- Gates: `pnpm lint`, `typecheck`, `test` (9), `build`, `e2e` (2) en verde; `actionlint` sin errores sobre el `ci.yml` nuevo.
- **Capturas reales** de ambas vistas contra la API stubbeada: la de consulta muestra chip `art. 107` → panel con «Artículo 107» y su enlace al BOE; la de revisor muestra «2 avisos», badges `posible_incumplimiento`/`ambigüedad`, cita literal entrecomillada y panel del art. 193. Paleta y estructura fieles a `frontend/docs/mock/`.
- **Fallo de entorno corregido:** `pnpm format:check` fallaba en 9 ficheros que nadie había tocado. Causa: `core.autocrlf=true` en el clon Windows frente a LF del repositorio. Se añadió `.gitattributes` con `* text=auto eol=lf`; `format:check` queda limpio y no vuelve a pasar en ningún clon.

**RDD (revisión nativa, `high`)**

- `assess --base-ref b12de34` → **`high`** (`process_boundary` y `shell_source` en `.github/workflows/ci.yml`).
- Lineage `review-fc0433fbf0ffb962`, 3 lentes (`risk`, `readability`, `reliability`), 19 ficheros, 1.732 líneas. Tres revisores ejecutados, refutador ejecutado, veredicto **`approved`** con authority quemada.
- Hallazgo crítico **refutado** por el refutador: `R3-001-ui-crash-undefined-filter` (RevisorView.tsx:50-51).
- Avisos no bloqueantes (trabajo posterior, no reabren esta revisión):
  - `R3-002-stale-panel-history-switch` (WARNING, `ConsultaView.tsx:28`): al cambiar de entrada del historial el panel puede mostrar el artículo anterior.
  - `R3-003-ci-port-reuse-flakiness` (WARNING, `playwright.config.ts:18`): el puerto 5273 fijo puede colisionar en un runner compartido.
  - `R3-004-regex-silent-cast` (SUGGESTION, `answerText.ts:8`).

## Progreso y siguiente paso

- Progreso: 7/9 tareas implementadas y verificadas (CL-01 RDD cerrado por abandono autorizado; CL-02 a CL-06 con RDD `medium` diferido; CL-07 con revisión nativa `approved`).
- RDD pendiente: (a) aplicar la corrección de `R4-async-singleton-race` (cerrojo async en la inicialización del engine, con test), (b) decidir si los dos mockups entran en la candidata, (c) revisar los slices `web` e `infra`.
- Siguiente paso: CL-08 (set de 25 preguntas y evaluación con la API real). Requiere decisión de Albert sobre gastar cuota.
- Trabajo posterior anotado: los tres avisos del revisor (`R3-002`, `R3-003`, `R3-004`); el e2e del CI solo se ejercita en un PR.
- Pendiente de decisión: endurecer `NanLLMClient` para errores de conexión/timeout antes de la carga real de 37 lotes.

## Log

- **L1 (solicitud original de Albert, literal):** "Lee el BRIEF.md y el AGENTS.md y aunque en el brief ponga que este proyecto se va a empezar si se acaba primero el de radar de pliegos, no va a ser asi, vas a hacerlo a la vez que se hace el otro"
- **L2 (decisión de alcance, 2026-11-12):** queda anulada la premisa del BRIEF "(Proyecto secundario: se hace solo si Radar de Pliegos tiene la Fase 1 cerrada...)" y la dependencia "Fase 2 · Extensión (solo con la Fase 1 cerrada y en verde)" en lo que respecta al calendario: Consultor LCSP Fase 1 avanza **en paralelo** con Radar de Pliegos. El resto del BRIEF (alcance, non-goals, criterios de aceptación) no cambia.
- **L3 (hecho, 2026-11-12):** leídos `BRIEF.md` y `AGENTS.md` completos; entorno verificado: uv 0.12.10, Python 3.14.5, Node v24.22.1, pnpm 11.4.0, Docker 29.9.3, RDD on. Repo sin commits, sin ramas locales, remoto `github.com/aam9063/Consultor-LCSP` vacío.
- **L4 (decisión de Albert, 2026-11-12):** bootstrap de Git = commit inicial en `main` (AGENTS.md, BRIEF.md, `.gitignore`), luego `dev` y trabajo en `feat/cl-01-skeleton`. Ejecutado: `2225e7b` en `main`, `dev` y `feat/cl-01-skeleton` desde ahí.
- **L5 (hallazgo, 2026-11-12):** aparecen sin commitear `frontend/docs/mock/LcspConsulta.dc.html` y `frontend/docs/mock/LcspRevisor.dc.html` (mockups de la UI, no generados por el agente). Quedan fuera de los commits de CL-01 a la espera de decisión.
- **L6 (decisión de Albert, 2026-11-12):** los dos mockups se excluyen de la candidata de revisión; `.env.example` se versiona (el fichero lo crea Albert, sin secretos). La lineage `review-3d828745be58ead1` se abandona con `operator_disposition` y queda en cuarentena.
- **L7 (corrección propia, 2026-11-12):** el XML del BOE es UTF-8 válido; el diagnóstico anterior de ISO-8859-1 era un artefacto de la consola. Corregidos `data/lcsp/README.md` y el docstring del parser.
