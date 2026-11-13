# S8 · Feedback del usuario

## 1. Qué se ha construido

Dos pulgares debajo de cada respuesta y una tabla en Postgres que guarda esos votos. El objetivo no
es tener métricas de producto: es **convertir cada respuesta mal valorada por un usuario en una
pregunta candidata** para el set de evaluación, que hasta ahora se anotaba a mano. Incluye un comando
que vuelca los votos negativos en el formato de `evals/preguntas.yaml`.

## 2. Cómo se ha hecho y por qué así

### Decisión: una fila por voto, no un historial de consultas
- **Qué se eligió.** La tabla `feedback` guarda pregunta, respuesta, citas validadas, modelo, voto y
  comentario. No existe una tabla de consultas.
- **Por qué.** El BRIEF pide guardar el voto «en base de datos para ampliar el set de evaluación» y,
  en la misma página, prohíbe persistir el historial. Guardar solo lo valorado satisface lo primero
  sin violar lo segundo. La alternativa —guardar todas las consultas y referenciarlas— habría creado
  exactamente el registro de actividad que el §6 descarta.

### Decisión: idempotencia por huella de pregunta + respuesta
- **Qué se eligió.** Una columna `huella` (sha256 de pregunta + respuesta, normalizadas) con índice
  único: volver a votar **actualiza** la fila.
- **Por qué.** El usuario tiene derecho a cambiar de opinión y el set no debe llenarse de duplicados
  de la misma respuesta. Verificado en ejecución: dos POST seguidos devuelven el **mismo id** con
  `actualizado: true` y el voto cambiado.

### Decisión: el exportador propone, no decide
- **Qué se eligió.** `python -m app.feedback_export` escribe YAML con la forma del set anotado, pero
  nunca toca `evals/preguntas.yaml`.
- **Por qué.** Un voto negativo no es una anotación: es una señal de que alguien debería mirar esa
  respuesta. La anotación exige decidir el artículo esperado y si el sistema debería abstenerse. Un
  script no puede hacer eso sin inventar la respuesta correcta.

### Decisión: la privacidad se cuenta con dos hechos separados
- **Qué se eligió.** El pie de la interfaz dice: las preguntas se procesan en la UE (NaN Builders),
  que declara no registrar prompts ni respuestas ni entrenar modelos; y las valoraciones sí se
  guardan en esta instalación.
- **Por qué.** Se descartó la frase «tu pregunta no se envía a ningún otro sitio» porque es falsa: la
  pregunta viaja a la API para generar la respuesta. Cumplir el RGPD no significa que el dato no se
  transmita, significa que se trata con garantías. La afirmación que se publica se cita **con
  atribución** al proveedor, no como hecho propio.

## 3. Errores detectados

### La copia prometía privacidad que el sistema no tiene
- **Cómo se detectó.** Leyendo la línea antes de aceptar el trabajo del worker.
- **Causa.** El worker escribió una confirmación razonable pero no verificable.
- **Qué se hizo.** Copy reemplazada por la única verdad comprobable, y un comentario en el código que
  explica por qué no puede volver a introducirse. Además, un aviso de datos con la declaración del
  proveedor, citada.

### `GET /feedback?limit=` rompía el contrato de errores de toda la API (R3-001, crítico)
- **Cómo se detectó.** Revisión nativa; el refutador lo corroboró con evidencia determinista.
- **Causa.** Declarar `limit` como `int` con `ge=1` delega la validación en FastAPI, que responde
  `{"detail": [...]}`. Era el único endpoint con un sobre distinto.
- **Qué se hizo.** Parseo manual del parámetro y 422 con el sobre propio (`limite_invalido`), con
  test que falla contra el comportamiento anterior (`{"detail": ...}` en el mensaje del assert).

### Mis propios tests quedaron desalineados al cambiar la copy
- **Cómo se detectó.** Dos gates rojos seguidos: el unitario y el e2e afirmaban el texto viejo.
- **Causa.** Cambiar copy es cambiar comportamiento observable; toqué el componente sin correr los
  tests que la fijaban.
- **Qué se hizo.** Actualizados ambos a la nueva afirmación, que además es más precisa («se guarda en
  esta instalación»).

### Los bindings del revisor no se pueden transcribir a mano
- **Cómo se detectó.** Dos rechazos `collectBinding is missing or stale`: primero por omitir el campo
  `validationRequest`, después por perder un `\n` final dentro de `policyContent`.
- **Causa.** Son identificadores opacos y largos; copiarlos a ojo introduce errores invisibles.
- **Qué se hizo.** Se dejan de escribir a mano: se decodifica el STATUS nativo y se envía la cadena
  canónica que produce el decodificador.

## 4. Cómo se iteró hasta una solución válida

1. Specs y contrato de API fijados **en los dos handoffs** (backend y frontend en paralelo), para que
   ninguno inventara su propia forma del `POST /feedback`.
2. RED de cada mitad por separado: backend `ModuleNotFoundError`; frontend botones inexistentes.
3. GREEN con 181 unitarios y 33 de integración en backend, 12 unitarios y 3 e2e en frontend.
4. Revisión nativa (`risk` + `reliability`): 3 hallazgos, 1 crítico corroborado por el refutador.
5. Corrección acotada declarada en **64 líneas de diff** (presupuesto 200), validada por un validador
   dirigido: `approved`.
6. Quedan dos WARNING no bloqueantes (coerción de `"1"` a int en Pydantic; el estado del botón tras
   un fallo), anotados como trabajo posterior.

## 5. Conclusión: qué se aprende de esto

**Una promesa de privacidad es una afirmación técnica, y se audita como las citas de la ley.** El
sistema entero está construido sobre la idea de que ninguna frase va sin respaldo; la interfaz no
puede ser la excepción. «No se envía a ningún otro sitio» era falso y habría pasado desapercibido
porque suena bien. La regla que queda: cada afirmación sobre datos se escribe con lo que el
proveedor declara y con atribución explícita, y se separa el tránsito (ellos) del almacenamiento
(nosotros).

**Los frameworks tienen bordes donde rompen tus contratos.** FastAPI valida por su cuenta y responde
con su propio formato: adoptar un sobre de errores propio obliga a revisar cada parámetro que el
framework pueda rechazar antes que tú. El test que lo fija no comprueba «devuelve 422», comprueba
**qué cuerpo** devuelve, porque el status era correcto incluso en la versión defectuosa.

**Trabajar con identificadores opacos exige automatizar la copia.** Cuando un sistema te da un
binding que debe devolverse byte a byte, transcribirlo es una fuente de fallos silenciosos: se
genera, se verifica contra el original y se envía; nunca se reescribe de memoria.
