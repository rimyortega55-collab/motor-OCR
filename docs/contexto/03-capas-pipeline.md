# Capas del Pipeline — Motor OCR

Pipeline determinista de 5 capas. El LLM se usa exclusivamente en la Capa 5, como último recurso, sobre unidades pequeñas y agrupadas (batching), nunca sobre documentos completos.

---

## Capa 1 — Triage

**Objetivo:** decidir, por página o zona, el origen del contenido, el perfil de contenido aproximado, y el DPI de renderizado — antes de hacer cualquier trabajo costoso.

### Lógica

1. **Detección de origen** (con PyMuPDF): ¿el PDF tiene capa de texto embebida?
   - **Nativo-digital**: se puede inspeccionar el nombre de las fuentes embebidas. Fuentes tipo `CMMI`, `CMSY`, `CMEX`, `MSAM`, `MSBM`, Latin Modern Math u otras fuentes matemáticas OpenType son una señal confiable y gratuita de presencia de notación matemática — sin necesidad de OCR ni LLM.
   - **Escaneado**: no hay esa señal; se requiere un pase visual barato.
2. **Pase visual a baja resolución (~150 DPI)** para páginas escaneadas, usando heurísticas rápidas (no modelos pesados):
   - Densidad de componentes conectados pequeños y aislados → indicio de fórmulas.
   - Líneas rectas en rejilla (detección tipo Hough) → indicio de tabla.
   - Regiones grandes de tono uniforme no textual → indicio de figura/diagrama.
   - Densidad de texto corrido, líneas parejas → texto plano.
3. **Agrupación en zonas**: páginas contiguas con perfil de contenido similar se agrupan (no se decide DPI estrictamente página por página) para simplificar la orquestación de renderizado sin perder el ahorro de cómputo. Ej.: páginas 1–40 (texto narrativo) → zona DPI 200; páginas 41–65 (capítulo denso en fórmulas) → zona DPI 400.
4. **Optimización clave**: una página nativo-digital sin fórmulas no necesita pasar por OCR — se extrae el texto directo del PDF (100% preciso, costo de cómputo mínimo).

### Contrato de salida

```
TriageResult (por página):
├── origen: "nativo_digital" | "escaneado"
├── perfil_contenido: { texto_ratio, formula_ratio, tabla_ratio, figura_ratio }
├── dpi_objetivo: int
├── requiere_ocr: bool
└── fuentes_detectadas: [...]   # solo si nativo_digital
```

Las zonas resultantes (agrupaciones de páginas) también son metadata útil para Graphify más adelante, ya que suelen representar agrupaciones temáticas naturales del documento.

---

## Capa 2 — Segmentación de Layout

**Objetivo:** dividir cada página/zona en bloques individuales con tipo, posición y orden de lectura correctos.

### Lógica

1. **Bifurcación según origen (definido en Capa 1):**
   - **Nativo-digital**: los bloques se derivan directamente de la estructura del PDF (agrupando por fuente + posición + espaciado vertical) — más preciso y más barato que segmentación visual.
   - **Escaneado**: se usa docTR para layout detection (detecta regiones: texto, título, tabla, figura, fórmula).

2. **Taxonomía extendida de bloques** — va más allá de "párrafo/fórmula/tabla/figura" para capturar la estructura semántica que necesita Graphify:

```
encabezado          # título, sección, subsección
parrafo             # texto corrido
formula_inline      # ecuación dentro de una línea de texto
formula_display     # ecuación en línea propia, centrada, numerada
tabla
figura
caption             # asociado a tabla/figura
teorema / lema / proposicion / definicion / corolario
demostracion        # "Proof." — normalmente termina con ∎
nota_pie
lista
codigo              # pseudocódigo o código real
ruido               # encabezado/pie de página, número de página
```

   Los tipos semánticos (teorema/lema/definición/demostración) se detectan con reglas y regex sobre patrones tipográficos y textuales reconocibles (negrita + "Teorema 3.2." al inicio, símbolo ∎ al final de una demostración, numeración consistente) — **no requieren LLM**.

3. **Resolución de orden de lectura**: en layouts de una sola columna es trivial (arriba hacia abajo). En layouts de **dos columnas** (común en libros de matemática), se requiere una heurística de agrupación por columnas antes de asignar el índice de orden — de lo contrario el texto sale desordenado y ninguna corrección posterior lo repara bien.

### Contrato de salida

```
Block (por página/zona):
├── id
├── tipo                # de la taxonomía extendida
├── bbox
├── orden_lectura        # ya resuelto el problema de columnas
├── bloque_padre         # ej. caption → apunta a su figura/tabla
├── origen               # "texto_nativo" | "requiere_ocr"
└── confianza_layout
```

---

## Capa 3 — OCR Especializado por Tipo de Bloque

**Objetivo:** aplicar el motor correcto según el tipo de bloque, resolviendo el hecho de que muchos bloques de texto contienen fórmulas inline entrelazadas.

### Lógica

1. **Sub-segmentación dentro del bloque** (para bloques de tipo texto: `parrafo`, `teorema`, `lema`, `demostracion`, `definicion`, `nota_pie`): antes de aplicar OCR, se detectan regiones de fórmula inline dentro del bloque usando señales baratas:
   - Nativo-digital: cambios de fuente matemática dentro de la misma línea (misma señal que en Capa 1).
   - Escaneado: componentes conectados con proporciones/densidad distintas al texto circundante (superíndices, símbolos aislados, fracciones).
   - Resultado: secuencia de micro-segmentos `[texto, formula_inline, texto, ...]`, cada uno enrutado a su engine, luego recompuestos en orden en una sola cadena (LaTeX con `$...$` incrustado).

2. **Enrutamiento por tipo de bloque:**

```
parrafo / teorema / lema / demostracion / definicion / nota_pie:
  → sub-segmentar en [texto, formula_inline]*
  → texto: EasyOCR | formula_inline: pix2tex
  → recomponer en una sola cadena

formula_display:
  → todo el bloque → pix2tex directo (sin sub-segmentar)

tabla:
  → docTR (estructura + celdas)
  → celdas con notación matemática → pix2tex (mismo patrón de sub-segmentación, a nivel de celda)

encabezado / caption / lista / codigo:
  → EasyOCR (con detección de fuente matemática por si aplica)

figura:
  → sin OCR; se preserva como imagen embebida + caption asociado
```

3. **Cálculo de confianza** — combinación de tres señales por micro-segmento:
   - Confianza nativa del engine (score propio de EasyOCR / pix2tex).
   - Validación estructural: ¿el LaTeX resultante compila/parsea sin errores de sintaxis? (parser ligero, no requiere `pdflatex` completo).
   - Consenso entre engines: comparación con Tesseract como fallback barato; si difieren mucho, confianza baja.

   Solo cuando la combinación cae bajo umbral, el **micro-segmento** (no el bloque completo) se marca para escalación en Capa 5.

### Contrato de salida

```
BlockOCRResult (por bloque):
├── id
├── contenido                 # texto/LaTeX recompuesto
├── micro_segmentos: [
│     { tipo, contenido, engine_usado, confianza_engine, confianza_estructural }
│   ]
├── confianza_global
└── requiere_escalacion        # bool
```

---

## Capa 4 — Corrección Post-OCR (sin LLM)

**Objetivo:** exprimir todo el arreglo posible con reglas deterministas antes de considerar cualquier escalación a LLM.

### Lógica

1. **Normalización de LaTeX equivalente:**
   - `\dfrac{}{}` vs `\frac{}{}` → estandarizar.
   - `\left(`/`\right)` vs paréntesis sueltos → aplicar consistentemente cuando el contenido lo amerita (fracciones, matrices).
   - Espaciado redundante (`\,\,\,`) → colapsar.
   - Alias de comandos (`\varnothing` vs `\emptyset`) → estandarizar según guía de estilo interna.

2. **Validación estructural con reparación determinista:**
   - Paréntesis/llaves desbalanceados con desbalance simple → inferir y cerrar automáticamente contando profundidad de anidamiento.
   - `\begin{...}` sin `\end{...}` correspondiente → intentar emparejar por proximidad.
   - Si la reparación falla o el desbalance es ambiguo → se marca para escalar.

3. **Corrección ortográfica determinista, quirúrgica:**
   - Diccionario base del idioma + diccionario técnico-matemático curado.
   - Se corrige solo cuando la palabra no está en ningún diccionario Y existe una corrección de distancia de edición 1 con alta frecuencia en el corpus.

4. **Consistencia estructural a nivel de documento completo** (posible solo porque ya se tiene el documento entero, no bloque por bloque):
   - Numeración de teoremas/lemas consistente (ej. detectar salto de "Teorema 3.2" a "Teorema 3.4" sin 3.3).
   - Referencias cruzadas resolubles (ej. "por el Lema 2.1" sin bloque correspondiente en el documento).
   - Continuidad de fórmulas numeradas.
   - Estas inconsistencias **se resuelven también vía LLM** (decisión de producto), pero como una cola de escalación separada (ver Capa 5) — no se inventan ni se rellenan automáticamente.

### Contrato de salida

```
DocumentPostCorrection:
├── bloques_corregidos: [
│     { id, contenido_normalizado, reparaciones_aplicadas: [...] }
│   ]
├── inconsistencias_detectadas: [
│     { tipo: "numeracion_faltante" | "referencia_rota", detalle, ubicacion }
│   ]
└── bloques_pendientes_escalacion: [ids]
```

---

## Capa 5 — Escalación y Batching a LLM

**Objetivo:** resolver, con el menor costo posible, únicamente lo que las capas 1–4 no pudieron resolver de forma determinista.

### Dos colas separadas (contexto distinto, no se mezclan en el mismo lote)

**Cola 1 — micro-segmentos de baja confianza (origen: Capa 3)**
- Requiere modelo con **visión**: el error suele venir de algo que el engine determinista no pudo interpretar visualmente.
- **Unidad de batching**: por página — todos los micro-segmentos dudosos de una misma página en una sola llamada (no una llamada por segmento).
- **Qué se envía**: recorte de imagen del segmento (no la página completa) + una o dos líneas de contexto textual antes/después + el resultado del engine determinista (para que el LLM corrija, no transcriba desde cero — más barato en tokens de salida).
- **Salida esperada**: JSON estructurado con contenido corregido + confianza propia del LLM.

**Cola 2 — inconsistencias documentales (origen: Capa 4)**
- Es un problema de "qué falta o qué está mal conectado", no de transcripción — no requiere imagen, requiere contexto estructural en texto.
- **Unidad de batching**: todas las inconsistencias del documento en una sola llamada (o pocas, si el documento excede context window razonable).
- **Qué se envía**: índice estructural (teoremas/lemas/ecuaciones detectados) + fragmentos de texto inmediatamente antes/después de cada inconsistencia — no el documento completo.
- **Regla crítica**: si el LLM concluye que falta un bloque, **no genera contenido nuevo**. Marca la zona para reprocesamiento (segunda pasada de Capa 2 más agresiva) o revisión humana. Inventar contenido matemático faltante es inaceptable para la promesa de precisión del producto.

### Control de concurrencia

- Semáforo con límite configurable de llamadas concurrentes al proveedor de LLM (respeta rate limits).
- Cola 1 tiene prioridad sobre Cola 2 en caso de contención de recursos (afecta directamente la fidelidad del contenido, no solo metadata).

### Tracking de costo

Cada llamada a LLM se registra con: tokens de entrada/salida, documento/bloque que la originó, y la razón de escalación. Esto alimenta directamente el modelo de cobro por nivel de trabajo, y con el tiempo permite ajustar los umbrales de confianza de las capas 3 y 4 (si un tipo de bloque escala demasiado seguido, es señal de ajustar el engine determinista, no el umbral).

### Contrato de salida

```
EscalationResult:
├── cola_origen              # "micro_segmento" | "inconsistencia_documental"
├── contenido_final
├── confianza_llm
├── requiere_revision_humana   # true si confianza_llm también es baja
├── costo: { tokens_entrada, tokens_salida, modelo_usado }
└── razon_escalacion
```

---

## Flujo completo, extremo a extremo

```
PDF crudo
  → Capa 1 (Triage): origen, perfil, DPI por zona
  → Renderizado a imagen según DPI de zona
  → Capa 2 (Segmentación): bloques con taxonomía extendida + orden de lectura
  → Capa 3 (OCR especializado): contenido por bloque, con sub-segmentación de fórmulas inline
  → Capa 4 (Corrección determinista): normalización, reparación estructural, consistencia documental
  → Capa 5 (Escalación LLM, solo lo no resuelto): dos colas batcheadas
  → Salida final: bloques con contenido, confianza y relaciones,
     listos para el esquema de metadata (ver 05-esquema-metadata-bloque-ocr.md)
```
