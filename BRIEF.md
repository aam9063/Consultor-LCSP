# BRIEF · Consultor LCSP

> Proyecto de aprendizaje inspirado en **Themia** (Crata AI), el "sistema operativo de IA para equipos legales".
> Autor y dueño del producto: Albert. Fecha del brief: 11 nov 2026.
> Proyecto secundario: se hace solo si Radar de Pliegos tiene la Fase 1 cerrada, o como siguiente proyecto después de la entrevista.

---

## 0. Cómo usar este brief con ODD (instrucciones para el agente)

1. Este documento es la **especificación de producto**. Léelo entero antes de explorar el código.
2. El trabajo es **sustancial** según ODD. Antes de la primera escritura de código crea el feature document `odd/tasks/consultor-lcsp-mvp.md` y su espejo en Engram (`odd/consultor-lcsp-mvp/tasks`).
3. El feature document **cita este brief literalmente** en su sección de objetivo y problema. Los handoffs a subagentes apuntan al feature document, nunca lo parafrasean.
4. Cada tarea del checklist lleva un **ID estable** (`CL-01`, `CL-02`...) y enlaza los criterios de aceptación (`AC-xx`) que cubre.
5. TDD y RDD están **activados** según `AGENTS.md`. Cada tarea cierra con un work-unit commit en su rama `feat/*` y la evidencia en el feature document.
6. Si algo es ambiguo y cambia la siguiente acción, haz **una** pregunta concreta a Albert. Los hallazgos no autorizan alcance nuevo.

---

## 1. Introducción

**Consultor LCSP** es un asistente que responde preguntas sobre la **Ley 9/2017, de Contratos del Sector Público** (LCSP) citando siempre el artículo y el apartado exactos, y que se niega a responder cuando la ley no da base suficiente.

Incluye además un **revisor de cláusulas**: pegas una cláusula de un pliego y el sistema señala posibles choques con la LCSP, cada uno con su artículo.

Es la versión mínima del patrón que Crata vende en Themia: centralizar la normativa, responder con trazabilidad a la fuente y revisar borradores para detectar riesgos.

## 2. El problema

- La LCSP tiene más de 340 artículos más disposiciones adicionales y transitorias. Las dudas del día a día (umbrales, plazos, garantías, penalidades) obligan a buscar a mano o a preguntar a alguien que se la sabe.
- Un chat genérico responde con seguridad, pero cita artículos que no existen o versiones antiguas, y no dice cuándo no lo sabe.
- En un equipo jurídico o de licitaciones, una respuesta sin artículo no sirve: hay que poder justificarla.

## 3. Para quién

| Persona | Qué necesita | Cómo usa el Consultor |
| --- | --- | --- |
| **Técnico de licitaciones de una constructora** (usuario principal) | Resolver dudas rápidas sobre plazos, garantías y requisitos | Pregunta en lenguaje natural y comprueba el artículo citado |
| **Jurista junior o responsable de contratación de un ayuntamiento pequeño** (secundario) | Revisar si una cláusula de un pliego es coherente con la ley | Pega la cláusula y revisa los avisos |

## 4. Objetivo y métrica de éxito

- Respuestas en menos de 10 segundos, donde **cada afirmación** lleva al menos una cita `[art. X.Y]` que existe en el texto recuperado.
- Abstención correcta: si la pregunta no tiene base en la LCSP, lo dice en vez de inventar.
- Evaluación con 25 preguntas anotadas: recall@5 del artículo correcto, % de respuestas con todas las citas válidas y % de abstenciones correctas.

## 5. Alcance (scopes)

### Fase 1 · MVP (obligatorio)

**S1 · Ingesta de la ley**
- Texto consolidado de la LCSP descargado a mano del BOE (identificador `BOE-A-2017-12902`, en HTML o XML) y guardado en `data/lcsp/`.
- Comando `uv run python -m app.ingest data/lcsp/<fichero>` que parsea la estructura: libro, título, capítulo, sección, artículo, apartado y disposiciones.
- Unidad de recuperación (chunk): el **artículo**; si un artículo supera unos 1.500 tokens, se divide por apartados sin partir ninguno.
- Metadatos por chunk: número de artículo, título, ruta jerárquica, apartado si aplica, URL con ancla al BOE y fecha de la versión consolidada.
- La ingesta es idempotente: ejecutarla dos veces no duplica nada.

**S2 · Índice híbrido en Postgres**
- Embeddings con el modelo `qwen3-embedding` de NaN Builders (4.096 dimensiones) guardados con `pgvector`.
- Con 4.096 dimensiones los índices HNSW e IVFFlat de pgvector no aplican (su límite es inferior), así que se usa **búsqueda exacta**. Con unos 500 chunks es rápida de sobra.
- Búsqueda de texto completo de Postgres con configuración `spanish` sobre el mismo corpus.
- Fusión de ambos rankings con Reciprocal Rank Fusion y reordenación final con el modelo `rerank` de NaN. Se quedan los 6 mejores.
- Si la pregunta menciona un artículo concreto ("¿qué dice el artículo 107?"), se recupera directamente por número.

**S3 · Respuesta con citas**
- Generación con `deepseek-v4-flash`. El prompt obliga a responder **solo** con el contexto recuperado y a citar `[art. X]` o `[art. X.Y]` tras cada afirmación.
- Salida estructurada (`json_schema`, sin tools): `respuesta`, `citas` (lista de artículo y apartado), `abstencion: bool`, `motivo_abstencion`.
- **Validación en código**: toda cita debe corresponder a un chunk recuperado. Una cita inventada provoca un reintento; si persiste, la afirmación se marca como no respaldada y se muestra un aviso.
- **Abstención**: si la mejor puntuación del reranker queda por debajo de un umbral configurable, no se llama al LLM y se responde "No encuentro base en la LCSP para responder esto".
- Aviso fijo en la interfaz: no es asesoramiento jurídico.

**S4 · Revisor de cláusulas**
- Entrada: texto de una cláusula (hasta unas 800 palabras).
- El sistema recupera los artículos relevantes y devuelve una lista de avisos: `{tipo: posible_incumplimiento | ambiguedad | ok, explicacion, articulos_citados, cita_de_la_clausula}`.
- Mismas reglas: solo artículos recuperados y validados; si no hay base, "sin observaciones fundadas".

**S5 · Frontend**
- Vista de consulta: caja de pregunta, respuesta con las citas como chips y un panel lateral con el texto del artículo citado al pulsar un chip.
- Lista de artículos recuperados con su puntuación, plegable, para entender qué ha encontrado el sistema.
- Vista del revisor: área de texto para la cláusula y tarjetas de avisos con su artículo.
- Historial de consultas de la sesión (en memoria del navegador, sin persistir).

**S6 · Evaluación**
- `evals/preguntas.yaml` con 25 entradas: pregunta, artículos esperados, respuesta de referencia breve y si debería abstenerse.
- 20 preguntas con base en la ley y 5 fuera de ella (por ejemplo, sobre el IVA o sobre derecho laboral).
- Ejemplos de partida, **a confirmar contra el texto del BOE al anotar**: penalidades por demora (art. 193), cuándo se exige clasificación en obras (art. 77), importe de la garantía definitiva (art. 107), límites del contrato menor (art. 118), procedimiento abierto simplificado (art. 159), criterios de adjudicación (art. 145), ofertas anormalmente bajas (art. 149), subcontratación (art. 215).
- Comando `uv run python -m evals.run` que genera `evals/results/<fecha>.md` con recall@5, % de citas válidas, % de abstención correcta y los peores casos.
- Usa la API real; no corre en el CI por defecto (solo `workflow_dispatch` con el secreto `NAN_API_KEY`).

### Fase 2 · Extensión (solo con la Fase 1 cerrada y en verde)

- **S7 · Conexión con Radar de Pliegos**: el revisor recibe las penalidades o garantías extraídas por Radar y las contrasta con la LCSP.
- **S8 · Feedback del usuario**: pulgar arriba o abajo por respuesta, guardado en base de datos para ampliar el set de evaluación.

## 6. Lo que NO queremos (non-goals)

- Otras leyes o reglamentos (RGLCAP, normativa autonómica, jurisprudencia). Solo la LCSP consolidada.
- Descarga automática del BOE en tiempo de ejecución.
- Conversación multi-turno con memoria. Cada consulta es independiente.
- Autenticación, multiusuario o persistencia del historial.
- Frameworks de RAG o agentes pesados (LangChain, LlamaIndex, LangGraph). SDK `openai` apuntando a NaN + SQL propio.
- Bases de datos vectoriales externas (Pinecone, Qdrant...). Solo Postgres con pgvector.
- Fine-tuning.
- Presentar las respuestas como asesoramiento jurídico.
- Llamadas reales a la API de IA en los tests del CI.

## 7. Restricciones

- Stack, Git, TDD, RDD y CI según `AGENTS.md`.
- Límites de NaN Builders: 60 peticiones por minuto y 7 concurrentes por clave (embeddings y rerank sin límite de concurrencia, rerank hasta 1.000 por minuto). Ingesta de embeddings por lotes con backoff ante 429.
- El texto de la ley es público (BOE) y puede versionarse en el repo.

## 8. Modelo de datos (orientativo)

- `fuente(id, nombre, boe_id, fecha_version, importado_en)`
- `chunk(id, fuente_id, articulo, apartado, titulo, ruta, texto, url, tsv tsvector, embedding vector(4096))`
- `consulta(id, pregunta, respuesta jsonb, chunks_recuperados jsonb, creada_en)` (solo para depurar y evaluar)

## 9. API (orientativa)

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/health` | Salud del servicio |
| `POST` | `/consultas` | Pregunta → respuesta con citas o abstención |
| `POST` | `/revisiones` | Cláusula → lista de avisos |
| `GET` | `/articulos/{numero}` | Texto completo de un artículo |
| `GET` | `/buscar?q=` | Depuración: ranking híbrido sin LLM |

## 10. Criterios de aceptación

Formato: Dado / Cuando / Entonces. Cada uno debe tener al menos un test automatizado salvo que se indique otra cosa.

- **AC-01 · Arranque.** Dado el repo recién clonado con `.env` copiado de `.env.example`, cuando ejecuto `docker compose up -d`, entonces `api`, `web` y `db` (con la extensión `vector` creada) quedan sanos y `GET /health` devuelve 200.
- **AC-02 · Parser.** Dado un fragmento de la ley en fixture con 3 artículos, uno de ellos con apartados, cuando lo parseo, entonces obtengo los chunks con número, título, apartado y ruta correctos.
- **AC-03 · Idempotencia.** Dada la ley ya ingerida, cuando repito la ingesta, entonces el número de chunks no cambia.
- **AC-04 · Recuperación directa.** Dada la pregunta "¿Qué dice el artículo 107?", cuando consulto, entonces el primer chunk recuperado es el art. 107.
- **AC-05 · Fusión y rerank.** Dados dos rankings falsos, cuando aplico RRF y el reranker falso, entonces el orden final coincide con el esperado en el test.
- **AC-06 · Citas válidas.** Dada una respuesta del LLM (falso) que cita un artículo no recuperado, cuando se valida, entonces se reintenta una vez y, si persiste, la afirmación queda marcada como no respaldada.
- **AC-07 · Abstención.** Dada una pregunta cuya mejor puntuación de rerank queda bajo el umbral, cuando consulto, entonces la respuesta es una abstención y **no** se llama al LLM de generación.
- **AC-08 · Revisor.** Dada una cláusula de prueba, cuando la reviso con el LLM falso, entonces devuelvo avisos tipados y cada artículo citado pertenece a los recuperados.
- **AC-09 · UI de citas.** Dada una respuesta con dos citas, cuando pulso un chip, entonces el panel lateral muestra el texto de ese artículo. (Test de componente con Vitest y un e2e con Playwright.)
- **AC-10 · Evaluación.** Dadas las 25 preguntas, cuando ejecuto `uv run python -m evals.run`, entonces se genera el informe. Objetivos: recall@5 ≥ 85%, citas válidas ≥ 95%, abstención correcta en al menos 4 de 5 preguntas fuera de la ley. Si no se alcanzan, el informe explica por qué. (Prueba manual, con evidencia en el feature document.)
- **AC-11 · CI en verde.** Dado un push a una rama `feat/*`, cuando corre GitHub Actions, entonces pasan lint, tipos, tests de backend (con Postgres + pgvector como servicio) y frontend y build, sin usar `NAN_API_KEY`.
- **AC-12 · README.** Explica cómo arrancar, cómo ingerir la ley y cómo evaluar, en pocos comandos, y muestra las últimas métricas.

## 11. Orden sugerido de tareas (para el checklist del feature document)

| ID | Tarea | Cubre |
| --- | --- | --- |
| CL-01 | Esqueleto del monorepo, Docker Compose con pgvector, `/health`, CI mínimo | AC-01, AC-11 |
| CL-02 | Parser de la LCSP y modelo `chunk` | AC-02 |
| CL-03 | Ingesta idempotente con embeddings y `tsvector` | AC-03 |
| CL-04 | Recuperación híbrida, RRF, rerank y búsqueda por número | AC-04, AC-05 |
| CL-05 | Generación con citas, validación y abstención | AC-06, AC-07 |
| CL-06 | Revisor de cláusulas | AC-08 |
| CL-07 | Frontend: consulta con chips y panel, revisor, historial | AC-09 |
| CL-08 | Set de 25 preguntas y evaluación | AC-10 |
| CL-09 | README y cierre de la Fase 1 | AC-12 |

## 12. Qué quiere aprender Albert con esto

- Cómo se construye un RAG en el que el usuario puede **auditar** cada frase.
- Cuánto aporta la búsqueda híbrida y el reranker frente a solo embeddings (comparar en la evaluación).
- Cómo se diseña la abstención para que el sistema diga "no lo sé" en el momento justo.
- Cómo se pasa de "responder preguntas" a "revisar documentos", que es donde Themia aporta valor a un equipo legal.
