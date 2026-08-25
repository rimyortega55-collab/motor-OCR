# Funciones Avanzadas de Interfaz

Propuesta de funciones sobre el motor OCR (foco de salida: LaTeX y Markdown como formatos principales; `.ipynb` y otros quedan como secundarios). Todas se apoyan en el esquema de metadata a nivel de bloque ya definido (`05-esquema-metadata-bloque-ocr.md`) — la granularidad de bloque (`id`, `confianza`, `relaciones`, `traduccion`) es la base común de las cinco funciones, no requieren rediseño del modelo de datos.

---

## 1. Edición / corrección manual de bloques

Permite al usuario revisar y ajustar el resultado a nivel de bloque individual, no de documento completo.

**Consideraciones de diseño:**
- Al editar manualmente un bloque, se marca `verificado_por_usuario: true` en su metadata y deja de ser candidato a revisión automática.
- Esta señal es útil más allá de la UI: si muchos usuarios corrigen el mismo tipo de bloque de forma consistente, es indicio de que los umbrales de confianza de Capa 3/4 del motor OCR necesitan ajuste.
- Una edición en un bloque con fórmula inline (ej. `teorema`) debe volver a pasar por la plantilla Jinja2 correspondiente para regenerar el LaTeX/Markdown final — no se guarda como texto suelto desconectado del pipeline de renderizado.

**Pendiente de definir:** flujo de versionado (¿se conserva el resultado original del OCR junto al editado, para auditoría?).

---

## 2. Búsqueda y navegación vía Graphify

Navegación del documento convertido apoyada en el grafo de conocimiento generado por Graphify.

**Consideraciones de diseño:**
- El modo `--wiki` de Graphify genera artículos navegables por comunidad/nodo-god con un `index.md` como punto de entrada — esto puede reutilizarse directamente como base de la interfaz de exploración, en vez de construir un buscador desde cero.
- El modo `--mcp` permite que la búsqueda/navegación se sirva mediante consultas en tiempo real al grafo, útil si se quiere una experiencia más interactiva que archivos estáticos de wiki.

**Pendiente de definir:** si la navegación se sirve como contenido estático (wiki generado) o como consultas en vivo (MCP).

---

## 3. Integraciones (Overleaf, Notion, Obsidian)

Exportación del contenido convertido hacia herramientas externas.

| Destino | Vía | Dificultad estimada |
|---|---|---|
| **Obsidian** | Graphify ya exporta directamente a vault de Obsidian (carpeta `obsidian/` en su output) | Baja — integración prácticamente resuelta |
| **Overleaf** | Sincronización vía Git (Overleaf soporta repos Git) — exportar LaTeX + repo por proyecto de usuario | Media |
| **Notion** | API de bloques propia de Notion — su modelo de bloques es limitado para LaTeX complejo, no todos los símbolos matemáticos se traducen bien a su editor | Alta — la integración más laboriosa de las tres |

---

## 4. Colaboración (compartir / comentar documentos convertidos)

Función con mayor requerimiento de infraestructura nueva del grupo.

**Consideraciones de diseño:**
- Requiere modelo de usuarios y permisos (no existente aún en el diseño actual del motor OCR).
- Los comentarios se anclan a `bloque_id` — la granularidad de bloque ya definida lo permite sin cambios al esquema de metadata.
- Decisiones de producto pendientes:
  - ¿Comentarios en tiempo real o asíncronos?
  - ¿Quién puede editar vs. solo comentar (roles y permisos)?

---

## 5. Traducciones personalizables

Se apoya en el módulo de traducción ya definido (NLLB-200 / Opus-MT, con LLM como respaldo para casos semánticos límite).

**"Personalizable" puede implicar varias dimensiones — pendiente de decidir cuáles incluir:**
- Selección de idioma destino por documento o por usuario.
- Glosario de términos técnicos consistente (ej. que "eigenvalue" se traduzca siempre igual en todo el documento).
- Tono/registro configurable (más formal/académico vs. más accesible).
- Traducción selectiva por bloque (traducir solo ciertas secciones, no el documento completo).

---

## Resumen de dependencias técnicas

| Función | Depende de | Nivel de esfuerzo relativo |
|---|---|---|
| Edición/corrección manual | Esquema de metadata de bloque, plantillas Jinja2 | Bajo |
| Búsqueda/navegación (Graphify) | Graphify (`--wiki` / `--mcp`) | Bajo-Medio (reutiliza output existente) |
| Integraciones | Obsidian: bajo · Overleaf: medio · Notion: alto | Variable |
| Colaboración | Modelo de usuarios/permisos (nuevo) | Alto |
| Traducciones personalizables | Módulo de traducción existente | Medio (según cuántas dimensiones de personalización se incluyan) |

## Próximos pasos

Definir orden de prioridad de implementación entre las cinco funciones, y profundizar el diseño de la primera que se seleccione.
