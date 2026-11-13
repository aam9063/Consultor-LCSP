# S7 — Conexión con Radar de Pliegos

Fecha: 2026-11-13 · Commits: `3737eee` (spec), `04a34b9` (implementación) · Líneas: ~700 (4 ficheros
de producto, 3 de test)

## 1. Qué se ha construido

El puente entre los dos productos: Radar extrae del pliego las penalidades y la garantía definitiva
como texto literal, y ahora puede **empujarlas** a Consultor, que las contrasta contra la LCSP y
devuelve avisos tipados. Es el equivalente a pegar una cláusula en la vista del revisor, pero con el
origen de cada cita identificado (`penalidades` o `garantia_definitiva`) y sin que nadie copie y pegue
a mano.

## 2. Cómo se ha hecho y por qué así

- **Push, no pull.** Radar envía a `POST /revisiones/radar`; Consultor no llama a Radar. Razón: si
  Consultor consultara a Radar, cada consulta dependería de que Radar esté vivo, de una red Docker
  compartida entre dos compose y de una configuración de URL entre servicios. Con push, Consultor
  sigue siendo una aplicación autónoma, se prueba con fixtures y el acoplamiento es un contrato JSON,
  que es lo más débil posible. *Alternativa descartada:* pull por `licitacion_id`; habría hecho el
  producto dependiente de la disponibilidad de otro y habría metido red y despliegue en la primera
  versión.
- **Reutilizar el motor de cláusulas sin tocarlo.** El servicio compone el texto y llama a
  `review_clause` tal cual. Razón: las reglas de S3 en Consultor (solo artículos recuperados, citas
  validadas, un reintento acotado, abstención antes de generar) ya estaban probadas y son la parte
  delicada. Duplicarlas habría creado dos definiciones de "cita válida", que es exactamente el error
  que CL-06 evitó al compartir el parser de citas. *Alternativa descartada:* un prompt específico de
  Radar con su propio esquema de salida; habría duplicado validación y coste de mantenimiento sin
  comprar nada.
- **Una sola pasada de generación.** Los campos se componen en un texto con secciones etiquetadas por
  origen. Razón: el modelo necesita ver la ficha junta porque hay reglas que solo se violan en
  combinación (el tope del 50% del art. 192 se entiende mirando el conjunto de penalidades), y una
  llamada por campo habría multiplicado el coste sin mejorar el juicio.
- **Origen resuelto en código, no en el prompt.** `origin_field_of_quote` busca la cita en la sección
  compuesta. Razón: pedirle al modelo que declare el campo de origen habría añadido un dato que el
  código puede derivar con certeza; y si la cita no aparece en ninguna sección, se devuelve `None`
  antes que adivinar.
- **Fallo cerrado en la entrada.** `ficha_sin_datos` y `ficha_demasiado_larga` son 422 tipados, con
  el mismo sobre que el resto de la API, y se validan **antes** de recuperar o generar. Razón: una
  petición inválida no debe gastar cuota ni devolver un 500 previsible.

## 3. Errores detectados

- **El contrato de Radar no estaba donde se esperaba (propio).** La primera tentación fue suponer
  tablas `penalidades`/`garantias`. No existen: todo vive en el JSONB `datos` de la tabla `ficha`, y
  los valores son **frases literales**, sin cifras normalizadas. Suponerlo habría producido un
  contrato inventado. La verificación costó una exploración dirigida y ahorró el rediseño completo.
- **El límite de palabras del revisor (propio, en el worker).** El primer test del límite falló
  porque las cabeceras de sección que añade el compositor **también son palabras**: el texto
  compuesto supera el tope antes de lo que el test suponía. Se corrigió derivando el límite del
  importado menos el sobre de composición, en vez de fijar un número.
- **Aviso inválido con corchete (propio).** El primer test de cita inventada falló porque
  `avisos_invalidos` guarda la etiqueta cruda `[art. 999]`, no `art. 999`. El RED destapó un detalle
  real del contrato existente; se ajustó la aserción, no el código.
- **`mem_save` rechazado en los subagentes (harness).** Los dos workers reportaron que Engram rechazó
  su guardado porque la sesión pertenece al proyecto `consultor-lcsp` y ellos pasaron
  `Consultor-LCSP`. No afecta al trabajo, pero significa que las observaciones de los subagentes no
  se persisten: el handoff del padre es el único registro.

## 4. Cómo se iteró hasta una solución válida

1. Lectura literal de S7 en el BRIEF (una línea) y verificación del contrato real de Radar: modelo
   (`PliegoFicha`), endpoint (`GET /licitaciones/{id}/ficha`), forma de los valores (texto verbatim),
   ausencia de auth y topología de compose.
2. Dos decisiones de producto a Albert, porque una línea de spec no las fija: dirección (push) y
   alcance (solo penalidades + garantía definitiva). Registradas como L2 del feature document.
3. RED de dominio y servicio: `ModuleNotFoundError: app.domain.radar_ficha` — 2 errores de colección.
4. GREEN: 12 tests de dominio + 4 de servicio; suite completa 223 pasada.
5. Integración: 5 tests con el corpus real y `FakeLLMClient`. Como la implementación ya existía, el
   RED se demostró por **mutación**: romper el mapeo de origen, vaciar `avisos_invalidos`, quitar el
   umbral, quitar cada 422 → cada mutación hizo fallar su test, revertida byte a byte.
6. Prueba real de extremo a extremo (no fake) con la ficha del expediente 4586/2026 tal como la
   extrae Radar: recuperó arts. 192, 193, 110, 107, 194, 109; devolvió
   `posible_incumplimiento` sobre las penalidades coercitivas del 10% **por falta del tope del 50%
   del art. 192**, una `ambiguedad` sobre el "y/o", y dos `ok` (penalidad diaria conforme al art. 193
   y garantía del 5% conforme al art. 107). Cero avisos inválidos. Corpus intacto: 580 chunks.

## 5. Conclusión: qué se aprende de esto

**Integrar dos sistemas empieza por leer el contrato, no por diseñar el adaptador.** La forma real de
los datos de Radar —texto verbatim dentro de un JSONB, sin cifras normalizadas— determinó todo el
diseño: si hubiera asumido tablas y números, habría construido un contrato que no existe y lo habría
descubierto al final. La regla transferible: el primer entregable de una integración es la descripción
verificada de la superficie del otro lado, con rutas y nombres de campos citados.

**Cuando ya tenés un motor probado, integrar es componer, no reescribir.** El valor de S7 no vino de
un prompt nuevo: vino de meter datos de otro producto en el mismo camino que ya validaba citas y
abstenía. Cada regla duplicada es una regla que puede divergir; cada reutilización es una garantía que
se hereda gratis.

**La prueba que convence es la que trae un hallazgo.** Los tests con fake demuestran que el cableado
está bien; la llamada real sobre la ficha 4586/2026 demostró que el sistema sirve: encontró que el
pliego fija penalidades coercitivas del 10% sin el límite del 50% del art. 192. Un test verde dice que
no rompiste nada; una salida útil sobre datos reales dice que construiste algo.
