# FX · Reintento de errores de red en el cliente LLM

## 1. Qué se ha construido

Un cambio de tres líneas de fondo en `backend/app/adapters/llm.py`: el reintento que ya existía para
`429` y `5xx` ahora también cubre los fallos de transporte (`APIConnectionError`, que incluye los
tiempos de espera agotados). Un corte de red momentáneo deja de abortar la operación: se reintenta con
el mismo backoff exponencial con jitter y, si se agotan los intentos, falla con el error tipado.

## 2. Cómo se ha hecho y por qué así

### Decisión: reintentar los fallos de red, no solo los estados HTTP
- **Qué se eligió.** Ampliar el `except` del helper compartido para incluir `APIConnectionError`.
- **Por qué.** Los dos fallos son igual de transitorios y ninguno es culpa de quien llama. El síntoma
  real: la ingesta del corpus son 37 lotes seguidos de embeddings; un solo corte de red en el lote 20
  mataba la ejecución entera y había que empezar de nuevo. Lo mismo podía ocurrir a mitad de una
  respuesta.
- **Alternativa descartada.** Reintentar en el llamador (ingesta o servicio) en vez de en el adaptador:
  habría duplicado la política de reintentos en cada punto de uso y dejado el problema abierto para
  cualquier llamada futura.

### Decisión: un solo helper y un único presupuesto de intentos
- **Qué se eligió.** El mismo `_send_with_retry` sirve a embeddings y a rerank; el error final sigue
  siendo `LLMRetriesExhaustedError`, que la API ya mapea a `502 llm_unavailable`.
- **Por qué.** Dos políticas distintas de reintento se desincronizan y nadie recuerda cuál aplica. Un
  solo límite (`_MAX_ATTEMPTS = 5`) también evita el bucle infinito que convertiría un proveedor caído
  en una petición colgada.
- **Lo que NO se toca.** Un `400`, `401` o `404` se propaga tal cual: reintentar una credencial inválida
  solo multiplica el fallo.

## 3. Errores detectados

### El reintento no cubría el fallo más probable en producción
- **Cómo se detectó.** Leyendo el `except` del helper al revisar los pendientes anotados del cierre de
  la Fase 1: solo capturaba `APIStatusError`.
- **Causa.** El código se escribió pensando en los límites de cuota del proveedor (429) y en sus caídas
  (5xx), que es lo que documenta la guía; los fallos de red no aparecían en ningún caso de prueba.
- **Evidencia de que era real.** Durante la carga real de 37 lotes no ocurrió, pero el riesgo estaba
  abierto: cualquier hipo de red habría costado la ingesta completa.

### El test no podía provocar el fallo hasta que el transporte lo permitió
- **Cómo se detectó.** Al escribir el RED.
- **Causa.** El doble de pruebas `ScriptedTransport` solo sabía lanzar estados HTTP por número; no
  había forma de guionizar una excepción arbitraria.
- **Qué se hizo.** El doble acepta ahora cualquier `Exception` en su guion y la lanza. Es un cambio en
  el test-double, no en la unidad bajo prueba: la unidad sigue siendo el adaptador real.

## 4. Cómo se iteró hasta una solución válida

1. **RED** con dos pruebas: dos fallos de red seguidos y luego éxito (debe acabar bien), y fallo de red
   persistente (debe lanzar el error tipado, no colgarse). Ambas fallaban con `APIConnectionError`
   propagándose.
2. **GREEN** con el `except` ampliado: 27 pruebas del cliente, 187 unitarias, 33 de integración, `mypy
   --strict` limpio.
3. **Revisión nativa** con lente `resilience` (90 líneas): aprobada, con una única sugerencia
   informativa.
4. Comportamiento conservado: un estado no reintentable sigue propagándose sin máscara.

## 5. Conclusión: qué se aprende de esto

**El reintento solo tapa lo que sabe nombrar.** Escribir `except` para los estados que documenta la guía
del proveedor deja fuera todo lo que ocurre antes de que exista una respuesta: DNS, TLS, timeouts, cortes
de red. En un sistema que hace 37 llamadas seguidas, el fallo probable no es el 429 que la guía menciona,
es la red. La pregunta correcta al diseñar reintentos no es «¿qué errores documenta el proveedor?» sino
«¿qué fallos son transitorios por naturaleza?».

**Reintentar no es insistir.** La diferencia está en el límite y en el criterio: cinco intentos con
backoff creciente para lo transitorio, cero reintentos para lo que nunca va a mejorar (una clave
inválida). Un reintento infinito convierte una caída del proveedor en una petición colgada, y un
reintento de un error de credenciales multiplica el fallo en lugar de suavizarlo.

**Un test-double también es código que evoluciona.** El guion del doble se amplió para poder lanzar
excepciones arbitrarias: sin eso, el caso de fallo de red era imposible de fijar. La regla: si no podés
provocar el fallo en un test, todavía no podés demostrar que lo arreglaste.
