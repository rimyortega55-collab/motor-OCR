# Prioridad de las funciones avanzadas

Orden de construcción para las cinco funciones de
`06-funciones-avanzadas-interfaz.md`, contrastado contra el código el 2026-08-25
con el motor en 92 pruebas en verde.

Versión publicada, más cómoda de leer:
https://claude.ai/code/artifact/2b3c84bf-651f-48c8-95d1-f73fdac24f4e

## El orden

| # | Función | Estado | Por qué ahí |
|---|---|---|---|
| 1 | Edición manual de bloques | casi lista | Cierra el loop de calidad y **baja** el costo variable |
| 2 | Búsqueda/navegación (Graphify) | bloqueada | Es la razón de ser declarada del proyecto; el prerrequisito es barato |
| 3 | Integraciones | parcial | Obsidian sale casi gratis con lo que ya se exporta |
| 4 | Traducciones | todo por hacer | La más cara y la única que aumenta el ingreso por uso |
| 5 | Colaboración | esperar demanda | Ya no es la más cara, pero es la que peor encaja con el cobro por uso |

## Dos supuestos del documento que no se sostienen

**El módulo de traducción no existe.** El documento lo da por «ya definido
(NLLB-200 / Opus-MT)» y estima esfuerzo *Medio*. En el código sólo están las
formas de datos: `Traduccion`, `MotorTraduccion` y `Documento.idiomas_traduccion`.
Ninguna línea ejecutable. El esfuerzo real es bastante mayor.

**El grafo de Graphify saldría sin aristas.** `metadata/exportador_graphify.py`
son 21 líneas que nadie llama, y arma los edges desde `Bloque.relaciones`, que
ningún módulo puebla. Los nodos saldrían bien y el grafo quedaría desconectado
— para un producto cuya descripción en `pyproject.toml` es «salida indexable por
Graphify», es el hueco más serio del inventario.

## Qué hay y qué falta de cada una

### 1. Edición manual de bloques

- **Hecho:** el visor de revisión, la decisión escribe `contenido_final` en el
  bloque, y la exportación lo aplica en los tres formatos.
- **Hecho:** la señal que pide el documento —«si muchos usuarios corrigen el
  mismo tipo de bloque, ajustar umbrales»— es `GET /umbrales/recomendaciones`,
  que agrupa por `tipo_bloque`.
- **Falta:** versionado. Hoy `contenido_final` pisa y no se conserva el original
  del OCR. El propio documento lo marca como pendiente.
- **Ojo:** pide regenerar el LaTeX «por la plantilla Jinja2 correspondiente».
  **No hay ninguna plantilla Jinja2 en el proyecto**; `jinja2` está declarado
  como dependencia y no se usa. Es construir ese paso, no reutilizarlo.

### 2. Búsqueda y navegación vía Graphify

- **Hecho:** `GET /export?formato=graphify` entrega el JSON de bloques con las
  correcciones humanas aplicadas.
- **Falta:** poblar `Bloque.relaciones`.
- **A favor:** `correction/consistencia_documental.py::_validar_referencias_cruzadas`
  ya detecta las referencias cruzadas; sólo reporta las rotas como
  inconsistencias en vez de guardar también las resueltas como relaciones. Es
  extender código existente.
- **Decidir:** wiki estático (`--wiki`) o consultas en vivo (`--mcp`). El
  estático alcanza para empezar y no suma infraestructura.

### 3. Integraciones

| Destino | Estado real | Veredicto |
|---|---|---|
| Obsidian | `?formato=markdown` ya produce el archivo que un vault consume | Hacerlo ya |
| Overleaf | Empujar el LaTeX a un repo Git por proyecto | Después de la 2 |
| Notion | Su modelo de bloques no representa LaTeX complejo | No hacerlo |

El documento admite que Notion «no traduce bien los símbolos matemáticos». Para
un producto de documentos matemáticos, esa integración entrega una versión
degradada de lo único que se vende.

### 4. Traducciones personalizables

- **Hecho:** sólo las formas de datos.
- **Falta:** el módulo entero, y decidir cuáles de las cuatro dimensiones de
  «personalizable» entran.
- **Clave:** es la única de las cinco que aumenta el consumo de IA. Como se cobra
  por IA, es el multiplicador de ingresos — y también de costo.
- **Empezar por el glosario de términos, no por el idioma.** Que «eigenvalue» se
  traduzca igual en todo el documento es lo que distingue una traducción técnica
  utilizable de una que no lo es, y es la dimensión más barata.

### 5. Colaboración

- **Hecho:** el documento dice que requiere «modelo de usuarios y permisos (no
  existente aún)». Ya existe: usuarios, sesiones, API keys y aislamiento por
  usuario con pruebas.
- **Falta:** permisos por documento, invitaciones y comentarios anclados a
  `bloque_id`.
- **En contra:** el producto cobra por cómputo e IA. Colaborar no consume ni
  cómputo ni IA: suma infraestructura y soporte sin sumar ingreso. Es una función
  de precio por asiento en un producto de precio por uso.

## Tandas

Las cinco en paralelo se estorban. Este reparto respeta las dependencias reales
y pone lo más barato adelante.

| Tanda | Qué entra | Por qué juntas |
|---|---|---|
| 1 | Versionado de la edición · `relaciones` pobladas · export a Obsidian | Extensiones de código que ya existe, independientes entre sí |
| 2 | Graphify navegable (`--wiki`) · Overleaf por Git | Consumen la salida que la tanda 1 dejó completa |
| 3 | Traducción: glosario, después idioma destino | Módulo nuevo entero; merece una tanda sola |
| 4 | Colaboración | Cuando exista un cliente que la pida y un plan que la pague |

El paso por Jinja2 de la función 1 queda fuera de la tanda 1 a propósito: no es
reutilizar una plantilla, es construir el sistema de plantillas. Conviene
decidirlo cuando el formato de salida esté estable.
