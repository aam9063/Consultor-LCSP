# Feature: Consultor LCSP — Fase 2 · S8 Feedback de usuario

Spec: `BRIEF.md` (Fase 2, S8) + `AGENTS.md`. Fase 1 cerrada y mergeada a `dev` en `bd02c1c`.
Ejecución: **solo S8**. S7 queda paralizada por decisión de Albert (L2).

**Objetivo (BRIEF §5, Fase 2, literal):**

> - **S8 · Feedback del usuario**: pulgar arriba o abajo por respuesta, guardado en base de datos para ampliar el set de evaluación.

**Problema que resuelve:** el set de evaluación son 25 preguntas anotadas a mano. Cada consulta real
que un usuario valora como mala (o buena) es una pregunta candidata con su respuesta y sus citas:
material que hoy se pierde. Sin este registro, ampliar `evals/preguntas.yaml` depende de que alguien
se acuerde de qué falló.

## Specs

- **S1 · Registro del voto.** Cada respuesta mostrada en la vista de consulta ofrece pulgar arriba y
  pulgar abajo. Un voto guarda: la pregunta, la respuesta, las citas validadas, el modelo, el voto
  (`1` / `-1`) y un comentario opcional, con su marca de tiempo.
- **S2 · Persistencia mínima.** Se guarda **solo la respuesta valorada**, no el historial de
  consultas. El BRIEF §6 prohíbe persistir el historial, y su §8 admite una tabla `consulta` "solo
  para depurar y evaluar": se resuelve con una fila autocontenida por voto, sin sesión ni usuario.
- **S3 · Idempotencia del voto.** Volver a valorar la misma respuesta actualiza el voto existente en
  lugar de acumular filas duplicadas. La clave es la huella (hash) de `pregunta + respuesta`.
- **S4 · API tipada.** `POST /feedback` acepta el voto y devuelve el registro creado o actualizado;
  `GET /feedback` devuelve los votos para poder revisarlos al ampliar el set. Errores tipados con el
  mismo sobre `{"error": {"code", "message"}}` que el resto de la API.
- **S5 · Exportación al set de evaluación.** Comando que vuelca los votos negativos en un YAML con
  la forma de `evals/preguntas.yaml` (`pregunta`, `articulos_esperados` vacío, `debe_abstenerse`
  por defecto `false`), para que un humano los anote. El comando **no** escribe en
  `evals/preguntas.yaml`: propone, no decide.
- **S6 · Interfaz.** Botones accesibles (etiqueta, `aria-pressed`, foco visible), estado visible
  tras votar, y el aviso de que el voto se guarda para mejorar el sistema. Sin llamadas reales a la
  IA en los tests.
- **S7 · Verificación.** Unitarios de validación y cálculo de huella, integración contra Postgres
  real para el alta y la actualización idempotente, frontend con Vitest y e2e con la API stubbeada.
  CI en verde antes del merge.

## Non-goals

Autenticación o identificación de usuario; moderación de comentarios; métricas de producto
(promedio de votos, dashboards); escritura automática del set de evaluación; tocar S7.

## Configuración de proceso

- **TDD: activado.** Fuente `AGENTS.md` §4. Runners: `uv run pytest`, `uv run pytest tests/integration`,
  `pnpm vitest run`, `pnpm e2e`. Se anota RED y GREEN por tarea.
- **RDD: activado.** `assess` después de cada work-unit commit; al cerrar el slice, revisión 4R. Si
  el assess sale `high`, revisión nativa completa.
- **Documentación de aprendizaje:** obligatoria al cerrar (`docs/aprendizaje/S8-feedback.md`).
- **Entrega:** autorización permanente de Albert (AGENTS.md §6): push, PR contra `dev`, CI verde,
  merge commit, nunca a `main`.

## Tasks

| ID | Tarea | Specs | Ruta | Commit |
| --- | --- | --- | --- | --- |
| FB-01 | Modelo `feedback`, migración y migración inversa | S1, S2, S3 | pendiente | — |
| FB-02 | `POST /feedback` y `GET /feedback` con validación tipada | S4, S3 | pendiente | — |
| FB-03 | Comando de exportación a YAML para anotar | S5 | pendiente | — |
| FB-04 | Botones de voto en la vista de consulta | S6 | pendiente | — |
| FB-05 | Documento de aprendizaje y cierre | S7 | pendiente | — |

## Evidencias de verificación

Se rellena por tarea: test escrito, RED, GREEN, checks y hash del commit.

## Progreso y siguiente paso

- Progreso: 0/5. Feature document creado; branch `feat/lcsp-s8-feedback` desde `dev` (`bd02c1c`).
- Siguiente paso: FB-01 y FB-04 en paralelo (superficies disjuntas: backend y frontend).

## Log

- **L1 (autorización de Albert, 2026-11-12, literal):** "Si pushea, y desde ya tienes permiso para abrir pr contra dev, vigilar el ci que no falle nada, si falla lo corrigis hasta que este en verde y mergear a dev pero nunca de dev a main. Cuando este cada feature o fix mergeado a dev continuas con la siguiente tarea. Acuerdate de documentar todo en md como te contado antes"
- **L2 (decisión de Albert, 2026-11-12, literal):** "conexion con radar de pliegos? eso paralizalo porque aun no esta terminado" — S7 no se implementa hasta que Radar de Pliegos esté terminado.
- **L3 (decisión de Albert, 2026-11-12, literal):** "mergea igual" — la PR #1 se mergeó con el check externo de GitGuardian en rojo, tras desestimar sus tres incidentes como falsos positivos.
- **L5 (decisión de Albert, 2026-11-12, literal):** "los modelos de nan cumplen el RDGPD de la UE asi que nada sale y es privado". Aclarado que conformidad RGPD no equivale a ausencia de tratamiento, Albert aportó la declaración pública de la FAQ de NaN: *"¿A dónde van mis datos? Se procesan en la Unión Europea, sin registrar prompts ni respuestas. Tu API key es personal e intransferible. Tu código no entrena ningún modelo y tus datos nunca salen de tu sesión."* La interfaz cita esa declaración **con atribución** y separa dos hechos distintos: el tránsito al proveedor (UE, sin registro ni entrenamiento) y el voto, que **sí** se guarda en esta instalación. Se descartó la frase "nada sale" por ser falsa: la pregunta viaja a la API para generar la respuesta.
- **L4 (hecho, 2026-11-12):** Fase 1 mergeada en `bd02c1c`; CI de `dev` verde en el run `43253302851`; branch de S8 creada desde `dev`.
