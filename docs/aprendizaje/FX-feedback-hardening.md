# FX · Endurecer el feedback: voto booleano y estado mentiroso

## 1. Qué se ha construido

Dos correcciones pequeñas sobre S8, ambas nacidas de la revisión nativa pero **ninguna** por la razón
que el revisor decía:

1. Un `voto: true` en JSON dejaba de ser un error: se convertía en un voto positivo. Ahora se rechaza
   con `422 voto_invalido`.
2. Si fallaba el envío del voto, el pulgar quedaba marcado como pulsado. Ahora se revierte y el aviso
   explica el fallo.

## 2. Cómo se ha hecho y por qué así

### Decisión: verificar el hallazgo antes de tocarlo
- **Qué se eligió.** Antes de arreglar nada, se ejecutó el endpoint real con cada valor problemático.
- **Por qué.** Los dos hallazgos eran **inferenciales**, no deterministas. Comprobarlos costó una
  llamada; arreglar código sano habría costado una revisión, un commit y confianza perdida en el
  historial. Y de hecho, uno estaba mal planteado y otro apuntaba a la línea equivocada.

### Decisión: la validación del voto vive en un solo sitio
- **Qué se eligió.** El campo del cuerpo deja de estar tipado (`voto: Any`) y `normalize_voto` sigue
  siendo quien decide qué es un voto.
- **Por qué.** El bug apareció por **duplicar** la validación: Pydantic ya había convertido `true` en
  `1` antes de que el validador lo viera. Dos validadores en serie no son más seguros: el primero
  puede transformar el dato y dejar al segundo sin nada que juzgar.

### Decisión: la interfaz no muestra un voto que no se guardó
- **Qué se eligió.** Actualización optimista con reversión en el error.
- **Por qué.** Mostrar el pulgar pulsado tras un fallo es una afirmación falsa sobre el estado del
  sistema, igual que la frase de privacidad corregida en S8. La regla del proyecto —nada de
  afirmaciones sin respaldo— aplica también a un icono.

## 3. Errores detectados

### El revisor acertó en el síntoma, no en la causa
- **Cómo se detectó.** Ejecutando: `voto: "1"` y `voto: 1.0` ya devolvían 422. En cambio `voto: true`
  devolvía 201.
- **Causa.** El hallazgo hablaba de cadenas numéricas; el agujero real era `bool`, que en Python es
  subclase de `int`.
- **Qué se hizo.** Se corrigió el agujero real y se dejó constancia de que `R3-002`, como estaba
  escrito, estaba refutado.

### El otro hallazgo apuntaba a la línea equivocada
- **Cómo se detectó.** `R3-004` señalaba `answerText.ts:8` como «cast silencioso»; esa línea es una
  unión de tipos y en el fichero no hay ningún `as` ni `!`.
- **Causa.** Los números de línea de un revisor son una pista de la revisión, no una verdad del árbol.
- **Qué se hizo.** `R3-004` se cierra como refutado con la evidencia, sin tocar el fichero.

### Mi test nuevo apuntaba a la base de datos equivocada
- **Cómo se detectó.** El test falló con `password authentication failed`: lo corrí sin `DATABASE_URL`
  y fue a parar al Postgres de **otro proyecto** que escucha en 5432.
- **Causa.** Un test que ejercita la app completa necesita la base; lo había puesto en `tests/unit/`.
- **Qué se hizo.** Movido a `tests/integration/` y verificado con la variable correcta.

### Los backticks se comieron el mensaje de commit
- **Cómo se detectó.** El commit se creó, pero el cuerpo decía «Pydantic coercía [vacío] a [vacío]»:
  bash había interpretado los backticks como sustitución de comandos.
- **Qué se hizo.** Reescritura local de los dos commits con el mensaje en un fichero, sin backticks en
  la línea de comandos. Los mensajes son documentación: un commit con el texto mutilado es un
  documento roto.

## 4. Cómo se iteró hasta una solución válida

1. Verificación empírica de los tres pendientes: **uno refutado** (`R3-002` tal como estaba escrito),
   **uno refutado** (`R3-004`), **uno parcialmente cierto** (`R3-003`, sin la parte de «bloquea»).
2. Un cuarto problema, no reportado por nadie, apareció en esa verificación: el voto booleano.
3. RED de cada corrección: `201` en el POST con `true`; `aria-pressed="true"` tras un fallo.
4. GREEN con 187 pruebas unitarias, 34 de integración, 12 de frontend y 3 e2e.

## 5. Conclusión: qué se aprende de esto

**Un hallazgo de revisión es una hipótesis, no un veredicto.** Los revisores automáticos leen rápido y
a veces deducen de más; el coste de comprobarlo es una llamada y el de creerlo es arreglar lo que no
está roto y dejar intacto lo que sí. La disciplina es la misma que con las citas legales: la afirmación
se sostiene con evidencia del sistema, no con la autoridad de quien la firma.

**Dos validadores en serie pueden ser peores que uno.** Pydantic convirtió `true` en `1` antes de que
la lógica de negocio mirara el valor: el segundo validador ya estaba juzgando un dato transformado. Si
la regla importa, el dato tiene que llegar crudo al lugar donde se decide.

**La interfaz es parte del sistema de creencias del usuario.** Un pulgar pulsado tras un fallo, o una
frase que promete que la pregunta no sale de casa, son la misma clase de error que una cita inventada:
algo que el sistema afirma y no puede sostener. Corregirlos no es cosmética, es coherencia.
