# CL-05 · Generación con citas, validación y abstención

## 1. Qué se ha construido

La capa que convierte "pregunta + 6 chunks" en una respuesta auditable:

- **Dominio de citas** (`app.domain.citations`): parseo de `[art. X]` y `[art. X.Y]`,
  separación de la respuesta en afirmaciones y respaldo de cada afirmación contra los
  chunks recuperados.
- **Servicio de respuesta** (`app.services.answers`): decide la abstención **antes** de
  llamar al modelo, genera con `deepseek-v4-flash` y `json_schema` (sin tools), valida
  cada cita en código contra lo recuperado y reintenta **una sola vez**, pasándole al
  modelo el feedback de validación de su propio intento fallido.
- **API**: `POST /consultas` devuelve respuesta, citas (ya validadas), afirmaciones no
  respaldadas, aviso, modelo y chunks.

Verificado con los 580 chunks reales: AC-07 con el rerank forzado a 0.05 (bajo el umbral
de entonces, 0.35) → `abstencion=True`, el texto exacto "No encuentro base en la LCSP para
responder esto" y **0** llamadas al modelo de generación. AC-06 con un guion que responde
primero `[art. 999]` y después `[art. 998.2]` → **2** llamadas (un solo reintento), 0
citas válidas, 2 afirmaciones marcadas como no respaldadas y aviso presente. Camino feliz
con `[art. 107]` sobre una consulta que recupera el 107 → 1 llamada, cita válida, sin
aviso.

## 2. Cómo se ha hecho y por qué así

### Decisión: el generador nunca recibe `tools` junto con `json_schema`
- **Qué se eligió.** La llamada de generación pide salida estructurada con `json_schema`
  en `/chat/completions` y no registra ninguna herramienta.
- **Por qué.** El `json_schema` de `deepseek-v4-flash` solo funciona en `/chat/completions`
  sin tools: mezclar ambos en la misma llamada rompe la respuesta estructurada. El stack
  (AGENTS.md) lo documenta y este slice lo convierte en restricción estructural del
  cliente, no en memoria de quien escribe la llamada. La alternativa (usar `qwen3.6`,
  que sí soporta json_schema estricto con más comodidades) quedaba como plan B.

### Decisión: la abstención se decide antes de generar
- **Qué se eligió.** Si la mejor puntuación del reranker queda bajo el umbral, no se llama
  al LLM y la respuesta es la frase fija de abstención.
- **Por qué.** AC-07 lo exige, y el motivo es doble: ahorra una llamada (latencia y
  cuota) y, sobre todo, es la única forma de garantizar "no se llama al modelo": dejarle
  la abstención al modelo la pondría a merced del prompt. Con el corte previo,
  el test mide llamadas al fake y el resultado es determinista.

### Decisión: un solo reintento, con el feedback de validación en el prompt
- **Qué se eligió.** Ante una cita que no corresponde a ningún chunk recuperado, se
  reintenta una vez, inyectándole al modelo qué citas fallaron y por qué.
- **Por qué.** Un reintento infinito destruye la latencia objetivo (< 10 s) y puede
  degradar la respuesta; pero tampoco se deja al modelo solo. Pasar el propio error de validación
  como feedback es la corrección más barata que existe: el modelo ya sabe qué afirmación
  no tiene respaldo y dónde mirarlo. Si persiste tras el reintento, las afirmaciones quedan
  marcadas como no respaldadas (no se ocultan) y la UI muestra un aviso.

### Decisión: `citas` en la respuesta son solo las validadas
- **Qué se eligió.** El campo `citas` que ve la UI contiene únicamente citas respaldadas
  contra chunks recuperados. Las inventadas salen por `advertencia` /
  `afirmaciones_no_respaldadas`.
- **Por qué.** El chip de la UI abre el texto del artículo citado: un chip hacia un
  artículo inexistente sería un bug visible. La decisión del worker (aceptada) alineó el
  contrato de la API con lo que la UI puede hacer.

## 3. Errores detectados

### La primera evaluación real bajó a 90% de citas válidas: se enviaban respuestas sin ninguna cita respaldada
- **Cómo se detectó.** Primera corrida de CL-08 sobre el set original: 90% de respuestas
  con todas las citas válidas. Las dos falladas eran respuestas donde **ninguna** cita
  sobrevivió al reintento, y el sistema las enviaba igual, con aviso.
- **Causa.** La spec hablaba de validar citas y reintentar; el caso "todas las citas
  fallaron" quedaba como "respuesta con avisos", que sigue siendo texto sin respaldo.
- **Qué se hizo.** Decisión explícita de Albert tras leer el informe: cuando sobrevive
  cero citas, la respuesta se convierte en la abstención exacta. Es más estricto que la
  spec y para una herramienta legal es correcto: una respuesta sin ningún respaldo es
  justamente el modo de fallo que este producto existe para evitar. Commit `71c36eb`,
  con su test propio. Las parciales (alguna cita válida) siguen mostrándose con aviso.

### Criterio complementario del worker: la afirmación sin ninguna cita tampoco pasa
- **Cómo se detectó.** Durante el desarrollo: la spec solo habla de citas inválidas, no de
  afirmaciones sin cita.
- **Qué se hizo.** Una afirmación de la respuesta que no trae ninguna cita se marca igual
  como no respaldada. El criterio es más estricto que la spec y no oculta texto sin
  respaldo.

## 4. Cómo se iteró hasta una solución válida

RED del worker observado: `ModuleNotFoundError: app.domain.citations`,
`ImportError: ChatResponseError`, `AttributeError: generate_json` y
`TypeError: unexpected keyword 'generation_responses'`. GREEN: 94 unitarios y 21 de
integración. La verificación real comprobó los tres estados del servicio (abstención,
fallo persistente de citas, camino feliz) midiendo **llamadas al fake**, no solo la
respuesta: 0 / 2 / 1. Ese contador es la única prueba sólida de "antes de generar" y "un
solo reintento".

El ciclo que remata el slice vino de afuera (de la evaluación): corrida 1 de CL-08 →
90% de citas → lectura del informe → decisión de Albert (abstener si no sobrevive
ninguna cita) → RED/GREEN en `71c36eb` → corridas siguientes con 100%. Un ejemplo del
bucle completo: la evaluación no solo mide, además corrige diseño.

## 5. Conclusión: qué se aprende de esto

La abstención es una decisión del contrato, no un comportamiento emergente del prompt.
Pedirle al modelo "dime si no lo sabés" produce un "no lo sé" inestable; comparar la mejor
puntuación del reranker contra un umbral antes de gastar la llamada produce un "no lo sé"
verificable, contable y barato. Y la segunda barrera (validación de citas en código, no
del LLM) existe porque la regla es mecánica: una cita o está en los chunks recuperados o
no. Nunca pidas al generador juzgar algo que tu código puede decidir.

El otro aprendizaje es que el primer contacto con datos reales siempre destapa un caso que
la spec no contemplaba. Aquí fue "cero citas sobreviven": un caso paradójico donde el
sistema hace todo lo correcto (valida, reintenta, avisa) y aun así entrega el producto
equivocado. La respuesta correcta no fue alargar el aviso sino eliminar la entrega. En
herramientas de alto costo por error (legal, médico, financiero), "no mostrar nada" es
mejor que "mostrar algo sin respaldo con advertencia".
