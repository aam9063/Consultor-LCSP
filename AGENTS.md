# AGENTS.md

Guía y guardarraíles para cualquier agente de código que trabaje en este repositorio (Pi con gentle-shell, Claude Code, Codex u otro). Es la misma para **Radar de Pliegos** y **Consultor LCSP**; solo cambia la sección 1.

Si una instrucción de este fichero choca con una petición puntual de Albert en la sesión, **gana Albert**, pero dilo explícitamente antes de actuar.

---

## 1. Proyecto

- **Qué es:** ver `BRIEF.md` en la raíz. Es la especificación de producto y la fuente de verdad del alcance.
- **Dueño:** Albert. Habla con él en **español**. Código, nombres, comentarios, commits y descripciones de PR en **inglés**.
- **Feature document activo:** `odd/tasks/<feature>.md` (ver sección 3).

## 2. Stack y versiones

Usa siempre la **última versión estable** de cada herramienta en el momento de crear el proyecto y **fíjala** (lockfiles, `packageManager`, `.python-version`, `.nvmrc`). No actualices majors sin pedirlo.

**Backend (`/backend`)**
- Python **3.14**, gestionado con **uv** (`pyproject.toml` + `uv.lock`).
- **FastAPI** + Pydantic v2 + `pydantic-settings`.
- SQLAlchemy 2 (async) + Alembic para migraciones.
- PostgreSQL 18 con la extensión `pgvector` (imagen `pgvector/pgvector:pg18`).
- Calidad: `ruff` (lint y formato), `mypy --strict`, `pytest` + `pytest-asyncio` + `httpx` para tests de API.

**IA (NaN Builders)**
- API compatible con OpenAI. Base URL `https://api.nan.builders/v1`, autenticación `Authorization: Bearer $NAN_API_KEY`.
- Cliente: SDK oficial `openai` de Python con `base_url` y `api_key` desde configuración. Nada de LangChain, LlamaIndex ni similares.
- Modelos por defecto (configurables por variable de entorno):
  - Chat y extracción: `deepseek-v4-flash`. Su `json_schema` solo funciona en `/chat/completions` **sin tools**: nunca mezcles ambos en la misma llamada.
  - Alternativa con `json_schema` estricto: `qwen3.6`.
  - Embeddings: `qwen3-embedding` (4.096 dimensiones).
  - Reordenación: `rerank`.
- Límites: 60 peticiones/min y 7 concurrentes por clave. El adaptador usa un semáforo de 5 y backoff exponencial con jitter ante 429 y 5xx.
- Toda llamada pasa por un puerto `LLMClient` (interfaz) con dos implementaciones: `NanLLMClient` (real) y `FakeLLMClient` (tests). **Ningún test llama a la API real.**

**Frontend (`/frontend`)**
- **React 19** (última 19.x), **TypeScript** en modo `strict`, componentes en `.tsx`.
- **Vite** (última major) con `@vitejs/plugin-react`.
- **pnpm** como único gestor de paquetes, fijado en el campo `packageManager` de `package.json`. Instalar con `pnpm add`, ejecutar binarios con `pnpm exec` y herramientas puntuales con `pnpm dlx`. Ningún otro gestor de paquetes ni su lockfile.
- Node.js LTS activa, fijada en `.nvmrc` y en `engines`.
- Datos de servidor con TanStack Query; rutas con React Router.
- **Estilos: Tailwind CSS** (última versión estable), integrado con su plugin oficial para Vite e instalado con `pnpm add`. Nada de CSS Modules, styled-components ni librerías de componentes con estilos propios.
  - Los colores y tipografías del diseño preliminar van como tokens del tema de Tailwind, no como valores sueltos: fondo `#F6F6F3`, superficie `#FFFFFF`, borde `#E3E3DE`, texto `#17181C`, texto secundario `#5B5E66`, acento Radar `#2445C8`, acento LCSP `#0F6B5C`; estados GO `#1E7A46` sobre `#E6F4EC`, REVISAR `#8A5A00` sobre `#FFF4D6`, NO-GO `#B42318` sobre `#FDECEA`; fuentes Inter (texto) y Space Grotesk (títulos).
  - Clases utilitarias en el JSX; si una combinación se repite mucho, se extrae a un componente React, no a `@apply`.
- Tests: Vitest + Testing Library para componentes; Playwright para e2e.
- Lint y formato: ESLint (flat config + `typescript-eslint`) y Prettier.

**Infraestructura**
- `docker-compose.yml` en la raíz con `db`, `api` y `web`, todos con `healthcheck`.
- `.env.example` versionado con todas las variables; `.env` **nunca** se commitea.
- Todo debe arrancar con `docker compose up -d` desde un clon limpio.

## 3. Flujo de trabajo: ODD

Este repo trabaja con **Organic Driven Development** de gentle-ai, también fuera de gentle-shell.

1. **Authorize.** Preguntas, revisiones y propuestas son de solo lectura. No escribas nada hasta que Albert pida un cambio.
2. **Explore.** Lee `BRIEF.md`, este fichero y el código afectado antes de editar.
3. **Resolve uncertainty.** Una pregunta concreta solo si la respuesta cambia la siguiente acción. No inventes decisiones de producto.
4. **Classify.** Pequeño (entendido, bajo riesgo, recuperable con `git diff`) o sustancial (dos o más pasos con significado o progreso que merece recuperar).
5. **Track.** Para trabajo sustancial, antes de la primera escritura crea `odd/tasks/<feature>.md` y su espejo en Engram (`odd/<feature>/tasks`). Di a Albert en una línea qué documento has creado y cuántas tareas tiene.
   - Secciones: objetivo, problema, por qué, alcance, restricciones, checklist con **IDs estables** y criterios de aceptación, evidencias de verificación, progreso y siguiente paso.
   - Cita el `BRIEF.md` **literalmente** en objetivo y problema. Los handoffs apuntan al documento, no lo parafrasean.
   - Registra aquí la configuración de TDD (modo, fuente y runner) y la de RDD.
6. **Implement.** Tarea a tarea, con TDD (sección 4). Marca una tarea como hecha solo con prueba observada. Cada tarea termina con al menos un work-unit commit (sección 6) y el hash queda anotado en el feature document.
7. **Close.** Informa del resultado verificado, de cada check fallido o pendiente y del siguiente paso.

Alcance: los hallazgos durante el trabajo **no autorizan** ampliar el alcance. Si algo nuevo parece necesario, añádelo como propuesta en el feature document y pregunta.

Subagentes: solo con motivo explícito (exploración amplia, escritores en paralelo sobre ficheros distintos o verificador independiente de un punto de alto riesgo).

## 4. TDD obligatorio

- **Modo: activado.** Fuente: este `AGENTS.md`. Pásalo a cada worker y refréscalo al reanudar.
- Runners:
  - Backend: `uv run pytest` (desde `/backend`).
  - Frontend unitario y componentes: `pnpm vitest run` (desde `/frontend`).
  - E2E: `pnpm playwright test` (desde `/frontend`, con `docker compose up -d`).
- Ciclo por cada regla o comportamiento pedido: **RED observado** (el test falla por el motivo correcto) → **GREEN** con el mínimo código → **REFACTOR** con los tests en verde.
- Registra en el feature document, por tarea: test escrito, salida del RED, salida del GREEN.
- Cada comando u opción existente que toques necesita un test que demuestre que su comportamiento anterior se mantiene.
- Excepción solo cuando no hay test ejecutable con sentido (configuración, Dockerfile, CI): explícalo en el feature document y ejecuta la comprobación funcional equivalente (`docker compose config`, build, `actionlint`...).
- Prohibido: borrar, saltar (`skip`, `xfail`) o debilitar tests para ponerlos en verde, y mockear la unidad que se está probando.
- Lo que depende del LLM se prueba con `FakeLLMClient` y fixtures deterministas. La calidad real del modelo se mide en `evals/`, no en los tests.

## 5. RDD obligatorio: revisión después de implementar

**Receipt-Driven Development** de gentle-ai debe estar **activado** en este clon.

- Comprobación al empezar la sesión: `/gentle:review-mode status` (en gentle-shell) o `/gentle:rdd`. Si está desactivado, pide a Albert que lo active; no lo actives ni desactives tú.
- Después de **cada work-unit commit**:
  ```bash
  gentle-ai review assess --cwd <repo> --base-ref <último límite revisado> --committed-only --json
  ```
  - `high`, o assess no disponible o fallido: revisa ese commit inmediatamente con el STATUS nativo.
  - `medium`: se revisa al cerrar el slice de la feature.
  - `passive` o `low`: avanza el límite revisado.
  - Nunca deduzcas riesgo bajo de un assess fallido.
- **Regla de este repo, más estricta que la de serie:** al cerrar cada feature (antes de pedir el push) se revisa siempre el slice completo, aunque todos los assess hayan salido `passive`. Si la herramienta no exige revisión, haz tú una revisión explícita con las cuatro lentes **4R**: Risk, Resilience, Readability y Reliability.
- Como mucho **una corrección acotada** por revisión. Lo que quede abierto se reporta a Albert, no se arregla en bucle.
- Registra en el feature document, por tarea: nivel (`granted`, `declined`, `passive`, `deferred to slice`, `unavailable`) y resultado.
- La evidencia de RDD **no autoriza** commits, pushes, PRs ni releases. Eso lo decide Albert (sección 6).

## 6. Git

**Ramas**
- `main`: estable. Solo Albert mergea a `main`.
- `dev`: integración. Solo Albert mergea a `dev`.
- Trabajo: `feat/<slug>` o `fix/<slug>`, creadas **siempre desde `dev` actualizada**. Ejemplo: `feat/rp-04-pliego-extraction`.
- Nunca commitees directamente en `main` ni en `dev`. Si estás en una de ellas, crea la rama antes de escribir.

**Commits (automáticos)**
- Puedes hacer commit sin preguntar: al cerrar cada tarea y en cada paso con sentido dentro de ella.
- Formato **Conventional Commits** en inglés: `feat(api): add pliego upload endpoint`, `fix(web): jump to cited page`, `test(extract): cover missing penalties`, `chore(ci): cache uv`.
- Un commit = una unidad de trabajo coherente con sus tests. Nada de commits "wip" ni de mezclar refactor y feature.
- Antes de cada commit: lint, tipos y tests del área tocada en verde.

**Autorización permanente de Albert (2026-11-12)**

Albert delegó explícitamente el ciclo completo de entrega. Mientras esta autorización siga vigente:

1. **Push** de la rama de trabajo (`feat/*`, `fix/*`) a `origin` sin volver a preguntar.
2. **Abrir la PR contra `dev`** (nunca contra `main`) con el borrador del feature document.
3. **Vigilar el CI** de esa PR hasta verlo en verde; si falla, se diagnostica la causa raíz, se corrige y se vuelve a intentar. Nada se considera terminado con CI rojo.
4. **Mergear a `dev`** cuando la PR esté en verde, con merge commit (no squash: los hashes de los commits son evidencia citada en el feature document).
5. **Nunca mergear a `main`**, ni `dev` ni ninguna otra rama: eso sigue siendo decisión exclusiva de Albert.
6. Al terminar el merge, **continuar con la siguiente tarea** del feature document, documentando en `docs/aprendizaje/<ID>-<slug>.md` según la sección 11.

Esta autorización **no** incluye: force push, reescribir historia compartida, tocar `main`, saltarse TDD/RDD, ni desactivar gates.

**Push (resto de casos)**
- Cualquier otro push (rama ajena al ciclo, `dev`, `main`) sigue exigiendo pregunta explícita.
- **Después de cada push, espera el run del CI.** No des una tarea por cerrada hasta ver ese run en verde: `gh run watch <run-id> --exit-status` (o `gh run list` para localizarlo). Si falla, lee `gh run view <run-id> --log-failed`, diagnostica la causa raíz, corrígela y vuelve a pushear y esperar. Un push sin run verde no es un push terminado.
- Nunca `--force` ni `--force-with-lease`.
- No actives los modos `YOLO`, `Super Yolo` ni `auto` de gentle-shell para saltarte esta regla: conceden push y PR por su cuenta.

**Pull requests**
- Autorizadas contra `dev` según la autorización permanente de arriba. **Nunca** contra `main`.
- Al cerrar una feature, deja en el feature document un borrador de PR en inglés: título, resumen, criterios de aceptación cubiertos, cómo probarlo y resultado de RDD.
- Nunca hagas merge, rebase ni cherry-pick sobre `main` o `dev`.

## 7. CI (GitHub Actions)

Fichero `.github/workflows/ci.yml`. Se ejecuta en `push` a `feat/**`, `fix/**`, `dev` y `main`, y en `pull_request` hacia `dev` y `main`. Usa `concurrency` para cancelar ejecuciones viejas de la misma rama.

Jobs:
1. **backend**: `astral-sh/setup-uv` con caché → `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy --strict` → `pytest` con un servicio `pgvector/pgvector:pg18`.
2. **frontend**: `pnpm/action-setup` + `actions/setup-node` con caché de pnpm → `pnpm install --frozen-lockfile` → `pnpm lint` → `pnpm typecheck` (`tsc --noEmit`) → `pnpm vitest run` → `pnpm build`.
3. **e2e** (solo en PR hacia `dev` o `main`): `docker compose up -d --wait` → Playwright → sube el informe como artifact si falla.
4. **docker**: `docker compose build` para comprobar que las imágenes construyen.

Reglas:
- El CI **no usa** `NAN_API_KEY`. Las evaluaciones con la API real van en `.github/workflows/evals.yml`, solo con `workflow_dispatch` y el secreto `NAN_API_KEY`.
- Acciones fijadas a una major concreta. Permisos mínimos (`contents: read`).
- Un CI en rojo bloquea el cierre de una tarea.

## 8. Estructura del repo

```
.
├── AGENTS.md
├── BRIEF.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .github/workflows/{ci.yml,evals.yml}
├── odd/tasks/                 # feature documents de ODD
├── backend/
│   ├── pyproject.toml, uv.lock, .python-version
│   ├── app/{api,domain,services,adapters,db}/
│   ├── migrations/            # Alembic
│   └── tests/{unit,integration}/
├── frontend/
│   ├── package.json, pnpm-lock.yaml, .nvmrc
│   ├── src/{app,features,components,lib}/
│   └── tests/e2e/
└── evals/                     # datos anotados, runner e informes
```

Arquitectura del backend: `domain` no importa nada de FastAPI, SQLAlchemy ni del SDK de IA. Las reglas de negocio (motor de decisión, validación de citas, fusión de rankings) viven en `domain` como funciones puras y testeadas.

## 9. Comandos

```bash
# Arranque completo
cp .env.example .env && docker compose up -d

# Backend
cd backend && uv sync && uv run alembic upgrade head
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict app
uv run ruff check ../evals && uv run mypy --strict ../evals   # el runner de evaluación también se lintea

# Frontend
cd frontend && pnpm install
pnpm dev
pnpm vitest run && pnpm lint && pnpm typecheck && pnpm build
pnpm playwright test

# Evaluación (usa la API real, gasta cuota)
cd backend && uv run python -m evals.run
```

## 10. Calidad y seguridad

- Tipado estricto en ambos lados. En TypeScript, nada de `any`; en Python, nada de `# type: ignore` sin motivo escrito al lado.
- Errores explícitos: la API devuelve errores tipados con mensaje útil; nunca un 500 genérico por un fallo previsible del LLM.
- No registres prompts completos ni la clave en los logs. Registra modelo, tokens, latencia e ID de petición.
- Secretos solo por variables de entorno. Si detectas un secreto en el código o en el historial, para y avisa.
- No añadas dependencias nuevas sin justificarlo en una línea en el feature document.
- Accesibilidad básica en el frontend: etiquetas en formularios, foco visible y contraste suficiente.

## 11. Documentación de aprendizaje (obligatoria)

Al cerrar **cada** implementación (tarea del feature document, corrección relevante o slice), escribe
`docs/aprendizaje/<ID>-<slug>.md`. No es un changelog ni un resumen del diff: es material de estudio
para Albert, que está aprendiendo a construir este tipo de producto.

Estructura fija, en español, con estas cinco secciones:

1. **Qué se ha construido** — la pieza en una frase y su lugar en el sistema, sin jerga sin explicar.
2. **Cómo se ha hecho y por qué así** — cada decisión con su argumento y, cuando exista, la
   alternativa descartada y por qué se descartó. Prohibido "porque es lo habitual": o hay razón o no
   se escribe.
3. **Errores detectados** — los reales, con el síntoma, la causa y la evidencia que los delató.
   Incluye los propios del agente, no solo los del código.
4. **Cómo se iteró hasta una solución válida** — la secuencia RED → diagnóstico → decisión → GREEN,
   con los números que la justifican.
5. **Conclusión: qué se aprende de esto** — el principio transferible a otro proyecto, en dos o tres
   párrafos. Es la sección que Albert se va a releer.

Reglas: nada de métricas inventadas ni redondeadas a favor; si algo no se midió, se dice. Si una
decisión la tomó Albert, se registra como suya y con su motivo. Los documentos se versionan junto al
código que explican.

## 12. Definición de hecho (por tarea)

- [ ] Tests escritos primero, con RED y GREEN anotados.
- [ ] Lint, tipos y tests en verde en local.
- [ ] Work-unit commit en `feat/*` o `fix/*` con Conventional Commit; hash anotado.
- [ ] RDD assess ejecutado y anotado.
- [ ] Criterios de aceptación del `BRIEF.md` cubiertos por la tarea marcados con su evidencia.
- [ ] Feature document actualizado: progreso y siguiente paso.

## 13. Nunca

- Hacer push o abrir PRs sin el sí explícito de Albert (el push) o en absoluto (las PRs).
- Commitear en `main` o `dev`, hacer force push o reescribir historia compartida.
- Llamar a la API real de IA en los tests o en el CI normal.
- Ampliar el alcance del `BRIEF.md` sin autorización.
- Dejar que el LLM decida o calcule lo que puede hacer el código.
- Instalar paquetes con un gestor distinto de `uv` (backend) o `pnpm` (frontend).
- Desactivar RDD, TDD, lint o tipos para "ir más rápido".
