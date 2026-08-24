# Esquema de Metadata a Nivel de Bloque — Motor OCR

Especificación de salida del pipeline OCR (5 capas), diseñada para ser indexable por Graphify. Este documento es la referencia para la implementación en Claude Code.

---

## 1. Objeto de Documento (nivel raíz)

```json
{
  "documento_id": "uuid",
  "titulo": "string",
  "origen": "nativo_digital | escaneado | mixto",
  "idioma_original": "es | en | ...",
  "idiomas_traduccion": ["en", "..."],
  "total_paginas": "int",
  "zonas_dpi": [
    { "paginas": [1, 40], "dpi": 200, "perfil_dominante": "texto" },
    { "paginas": [41, 65], "dpi": 400, "perfil_dominante": "formula" }
  ],
  "version_pipeline": "semver",
  "fecha_procesamiento": "ISO 8601",
  "costo_total": { "tokens_entrada": "int", "tokens_salida": "int", "modelo_usado": ["..."] },
  "indice_estructural": {
    "capitulos": [ { "numero": "string", "titulo": "string", "bloque_id_inicio": "uuid" } ],
    "teoremas": [ { "numero": "3.2", "bloque_id": "uuid" } ],
    "lemas": [ "..." ],
    "definiciones": [ "..." ],
    "ecuaciones_numeradas": [ { "numero": "(3.1)", "bloque_id": "uuid" } ]
  },
  "inconsistencias_no_resueltas": [
    { "tipo": "numeracion_faltante | referencia_rota", "detalle": "string", "ubicacion_pagina": "int" }
  ]
}
```

`indice_estructural` es la pieza que le da a Graphify un mapa de navegación del documento sin tener que recorrer todos los bloques — se construye como subproducto de la capa 4 (validación de consistencia documental).

---

## 2. Objeto de Bloque (nodo principal del grafo)

```json
{
  "id": "uuid",
  "documento_id": "uuid",
  "pagina": "int",
  "tipo": "encabezado | parrafo | formula_inline | formula_display | tabla | figura | caption | teorema | lema | proposicion | definicion | corolario | demostracion | nota_pie | lista | codigo | ruido",

  "identificador_semantico": {
    "numero": "3.2",
    "capitulo": "3",
    "seccion": "3.1"
  },

  "layout": {
    "bbox": [0, 0, 0, 0],
    "orden_lectura": "int",
    "bloque_padre_id": "uuid | null",
    "confianza_layout": "float"
  },

  "origen_contenido": "texto_nativo | requiere_ocr",

  "contenido": {
    "texto_plano": "string",
    "latex": "string",
    "markdown": "string",
    "ipynb_cell": { "cell_type": "markdown | code", "source": "string" }
  },

  "ocr": {
    "micro_segmentos": [
      {
        "tipo": "texto | formula_inline",
        "contenido": "string",
        "engine_usado": "easyocr | pix2tex | doctr | tesseract",
        "confianza_engine": "float",
        "confianza_estructural": "float"
      }
    ],
    "confianza_global": "float"
  },

  "correccion": {
    "reparaciones_aplicadas": ["normalizacion_latex", "balanceo_llaves", "..."],
    "diccionario_usado": "general | tecnico_matematico"
  },

  "escalacion": {
    "requirio_escalacion": "bool",
    "cola_origen": "micro_segmento | inconsistencia_documental | null",
    "confianza_llm": "float | null",
    "requiere_revision_humana": "bool",
    "razon_escalacion": "string | null",
    "costo": { "tokens_entrada": "int", "tokens_salida": "int" }
  },

  "traduccion": {
    "idioma": "en",
    "contenido": "string",
    "motor": "nllb-200 | opus-mt | llm",
    "confianza": "float"
  },

  "relaciones": {
    "salientes": [
      { "tipo": "PROVES", "objetivo_id": "uuid" },
      { "tipo": "USES_DEFINITION", "objetivo_id": "uuid" },
      { "tipo": "REFERENCES", "objetivo_id": "uuid | null", "referencia_texto": "Lema 2.1" },
      { "tipo": "CAPTION_OF", "objetivo_id": "uuid" },
      { "tipo": "PART_OF", "objetivo_id": "uuid" },
      { "tipo": "CONTINUES", "objetivo_id": "uuid" }
    ],
    "entrantes": [
      { "tipo": "PROVES", "origen_id": "uuid" }
    ]
  },

  "provenance": {
    "creado_por_capa": "2",
    "modificado_por_capas": ["3", "4"],
    "timestamp": "ISO 8601"
  }
}
```

---

## 3. Tipos de relación (edges) — el catálogo que usa Graphify

| Tipo | De → A | Se resuelve en | Ejemplo |
|---|---|---|---|
| `PROVES` | demostración → teorema/lema | Capa 2 (por proximidad + numeración) | Demostración 3.2 → Teorema 3.2 |
| `USES_DEFINITION` | cualquier bloque → definición | Capa 4 (regex sobre texto) | "por la Definición 1.4" |
| `REFERENCES` | cualquier bloque → cualquier bloque | Capa 4 | "ver Lema 2.1" |
| `CAPTION_OF` | caption → figura/tabla | Capa 2 (por adyacencia) | — |
| `PART_OF` | bloque → sección/capítulo | Capa 2 | Teorema 3.2 → Sección 3.1 |
| `CONTINUES` | bloque → bloque | Capa 2 (bloque partido por salto de página) | — |

Cuando `REFERENCES` no puede resolver `objetivo_id` (referencia rota), el edge se guarda igual con `objetivo_id: null` y `referencia_texto` con el texto original — esto le da a Graphify información explícita sobre huecos en el grafo, en vez de simplemente omitir la relación.

---

## 4. Principios de diseño para Graphify

1. **Cada bloque es un nodo candidato**, no solo texto. Los tipos semánticos (`teorema`, `demostracion`, `definicion`) son los nodos de mayor valor para consultas de agentes — permiten recuperar "todas las demostraciones que usan el Lema 2.1" sin tener que buscar en texto libre.
2. **Las relaciones se resuelven en el pipeline, no en Graphify.** Graphify indexa lo que ya viene resuelto; no debe tener que re-parsear texto para inferir que una demostración prueba un teorema.
3. **La confianza viaja con el contenido.** Un agente que consuma el grafo debe poder decidir si confía en un bloque según `ocr.confianza_global` / `escalacion.confianza_llm`, no asumir que todo el contenido tiene la misma fiabilidad.
4. **Multi-formato desde el mismo nodo.** `contenido.latex`, `contenido.markdown` y `contenido.ipynb_cell` se generan del mismo bloque canónico — evita mantener tres pipelines de conversión separados.
