# Datos de la LCSP

Esta carpeta guarda el texto consolidado de la **Ley 9/2017, de 8 de noviembre, de Contratos
del Sector Público** (identificador BOE `BOE-A-2017-12902`). El contenido **no se versiona**:
se descarga una vez por máquina con estos comandos.

## Texto consolidado en XML (entrada del parser)

```bash
mkdir -p data/lcsp
curl -L -H 'Accept: application/xml' \
  https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-2017-12902/texto \
  -o data/lcsp/lcsp-consolidada.xml
```

- Sin la cabecera `Accept: application/xml` el BOE responde `400` ("No soportado ningún mime
  type de la cabecera Accept").
- Tamaño aproximado: 1,9 MB.
- **Codificación:** verificado byte a byte, el fichero es **UTF-8 válido** (declara `utf-8` y
  lo cumple). Ojo con el diagnóstico: si la consola muestra `Secci?n`, es el terminal, no el
  dato. El parser decodifica `utf-8` y cae a `latin-1` solo como red de seguridad por si el
  BOE cambia el export.
- Estructura relevante: `<response><data><texto>` y dentro `<bloque>` con
  `tipo="nota_inicial" | "preambulo" | "encabezado" | "precepto" | "firma"`. Cada `precepto`
  lleva `id="a107"` (ancla del BOE) y `titulo="Artículo 107"`; los `encabezado` son
  TÍTULO/CAPÍTULO/Sección. La fecha de la versión consolidada está en
  `<version fecha_vigencia="...">`. Los `id` **no** son correlativos (`Artículo 107` es
  `a1-19`), así que el ancla se toma del `id` del bloque, nunca construida a mano.

## PDF consolidado (solo referencia humana)

```bash
curl -L https://www.boe.es/boe/dias/2017/11/09/pdfs/BOE-A-2017-12902.pdf \
  -o data/lcsp/BOE-A-2017-12902-consolidado.pdf
```

El PDF sirve para contrastar a mano, **no** como entrada del parser: aplana la jerarquía
(libro, título, capítulo, sección, artículo, apartado) y pierde las anclas.

## Verificación con el fichero real

El test que valida contra el XML de verdad vive en `backend/tests/data/` y se ejecuta
explícitamente, porque CI no descarga la ley:

```bash
cd backend && uv run pytest tests/data
```
