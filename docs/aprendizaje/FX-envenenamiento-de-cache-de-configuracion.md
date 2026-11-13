# FX — El envenenamiento de la caché de configuración

Fecha: 2026-11-13 · Commit: `4f18c7b` · Líneas: 63 (2 ficheros de test)

## 1. Qué se ha construido

La corrección del defecto que hacía que **las suites de integración corrieran contra la base de
trabajo en vez de contra `lcsp_test`**, destruyendo el corpus ingerido (580 chunks con embeddings
pagados, borrados dos veces: una antes de la base dedicada y otra con los guardias ya puestos).
El conftest ahora invalida la caché de `get_settings()` después de reasignar `DATABASE_URL`, y
además lee la URL resuelta y aborta la sesión si no es la de test: un regression futuro falla
ruidoso en vez de borrar datos en silencio.

## 2. Cómo se ha hecho y por qué así

- **`get_settings.cache_clear()` tras la reasignación.** La causa raíz: el conftest llama a
  `get_settings()` para sus guardias, `get_settings` está decorado con `@lru_cache`, y la instancia
  cacheada se construyó con el `DATABASE_URL` de trabajo. Cambiar `os.environ` después no la toca:
  todo engine construido luego (perezosamente, en el primer uso) leyó `lcsp`. Limpiar la caché es el
  cambio mínimo que repara la secuencia real sin tocar código de aplicación.
  *Alternativa descartada:* hacer que `app/db/session.py` reciba la URL explícitamente o no usar
  caché global. Descartada porque el problema no es de la aplicación sino de la secuencia de test
  (leer settings, luego mutar entorno), y tocar el runtime de producción por un defecto de las
  suites habría extendido el cambio sin necesidad.
- **Verificación fail-closed en el conftest.** Después de limpiar la caché se relee
  `get_settings().database_url` y si no coincide con la URL de test la sesión aborta
  (`pytest.exit(..., returncode=2)`). Es la política del repo: un fallo ruidoso y explicado es más
  barato que un éxito que borra datos. *Alternativa descartada:* confiar solo en el test de
  regresión — un test puede quedarse viejo; el check en el arranque de la suite protege aunque el
  test desaparezca.
- **El test de regresión ejecuta el conftest real.** No replica la secuencia en un test propio
  (podría divergir del código real): expulsa `tests.integration.conftest` de `sys.modules`, limpia
  la caché, importa el módulo de verdad bajo entorno controlado y afirma que `get_settings()`
  termina apuntando a `/lcsp_test`. Así el invariant testeado es el comportamiento del módulo tal
  como pytest lo ejecuta.
- **Mecanismo del test:** la primera idea fue `importlib.reload`, pero una segunda ejecución del
  cuerpo del módulo reasigna `DATABASE_URL` mientras `DATABASE_URL` sigue valiendo la URL de test
  del intento anterior, y el guardia de "working ≠ test" se dispara solo. La evicción de
  `sys.modules` + import fresco ejecuta el módulo exactamente como en una sesión real. Ajuste
  documentado, no cambio de especificación.

## 3. Errores detectados

- **El bug padrino (nuestro, de la entrega de PR #8/#9):** el guardia validaba la variable pero
  nadie verificó que la reasignación llegara a los engines. El síntoma fue el corpus borrado dos
  veces; la evidencia que lo delató fue `pg_stat_user_tables`: `lcsp` con contadores de borrado
  (627 en `chunk`) e inserciones de fixtures (47) mientras `lcsp_test` tenía **actividad cero**.
  Los tests del guardia (`pytest.exit` en caso de variable ausente o igual a la de trabajo) pasaban
  porque solo cubrían los guardias, no lo que venía después.
- **Por qué el CI no lo vio nunca:** en CI truncar la base del servicio es inofensivo — cada test
  siembra sus propios fixtures. Es un defecto que solo duele donde hay datos reales, y por eso el
  CI verde dio falsa confianza. Segunda vez que un ambiente de test "funciona" oculta el defecto.
- **Diagnóstico de import equivocado:** la reconstrucción con `importlib.reload` habría sido un
  test que falla por el motivo equivocado (el guardia, no la caché). detectado antes de commitear.

## 4. Cómo se iteró hasta una solución válida

1. Hallazgo: `select count(*) from chunk` en `lcsp` → 0, tras haber cerrado el día anterior con 580
   verificados y smoke tests andando.
2. Gobio forense: "Skipping initialization" y recovery automático en los logs del contenedor
   descartaron pérdida del volumen; `alembic` en 0004 en ambas bases descartó recreación. Todo
   apuntaba a un DELETE/TRUNCATE posterior.
3. `pg_stat_user_tables`: toda la actividad del día estaba en `lcsp` (chunk 47/627, fuente 24/25,
   feedback 9/9); `lcsp_test` en ceros. Conclusión: las suites de esa mañana corrieron contra la
   base de trabajo a pesar del guardia.
4. Reproducción en vivo sin escribir en la base: `get_settings()` → cambiar
   `os.environ["DATABASE_URL"]` → segunda llamada devuelve la URL vieja. Causa: `@lru_cache`.
5. RED observado: el test contra el conftest real falló con
   `AssertionError: integration conftest left get_settings() pointing away from the test database`.
6. Fix de 2 líneas de lógica (`cache_clear` + fail-closed) y GREEN: 202 unitarios, 34 de
   integración, ruff, `ruff format --check` y `mypy --strict` en verde.
7. Verificación a escala del orquestador: suite completa contra `lcsp_test` con los contadores de
   `lcsp` congelados (47/627 intactos) y `lcsp_test` con la actividad de la corrida (94/94,
   18/18, 48/48). El arreglo queda demostrado con datos, no con la lectura del código.

## 5. Conclusión: qué se aprende de esto

**Un guardia no es una ruta.** Validar la entrada y usarla después son dos momentos distintos, y
entre ellos puede colarse un singleton cacheado que congele el supuesto que el guardia acaba de
proteger. Cuando un check importante tiene consecuencias destructivas, el momento justo después
del check merece su propia verificación de que el mundo real (aquí, la URL que construirá el
engine) refleja la decisión tomada.

**La memorización convierte supuestos en invariantes invisibles.** `lru_cache` sobre una función
de configuración es idiomático y correcto en producción; en un test que muta el entorno después de
leerla, la misma caché es el bug. El patrón transferible: si un fixture reordena el entorno, debe
también declarar cómo invalida todo lo que pudiera haberse cacheado antes — y una lectura de
verificación inmediata (fail-closed) conviene que viva junto a la mutación, no en un test lejano.

**El CI no puede ser el único test de un defecto que solo duele con datos reales.** Este bug pasó
todos los gates y dos revisiones nativas porque en CI era inocuo. Lo que lo delató fue un conteo
de filas cruzado con estadísticas de tabla, no una suite. Donde una pérdida es cara y pagada, el
entorno de test merece una sonda propia: saber qué base tocó la última corrida tiene que poder
contestarse con una consulta, no con fe.
