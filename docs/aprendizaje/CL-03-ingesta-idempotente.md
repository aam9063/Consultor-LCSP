# CL-03 · Ingesta idempotente con embeddings y `tsvector`

## 1. Qué se ha construido

El pipeline que lleva los chunks del parser a la base, con sus embeddings. Tres piezas:

- **Puerto `LLMClient`** (un `Protocol` de Python) con dos implementaciones:
  `NanLLMClient`, el cliente real contra la API de NaN Builders, y `FakeLLMClient`, un
  cliente determinista para tests. Ningún test llama a la API real; eso es regla del
  AGENTS.md y este slice la materializa.
- **`NanLLMClient`** de embeddings: lotes de `EMBEDDING_BATCH_SIZE`, semáforo de 5
  concurrentes (los límites de la clave son 60 req/min y 7 concurrentes), timeout de 60 s,
  backoff exponencial con jitter ante 429 y 5xx, validación de que cada embedding tiene
  4.096 dimensiones y ninguna clave registrada en los logs.
- **`ingest_chunks` y la CLI** `python -m app.ingest <xml>`: inserción idempotente contra
  la clave única `(fuente_id, articulo, coalesce(apartado,''))`, embedimiento solo de lo
  nuevo o cambiado, y modo `--dry-run` que parsea y reporta sin escribir ni llamar a la
  API (ni siquiera construye el cliente real).

La idempotencia quedó probada a escala real, no con el fixture: doble ingesta del corpus
completo con `FakeLLMClient` — run 1: `inserted=580, embedded=580`; run 2:
`inserted=0, updated=0, skipped=580, embedded=0`; filas 580 → 580. AC-03 cumplido.

## 2. Cómo se ha hecho y por qué así

### Decisión: toda llamada a IA detrás de un puerto con fake determinista
- **Qué se eligió.** El puerto `LLMClient` como única puerta hacia la API, con el
  `FakeLLMClient` controlado por guiones (scripts) en los tests.
- **Por qué.** Permite que la lista de respuestas y fallos sea parte del test: podés dictar
  "devuelve 3 embeddings y luego falla". Sin el fake, cada test de ingesta dependería de la red. La alternativa
  (mockear con librerías de mocking el cliente HTTP) habría acoplado el test al formato
  interno del SDK en cada cambio de versión; con el puerto solo se adapta la implementación
  real.

### Decisión: idempotencia por clave única, no por "buscar y si no existe insertar"
- **Qué se eligió.** La unicidad vive en la base (clave única de expresión) y la ingesta
  la usa como contrato: filas nuevas se insertan, las existentes se saltan.
- **Por qué.** Un check-then-insert en Python tiene carrera y, además, definiría la
  identidad del chunk dos veces (en código y en esquema). Con la clave única, repetir la
  ingesta no puede duplicar nada aunque dos procesos corran a la vez, y la base expresa la
  regla por sí sola. El embedimiento selectivo (solo lo nuevo o cambiado) es la
  consecuencia práctica: no gastar cuota re-embebiendo 580 artículos sin cambios.

### Decisión: `--dry-run` que no toca nada
- **Qué se eligió.** Un modo que parsea, cuenta chunks y calcula lotes de embeddings sin
  escribir filas ni construir siquiera el cliente real.
- **Por qué.** Ingestar es la operación más cara del sistema (37 lotes de embeddings para
  el corpus completo). Tener una forma de ver "qué pasaría" sin riesgo convierte el
  comando en herramienta de diagnóstico cotidiana, y el costo de pruebas se separó del
  costo de ingesta real.

### Decisión: `Fuente.fecha_version` NOT NULL DATE
- **Qué se eligió.** La fecha de la versión consolidada es obligatoria y de tipo fecha.
- **Por qué.** Todo lo que el sistema responde se justifica contra "la LCSP consolidada a
  fecha X": sin esa fecha el aviso de versiones antiguas del BRIEF no es verificable.
  Que sea NOT NULL desde la migración hace que ninguna fuente sin fecha pueda colarse,
  ni por ingesta ni por parche manual.

## 3. Errores detectados

### El fake que se queda sin guion lanzó una excepción... y eso fue útil
- **Cómo se detectó.** En algún test del worker, el `FakeLLMClient` se quedó sin guion
  (scripts) y lanzó una excepción en vez de devolver datos inventados.
- **Causa.** El guion del fake describe exactamente lo que el test asume que pasará; si el
  código llama más veces de las previstas, el fake no tiene qué responder.
- **Qué se hizo.** Nada por "arreglar": el comportamiento quedó como diseño del fake. La
  lección registrada: un test doble estricto que falla cuando una suposición no se cumple
  es un detector de supuestos equivocados. Varias suposiciones sobre cuántas llamadas hace
  el pipeline salieron a la luz gracias a ese error.

### Limitaciones conocidas, anotadas y no corregidas (todavía)
- `NanLLMClient` reintenta 429/5xx pero no `APIConnectionError` ni timeouts de red: para
  la carga real de 37 lotes quedó anotado como decisión pendiente antes de la ingesta
  real con clave.
- El semáforo de 5 es por llamada a `embed()`, no global entre ingestas concurrentes: dos
  ingestas en paralelo podrían sumar 10 llamadas simultáneas. Anotado, no corregido.
- **Por qué no se corrigieron acá.** Ninguno impide la tarea ni su verificación; ampliar
  alcance por hallazgo sin pedirlo está prohibido por el AGENTS.md.

## 4. Cómo se iteró hasta una solución válida

RED del worker observado y anotado: `ModuleNotFoundError` de `app.adapters.llm`,
`app.ingest` y `app.services.ingest`. GREEN: 27 unitarios, 7 de integración y 1 de datos.
Los gates (`ruff`, `ruff format --check`, `mypy --strict` en 35 ficheros) en verde.

La iteración decisiva fue la verificación a escala real del orquestador, que no repitió el
fixture sino que jugó el juego completo: `--dry-run` sobre el XML real desde la raíz con
la forma literal del BRIEF (`uv run --project backend python -m app.ingest
data/lcsp/lcsp-consolidada.xml --dry-run`) → `{"chunks": 580, "embedding_batches": 37}`,
exit 0. Después, la doble ingesta descrita en la sección 1 contra Postgres y con FakeLLMClient.
El paso de `dry-run` a doble ingesta real es donde aparece lo que un fixture no puede
mostrar: conteos exactos de insertados/saltados/embebidos y el aprobado formal del AC-03.

## 5. Conclusión: qué se aprende de esto

La idempotencia se demuestra, no se declara. "Es idempotente porque uso `ON CONFLICT`"
es una hipótesis hasta que un test la ejecuta dos veces sobre el corpus completo y cuenta
filas. Y la demostración a escala real importa: la segunda pasada con 580 filas reales
ejercita la clave única de expresión, el orden de comparación y el conteo de "nada
cambiado" de una manera que un fixture de 3 artículos no puede.

El segundo aprendizaje es sobre el diseño del doble de tests. Un fake que responde
exactamente lo que su guion dice y **falla** cuando se le pide de más es más útil que uno
"amable" que inventa datos: convierte cada desajuste entre lo que el test asume y lo que
el código hace en un fallo visible y temprano. El costo de un fake estricto se paga una
vez; el costo de un fake flexible se paga debugging mal rastreado para siempre.
