# CL-02 · Parser de la LCSP y modelo `chunk`

## 1. Qué se ha construido

La pieza que convierte el XML consolidado de la Ley 9/2017 en el material de trabajo del
sistema. Dos capas:

- **Parser puro** en `app.domain.lcsp_parser` (solo stdlib, cero dependencias): lee los
  `<bloque>` del BOE y produce objetos `LcspChunk` con número de artículo, título, ruta
  jerárquica (libro → título → capítulo → sección → artículo), apartado si aplica, URL con
  ancla al BOE y fecha de la versión consolidada. Un chunk por artículo; solo si el
  artículo supera los ~1.500 tokens se corta por apartados, sin partir ninguno.
- **Modelo de datos** en `app.db.models`: tablas `Fuente` y `Chunk` con migraciones `0002`
  y `0003`, columna `tsv` de tipo `tsvector` (generada, con índice GIN), `vector(4096)` de
  pgvector y la clave única de expresión `(fuente_id, articulo, coalesce(apartado,''))`.

El test de datos contra el XML real validó el resultado: 580 chunks desde los 428
preceptos de la ley, 180 con apartado, 0 duplicados `(articulo, apartado)`, art. 107 con
ancla `#a1-19` y fecha de versión `2018-03-09`.

## 2. Cómo se ha hecho y por qué así

### Decisión: parser puro, stdlib únicamente
- **Qué se eligió.** El parser vive en `domain` como función pura sobre strings, sin
  importar FastAPI, SQLAlchemy ni librerías externas de parseo.
- **Por qué.** AGENTS.md lo exige (`domain` no importa infraestructura), y el motivo de
  fondo es que así el test del parser corre sin base, sin red y sin la ley: un fixture de
  3 artículos basta para AC-02. La alternativa (usar BeautifulSoup o similares) no aporta
  nada: el XML del BOE es regular y predecible; `xml.etree` alcanza y evita una
  dependencia que habría que justificar.

### Decisión: la unidad de recuperación es el artículo
- **Qué se eligió.** Un chunk = un artículo; corte por apartados solo por tamaño.
- **Por qué.** Las citas del BRIEF son `[art. X]` / `[art. X.Y]`: el usuario audita por
  artículo y apartado, así que recuperar y validar en esa misma unidad hace la trazabilidad
  natural. Partir por tamaño fijo (chunks de 300 tokens, p. ej.) habría partido el sentido
  jurídico de un apartado y complicado la cita con chunk sin significado.

### Decisión: el `tsv` usa una configuración `spanish_unaccent`
- **Qué se eligió.** Migración `0003` instala la extensión `unaccent` y crea la
  configuración de búsqueda `spanish_unaccent` (`COPY = spanish` con mapeo
  `unaccent, spanish_stem`); la columna generada `tsv` se calcula con ella.
- **Por qué.** El descubrimiento está en la sección de errores: sin quitar tildes antes de
  stematizar, una pregunta sin tildes devolvía cero resultados. La alternativa (normalizar
  en Python al indexar y al consultar) habría duplicado la lógica y perdido la
  integración con el FTS de Postgres.

### Decisión: identidad sintética para disposiciones
- **Qué se eligió.** Las disposiciones adicionales, transitorias, derogatorias y finales
  reciben identidad `DA1…DA58`, `DT1-6`, `DD1`, `DF1-16` por orden documental, con el
  ordinal completo en `titulo`.
- **Por qué.** El BOE no las numera como estructura propia separable, y el AC-04 solo
  exige recuperar por número de artículo. Se aceptó la limitación explícitamente: en la
  práctica la pregunta "¿qué dice la disposición adicional vigésima tercera?" se resuelve
  por contenido, no por número.

## 3. Errores detectados

### El diagnóstico de codificación estaba equivocado (y era un artefacto de la consola)
- **Cómo se detectó.** El primer contacto con el XML mostraba `Secci?n`: parecía texto
  ISO-8859-1 mal decodificado.
- **Causa.** El fichero es UTF-8 válido, verificado byte a byte tras la duda: 0 bytes
  `0xF3` y 16.693 secuencias de `ó` correctas. Lo que fallaba era el terminal, no el dato.
- **Qué se hizo.** Se corrigió `data/lcsp/README.md` y el docstring del parser; el fallback
  a latin-1 quedó solo como red de seguridad por si el BOE cambia el export. La corrección
  importa más de lo que parece: haber "arreglado" la codificación habría introducido un
  bug real para resolver un síntoma imaginario.

### Los anclas del BOE no son correlativos
- **Cómo se detectó.** Al revisar el art. 107: su `id` es `a1-19`, no `a107`.
- **Causa.** Los `id` de los bloques siguen una numeración interna del documento, no el
  número del artículo.
- **Qué se hizo.** El ancla se toma del `id` del bloque, nunca se construye desde el
  número. Un ancla inventada habría generado enlaces que apuntan a cualquier otra cosa.

### El stemmatizador "español" de Postgres no tolera tildes de forma simétrica
- **Cómo se detectó.** RED de integración propio (`assert 0 == 1` contra la configuración
  inexistente primero, y después la consulta sin tildes contra texto acentuado).
- **Causa.** Con la configuración `spanish` pura, `garantía` stematiza a `garant` pero
  `garantia` stematiza a `garanti`: dos tokens diferentes en el índice. Una pregunta sin
  tildes ("que garantia pide la ley") no encontraba nada aunque la ley dijera `garantía`.
- **Qué se hizo.** `spanish_unaccent` (descrito arriba), fijado con 2 tests de
  integración: que la configuración esté instalada y que una consulta sin tildes encuentre
  texto acentuado.

## 4. Cómo se iteró hasta una solución válida

El RED del worker quedó anotado: `ModuleNotFoundError: app.domain.lcsp_parser` y
`ImportError: app.db.models`. El GREEN cerró con 16 unitarios, 3 de integración y 1 de
datos. La verificación del orquestador (no delegada) añadió la escala real: migraciones
aplicadas contra Postgres 18 con `upgrade head` + `downgrade 0002` + `upgrade head`
limpios, `\d chunk` confirmando el `tsv` generado, GIN y la clave única, y una ingesta
completa de prueba en la base real con las 580 filas y su duplicado rechazado por la clave
única (que es exactamente el mecanismo que CL-03 usaría para demostrar la idempotencia).

La iteración específica del stemmatizador vale como ejemplo del ciclo completo: RED con la
consulta sin tildes devolviendo 0 filas → diagnóstico en `psql` comparando
`to_tsvector('spanish', ...)` con y sin tilde → decisión de arreglarlo en Postgres (donde
vive el problema) y no en el código de aplicación → migración `0003` → GREEN con los 2
nuevos tests de integración.

## 5. Conclusión: qué se aprende de esto

Cuando un dato externo se comporta raro, la primera pregunta es si el síntoma está en el
dato o en el camino que recorre hasta tus ojos. La consola que muestra `Secci?n` dice más
de sí misma que del fichero; verificar el dato byte a byte costó minutos y evitó
construir una solución (re-codificar a mano) alrededor de un problema inexistente. Este
patrón aparecerá siempre con texto en idiomas con tildes, con JSON en logs de Windows y
con cualquier capítulo entre tu fichero y la pantalla.

El segundo aprendizaje es de modelado: las decisiones de granularidad (chunk = artículo,
corte por apartados solo por tamaño) no se toman para el parser sino para todo lo que
viene después. Elegir el artículo como unidad hizo que la validación de citas, el panel
lateral de la UI y la evaluación del recall compartieran la misma definición de "lo que
llega al usuario". En RAG, la unidad de chunk es una decisión de producto con
consecuencias técnicas, no al revés.
