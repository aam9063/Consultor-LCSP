# CL-01 · Esqueleto del monorepo, Compose con pgvector, `/health` y CI mínimo

## 1. Qué se ha construido

El andamiaje sobre el que se construyó todo lo demás: un monorepo con backend FastAPI
(`/backend`, Python 3.14 gestionado con uv), frontend Vite + React + Tailwind (`/frontend`,
pnpm) y una pila `docker compose` con tres servicios (`db`, `api`, `web`), todos con
healthcheck, donde la base es PostgreSQL 18 con la extensión `pgvector` creada por la
primera migración de Alembic. Además: el endpoint `GET /health`, la configuración
tipada con `pydantic-settings` y un workflow de CI (lint, tipos, tests, build).

Se cerró en 5 commits de `feat/cl-01-skeleton` con 2.411 líneas autoradas (sin contar
lockfiles). El slice excede la guía de ~400 líneas porque es el arranque de todo el
repositorio; los slices siguientes volvieron a la guía.

## 2. Cómo se ha hecho y por qué así

### Decisión: el proyecto avanza en paralelo con Radar de Pliegos
- **Qué se eligió.** NO esperar a cerrar la Fase 1 de Radar de Pliegos: Consultor LCSP se
  desarrolla a la vez. Decisión explícita de Albert, que anuló la premisa del BRIEF
  ("proyecto secundario") en lo que respecta al calendario.
- **Por qué.** Las consecuencias técnicas llegaron enseguida: como Radar de Pliegos ya
  ocupa los puertos 5432, 8000 y 5173 en esta máquina, este proyecto usa en el host
  **5433** (db), **8001** (api) y **8080** (web). Ejecutar dos proyectos al mismo tiempo
  también obligó a ser estricto con versiones fijadas y lockfiles, para que ningún
  `uv sync` o `pnpm install` arrastre dependencias del otro.

### Decisión: bootstrap de Git en tres pasos
- **Qué se eligió.** Commit inicial en `main` (AGENTS.md, BRIEF.md, .gitignore), luego la
  rama `dev` y desde ahí `feat/cl-01-skeleton`. Decisión de Albert.
- **Por qué.** Deja `main` como punto de referencia limpio antes de cualquier código, y
  respeta la regla de trabajo del repo: nunca commitear directamente en `main` ni `dev`.

### Decisión: revisar el andamiaje por slices, no de una pieza
- **Qué se eligió.** La revisión nativa (RDD) del scaffold se hizo por slices: API, web e
  infra, un commit por bloque, con 5 commits en total. Decisión de Albert tras el aborto
  de la revisión completa.
- **Por qué.** La primera tentativa fue clasificar como candidata de revisión el
  andamiaje completo: 52 ficheros, 5.106 líneas. La revisión nativa abortó con el error
  `lens_context_budget_exceeded`: el contexto que necesita el revisor no entraba. La
  alternativa descartada (forzar la revisión entera de otro modo) no existe: el límite es
  del revisor, no de la invocación. Partir en commits pequeños no solo hacía viable la
  revisión; además cada commit ya era una unidad coherente (`feat(api)`, `feat(web)`,
  `feat(infra)`), así que el candidato natural de revisión y el commit coincidían.

### Decisión: TypeScript fijado en 6.0.3
- **Qué se eligió.** `typescript` en la versión 6.0.3, no la 7.0 disponible por entonces.
- **Por qué.** `typescript-eslint` rechazó explícitamente TS 7.0 al instalarlo, y el
  linting estricto es un pilar del repo. La alternativa (esperar soporte del plugin)
  bloqueaba el arranque. Fijar la versión también es obligación del AGENTS.md.

## 3. Errores detectados

### El CI moría en "Set up job" antes de ejecutar un solo paso
- **Cómo se detectó.** Primer push real de la rama: el run de GitHub Actions (43222982952)
  falló sin ejecutar nada, en la fase "Set up job".
- **Causa.** El workflow usaba `astral-sh/setup-uv@v10`. Esa ref no existe: el action solo
  mantiene majors flotantes hasta `v7` y el resto son tags de release concretos. Un error
  local (lint, build) lo habría visto antes un comando; un error en el nombre de una
  action solo se manifiesta en CI, y en la fase más temprana.
- **Qué se hizo.** Se fijó `@v10.3.3`, un tag que existe (commit `32cb185`). El run
  siguiente (43223603050) pasó los tres jobs, incluidos pasos del backend que hasta
  entonces nunca se habían ejecutado de verdad (Alembic contra el servicio de Postgres).

### El contenedor de Postgres salía con código 1
- **Cómo se detectó.** `docker compose up -d --wait` no alcanzaba el estado `healthy`.
- **Causa.** PostgreSQL 18 cambió el punto de montaje de datos a `/var/lib/postgresql`;
  el volumen `pgdata` montado donde la 17 usaba `/var/lib/postgresql/data` dejaba un
  directorio sin lo esperado y el servidor no arrancaba.
- **Qué se hizo.** `pgdata:/var/lib/postgresql` en el servicio `db`.

### El healthcheck de nginx fallaba por IPv6
- **Cómo se detectó.** El `web` no llegaba a `healthy` aunque la página servía bien desde
  el navegador del host.
- **Causa.** el `wget http://localhost/` del healthcheck resolvió a IPv6 dentro del
  contenedor y nginx solo escuchaba en IPv4.
- **Qué se hizo.** Healthcheck contra `127.0.0.1` y `listen [::]:80` en nginx: se cubren
  las dos pilas y el chequeo no depende de cómo resuelva `localhost`.

### Cuatro hilos construían cuatro engines
- **Cómo se detectó.** Revisión nativa del slice API (lineage `review-3d828745be58ead1`,
  565 líneas, lentes `risk` + `resilience`): hallazgo severo corroborado
  `R4-async-singleton-race` — los singletons `_engine`/`_session_factory` se
  inicializaban lazy sin cerrojo.
- **Causa.** Patrón clásico "inicialización perezosa sin exclusión mutua": en async, varias
  corrutinas/hilos pueden pasar a la vez por el check `if x is None`.
- **Qué se hizo.** Corrección `fix(api)` con `threading.Lock` alrededor de la
  construcción, y test que la fija: RED con el cerrojo neutralizado (4 hilos → 4 engines),
  GREEN con él (1 engine y la misma factory). Commit `58e1a8b`.

### Ficheros que el agente no podía crear
- **Cómo se detectó.** Al cerrar el slice, `.env.example` seguía inexistente aunque el
  AC-01 lo exige.
- **Causa.** La política del harness bloquea la creación del fichero por tratarse de una
  plantilla de entorno.
- **Qué se hizo.** Lo creó Albert a mano, sin secretos, y se versionó (`0c4138b`).

## 4. Cómo se iteró hasta una solución válida

TDD desde el primer commit, con RED y GREEN observados y anotados en el feature document:
`assert 404 == 200` antes de que existiera `/health`; `ModuleNotFoundError: app.config`
antes de la configuración; un import de `src/app/App` inexistente antes del shell de la
UI; `NoResultFound` en `pg_extension` antes de la migración de pgvector. Cada uno se pasó
a verde con el mínimo código y los gates (`ruff`, `ruff format --check`, `mypy --strict`,
`pytest`, `pnpm lint/typecheck/vitest/build/format:check`, `docker compose config/build/up --wait`,
`actionlint`) verificados a mano.

La iteración sobre la revisión fue la más cara: candidato completo → abort nativo por
presupuesto → división en 5 commits → revisión del slice API → hallazgo severo
corroborado → corrección con RED/GREEN propio. Y una lección de proceso al final: al
volver a la rama, el candidato de revisión volvió a ser todo el andamiaje (53 ficheros) y
la lineage quedó `stale` (`scope_changed`): revisar slices por checkout detached no es
compatible con la proyección de workspace del revisor, y el slice API no pudo cerrarse
nativamente. Por eso Albert decidió abandonar esa lineage envenenada con
`operator_disposition` y ponerla en cuarentena (junto con excluir los dos mockups no
generados por el agente de la candidata), y no reintentar la revisión sobre un candidato
que ya no reflejaba lo evaluado.

## 5. Conclusión: qué se aprende de esto

Un esqueleto parece trabajo menor y no lo es: es donde se toman las decisiones que todo lo
demás hereda (versiones, puertos, estructura de capas, cómo se inicializa la base). Los
cuatro defectos de este slice (action inexistente, punto de montaje de Postgres 18,
healthcheck IPv6, carrera en el engine singleton) no son error de lógica de negocio: son
error de supuestos sobre el entorno y el runtime. Ninguno se habría detectado leyendo
código; todos aparecieron ejecutando la pila completa o pasando revisión con lentes de
riesgo. "Arrancar de verdad antes de continuar" es más barato que hacerlo después.

El segundo aprendizaje es de proceso: el tamaño de una unidad de revisión es un recurso
real con presupuesto propio. Un candidato de 5.106 líneas no se revisa: se aborta. Como el
commit convencional ya exigía unidades coherentes, partirlas costó poco; si los commits
fueran una mezcla de refactor y feature, habría costado reescribir historial. Y por
último: si tu herramienta no puede crear un fichero (por política o por diseño), eso es un
bloqueo que se reporta y alguien humano lo resuelve — no una invitación a inventar un
atajo.
