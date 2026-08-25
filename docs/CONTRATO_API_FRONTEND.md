# Contrato de API para el frontend

**Estado: los cinco pasos implementados.** Sesión de navegador (§3), gestión de
API keys (§8), listado con filtros y cursor y procesamiento asíncrono con
progreso por capa (§4), bloques, páginas y decisiones que escriben el bloque
(§1, §5, §6), umbrales por usuario (§7), y consumo con desglose y exportación
(§9, §10). Pruebas en `test_auth_api.py`, `test_trabajos.py`, `test_bloques.py`
y `test_umbrales_consumo.py`: 81 pasan.

`POST /procesar` valida el archivo antes de encolar (`413` por tamaño o exceso
de páginas, `415` si no es un PDF, `400` si está corrupto) y rechaza con `402`
al superar la cuota del plan. Registro, login y procesado tienen límite de tasa
(`429`). El gasto en LLM por documento tiene techo
(`MOTOR_OCR_TOPE_GASTO_DOCUMENTO_USD`, 1 USD por defecto): al alcanzarlo, las
páginas que faltan van a revisión humana en vez de seguir escalando.

`POST /procesar` acepta `paginas` ("1-5, 8, 11-13"): las elegidas se extraen a un
PDF nuevo y `documentos.paginas_origen` guarda el mapeo para que la interfaz
muestre el número que el usuario reconoce. La cuota cuenta las páginas elegidas,
así que elegir un rango abarata de verdad.

La retención del PDF ya existe: se borra a los `MOTOR_OCR_DIAS_RETENCION_PDF`
días (30 por defecto) y el documento sobrevive sin su imagen de página.
`DELETE /documentos/{id}` borra el documento con sus archivos.

`GET /export` suma **`latex`**, que junto con `markdown` son los formatos
principales; `ipynb` queda como opción para quien escribe código y `graphify`
para el indexador.

Quedan sueltos: el resto de las `opciones` de `POST /procesar` (idioma y DPI),
`segundos_estimados_restantes` y el lote de decisiones.

**Los tres prerrequisitos de §1 están resueltos**: hay tabla `bloques`, el PDF se
conserva y el bbox se guarda normalizado.

Complementa los wireframes de `design/wireframes/`. El frontend es un SPA de
React + Vite + TypeScript que vive en `frontend/` y que sirve estáticamente el
mismo FastAPI, así que no hay CORS ni un segundo despliegue.

```
cd frontend && npm install
npm run dev     # Vite en :5173, proxeando /api a :8000
npm run build   # deja el build en ocr_engine/web_interface/estatico/
```

Con el build presente, `uvicorn ocr_engine.web_interface.api:app` sirve la
aplicación y la API juntas. En desarrollo, sin build, `/` responde un health
check en JSON.

---

## 1. Tres prerrequisitos de almacenamiento — resueltos

No son endpoints, pero sin ellos la mitad del contrato no se podía implementar.

### 1.1 Los bloques no se persistían

`POST /procesar` calcula miles de `Bloque` y los tira. `_resumir_documento` guarda
en `documentos.resultado` sólo conteos por tipo, confianza media y la lista de
inconsistencias. El visor de revisión necesita los bloques uno por uno.

Se agregó la tabla `bloques` (`persistence/models.py::BloqueAlmacenado`):

| columna | tipo | nota |
|---|---|---|
| `id` | `String(36)` PK | el `Bloque.id` |
| `documento_id` | FK `documentos.id` ON DELETE CASCADE | indexado |
| `pagina` | `Integer` | 0-based, como en el pipeline |
| `orden_lectura` | `Integer` | de `Layout.orden_lectura` |
| `tipo` | `String(30)` | valor de `TipoBloque` |
| `origen_contenido` | `String(20)` | `texto_nativo` / `requiere_ocr` |
| `bbox` | `JSON` | **normalizado**, ver §1.3 |
| `confianza_layout` | `Float` | |
| `confianza_global` | `Float` nullable | `Ocr.confianza_global` |
| `texto_plano` | `Text` nullable | |
| `latex` | `Text` nullable | |
| `contenido_final` | `Text` nullable | lo que dejó la revisión humana |
| `micro_segmentos` | `JSON` | lista de `MicroSegmento` |
| `escalacion` | `JSON` nullable | el `Escalacion` del bloque |
| `estado_revision` | `String(20)` | `pendiente` / `resuelto` / `no_requiere` |

Índices: `(documento_id, pagina, orden_lectura)` para el visor y
`(documento_id, estado_revision, confianza_global)` para armar la cola.

Se persiste una fila por bloque en vez de un JSON gigante en `documentos.resultado`
porque la cola de revisión filtra y pagina sobre 31 000 bloques; deserializar el
documento entero en cada request no escala.

### 1.2 El PDF original se borraba

`api.py` hace `ruta_temporal.unlink(missing_ok=True)` en el `finally`. Para servir
la imagen de una página hay dos caminos:

- **Guardar el PDF** en un directorio persistente (`MOTOR_OCR_DATA_DIR`) o en un
  bucket, y renderizar la página a demanda con caché. Barato en disco, gasta CPU.
- **Guardar los PNG ya renderizados** de las páginas que tengan bloques en la cola.
  Rápido de servir, pero ocupa mucho y hay que invalidarlo si cambia el DPI.

Se eligió guardar el PDF y renderizar a demanda con caché en disco
(`web_interface/almacen.py`): el visor sólo pide las páginas que el revisor
efectivamente abre, que son pocas, y un PDF pesa mucho menos que sus páginas
renderizadas.

Esto obliga a una política de retención explícita: el PDF de un usuario queda
guardado, así que hay que decir por cuánto tiempo y borrarlo al borrar la cuenta.

### 1.3 El `bbox` no tenía un espacio de coordenadas único

- `segmentation/nativo_digital.py` lo toma de PyMuPDF: **puntos PDF**, 72 dpi.
- `segmentation/escaneado.py` lo toma de docTR: **píxeles al DPI de render**.

`escalation/_recortar_bloque` indexa la imagen renderizada con el bbox crudo, lo
cual es correcto sólo para el segundo caso. Hoy no falla porque los bloques
nativos son `TEXTO_NATIVO`, la Capa 3 los saltea y por lo tanto nunca tienen
micro-segmentos que escalar. El overlay del visor sí los dibuja a todos, así que
ahí el error aparece: un bloque nativo se dibujaría a ~36 % de su tamaño real
sobre una página renderizada a 200 dpi.

**Decisión del contrato:** la API devuelve `bbox` siempre **normalizado a la caja
de la página**, como cuatro flotantes en `[0, 1]`:

```json
"bbox": { "x0": 0.128, "y0": 0.442, "x1": 0.871, "y1": 0.509 }
```

El frontend multiplica por el tamaño en píxeles de la imagen que recibió y no
necesita saber el DPI ni qué camino de segmentación produjo el bloque. La
conversión se hace una vez al persistir: dividir por `page.rect` en el camino
nativo y por `(ancho_px, alto_px)` en el escaneado.

`segmentation/bbox.py` normaliza al crear el bloque y desnormaliza donde hacen
falta píxeles: `escalation/_recortar_bloque`, el enrutador de la Capa 3 y la
sub-segmentación. En el frontend el bbox va directo a porcentajes de CSS, así que
el overlay no necesita saber el DPI.

---

## 2. Convenciones

**Autenticación.** Dos credenciales que resuelven al mismo `Usuario`:

- **Navegador:** cookie de sesión `motor_ocr_sesion`, `HttpOnly`, `Secure`,
  `SameSite=Lax`. Es lo que usa el SPA. No se guarda la API key en
  `localStorage`: es un secreto de larga vida y cualquier XSS se la lleva.
  El flag `Secure` se apaga con `MOTOR_OCR_COOKIE_SEGURA=0` para servir por HTTP
  plano; en `localhost` no hace falta, porque los navegadores lo tratan como
  contexto seguro.
- **Máquinas:** cabecera `X-API-Key`, como hoy.

La dependencia `usuario_actual` acepta cualquiera de las dos y la usan los
endpoints de datos y `GET /auth/yo`. Los de **gestión de claves** (§8) usan
`usuario_de_sesion`, que exige cookie: si una clave filtrada pudiera emitir
claves nuevas, revocarla no serviría de nada.

**Errores.** Cuerpo uniforme, para que el frontend pueda ramificar sin parsear texto:

```json
{ "codigo": "limite_plan_superado", "detail": "El plan libre permite 200 páginas por mes" }
```

`404` y no `403` para recursos de otro usuario, como ya hace `_documento_del_usuario`.

**Paginación.** `?limite=` y `?cursor=`, keyset sobre `(pagina, orden_lectura)`.
Con 31 000 bloques por documento, `OFFSET` profundo obliga a la base a recorrer
todo lo salteado. Respuesta:

```json
{ "items": [...], "siguiente_cursor": "14:0042", "total": 4812 }
```

`siguiente_cursor` es `null` cuando no hay más.

**Prefijo.** Toda la API cuelga de **`/api`**. Las rutas de este documento se
escriben sin él por brevedad: `GET /documentos` es `GET /api/documentos`.

El prefijo no es cosmético. Sin él, `/documentos` sería a la vez el endpoint de
datos y la ruta principal del SPA, y un navegador que entrara ahí recibiría JSON
en vez de la aplicación. Todo lo que no empiece con `/api` (ni con `/docs`,
`/redoc` u `/openapi.json`) lo resuelve el router de React.

**Fechas.** ISO 8601 en UTC con `Z`.

**Páginas.** 0-based en toda la API, igual que en el pipeline. La interfaz muestra
1-based; la conversión es del frontend.

---

## 3. Sesión — implementado

### `POST /auth/registro`

```
{ "nombre": "Rimy Ortega", "email": "…", "password": "…" }
→ 201 { "usuario": Usuario, "api_key": "moc_…" }  + Set-Cookie
```

`api_key` es la primera clave del usuario y se devuelve **una sola vez**: en la base
queda su hash SHA-256, igual que hoy en `auth.crear_usuario`.

`409 codigo=email_ya_registrado` si el email existe.

`Usuario` tiene ahora `password_hash`. Acá sí corresponde un hash lento: una
contraseña elegida por una persona es atacable por diccionario, a diferencia de
la API key aleatoria de 256 bits que justifica el SHA-256. Se usa
`hashlib.scrypt` de la biblioteca estándar en vez de bcrypt o argon2, para no
sumar una dependencia con extensiones en C que compilar; los parámetros viajan
dentro del hash (`scrypt$n$r$p$sal$hash`) y se pueden subir sin invalidar las
contraseñas ya guardadas.

### `POST /auth/login`

```
{ "email": "…", "password": "…" }
→ 200 { "usuario": Usuario }  + Set-Cookie
→ 401 codigo=credenciales_invalidas
```

Mismo mensaje para email inexistente y contraseña incorrecta.

### `POST /auth/logout` → `204`, invalida la cookie.

### `GET /auth/yo`

```
→ 200 Usuario
→ 401 codigo=sin_autenticacion
```

Lo llama el SPA al montar, para decidir entre el layout autenticado y `/login`.

```ts
type Usuario = {
  id: string
  nombre: string
  email: string | null
  plan: string
  creado_en: string
}
```

---

## 4. Procesamiento asíncrono — implementado

### `POST /procesar` — **implementado**

Antes corría el pipeline completo dentro del request. Un PDF de 92 páginas tarda
minutos: el navegador cortaba por timeout mucho antes.

```
multipart/form-data: file=<pdf>, opciones=<json>
→ 202 { "documento_id": "…", "estado": "en_cola" }
```

`opciones` (todas opcionales):

```ts
type OpcionesProceso = {
  idioma_original?: string   // "es"
  dpi?: number | "auto"      // "auto" = lo que decida el triage
  escalar_llm?: boolean      // default true
  tope_gasto_usd?: number    // corta la Capa 5 y manda el resto a revisión humana
}
```

**`opciones` todavía no se implementó.** El endpoint acepta el archivo y nada
más; el motor usa el DPI que decide el triage y escala al modelo sin tope de
gasto. `tope_gasto_usd` es el que más trabajo pide: hay que chequearlo en el
bucle de `escalation.procesar_escalaciones` antes de cada llamada y, al
alcanzarlo, marcar los bloques restantes como `estado_revision="pendiente"` en
vez de escalarlos. `413 codigo=archivo_demasiado_grande` y
`402 codigo=limite_plan_superado` tampoco están: los límites del plan no existen
todavía (§9).

Lo implementado: `400 codigo=archivo_vacio` y el encolado.

**Dónde corre.** En un hilo del proceso de la API (`web_interface/trabajos.py`),
no en una cola. Alcanza para una instancia; con varias, cada una sólo ve sus
trabajos. `documentos.latido_en` guarda la última señal del worker y
`marcar_colgados()` —que se llama al arrancar la API— cierra como error lo que
lleve más de diez minutos sin latir, para que un proceso caído no deje
documentos en `procesando` para siempre. Cuando haga falta escalar, esto se
reemplaza por RQ, Celery o `arq` sin tocar los endpoints.

### `GET /documentos/{id}/estado`

```json
{
  "documento_id": "…",
  "estado": "procesando",
  "capa_actual": 3,
  "capas": [
    { "capa": 1, "nombre": "triage",        "estado": "completada", "detalle": "92 páginas · nativo digital · 3 zonas de DPI" },
    { "capa": 2, "nombre": "segmentacion",  "estado": "completada", "detalle": "11940 bloques · 12 tipos" },
    { "capa": 3, "nombre": "ocr",           "estado": "en_curso",   "progreso": { "hechos": 4892, "total": 11940 },
      "detalle_engines": { "easyocr": 4210, "pix2tex": 512, "doctr": 170 } },
    { "capa": 4, "nombre": "correccion",    "estado": "pendiente" },
    { "capa": 5, "nombre": "escalacion",    "estado": "pendiente" }
  ],
  "costo_usd_parcial": 0.0,
  "segundos_estimados_restantes": 240,
  "error": null
}
```

`estado` del documento: `en_cola` · `procesando` · `completado` · `error`.
`estado` de cada capa: `pendiente` · `en_curso` · `completada` · `omitida`.

`Pipeline` acepta ahora `al_progresar(capa, estado, **datos)` y avisa al entrar y
salir de cada capa; la Capa 3, que es donde se va el tiempo, avisa cada 1 % de
avance. El worker vuelca esos avisos a `documentos.progreso`. Si el callback
falla, el aviso se traga la excepción: informar el progreso nunca puede costar el
trabajo hecho.

El frontend sondea cada 2 s y deja de sondear cuando el documento termina.
`segundos_estimados_restantes` **no** está implementado: haría falta medir el
ritmo real de la Capa 3 para no inventar un número.

SSE en `GET /documentos/{id}/eventos` queda como alternativa; el polling alcanza
y es mucho más simple de operar.

### `GET /documentos` — **implementado**

Acepta `?estado=`, `?buscar=` (por título, sin distinguir mayúsculas),
`?necesita_revision=`, `?limite=` y `?cursor=`. Devuelve
`{items, siguiente_cursor, total}`: es un cambio de forma respecto de la lista
suelta que devolvía antes.

El orden es `(creado_en DESC, id DESC)`. El `id` desempata a propósito: dos
documentos subidos en el mismo instante harían que el cursor saltee o repita
filas si el orden no fuera total.

---

## 5. Bloques y páginas — implementado

### `GET /documentos/{id}/bloques` — **implementado**

El endpoint que hace posible el visor.

Query: `?pagina=` · `?tipo=` (repetible) · `?confianza_max=` · `?estado_revision=`
· `?limite=` · `?cursor=` · `?incluir=escalacion,micro_segmentos`

Por defecto **no** incluye `micro_segmentos` ni `escalacion`: son pesados y la
tabla de bloques no los necesita. El visor los pide explícitamente.

```ts
type Bloque = {
  id: string
  pagina: number
  orden_lectura: number
  tipo: TipoBloque              // los 17 valores del enum del motor
  origen_contenido: "texto_nativo" | "requiere_ocr"
  bbox: { x0: number; y0: number; x1: number; y1: number }   // normalizado 0–1
  confianza_layout: number
  confianza_global: number | null
  texto_plano: string | null
  latex: string | null
  contenido_final: string | null
  estado_revision: "pendiente" | "resuelto" | "no_requiere"

  micro_segmentos?: MicroSegmento[]
  escalacion?: Escalacion | null
}

type MicroSegmento = {
  tipo: string
  contenido: string
  engine_usado: "easyocr" | "pix2tex" | "doctr" | "tesseract"
  confianza_engine: number
  confianza_estructural: number
}

type Escalacion = {
  requirio_escalacion: boolean
  cola_origen: "micro_segmento" | "inconsistencia_documental" | null
  contenido_llm: string | null      // lo que devolvió el modelo
  confianza_llm: number | null
  razon_escalacion: string | null
  requiere_revision_humana: boolean
  costo_usd: number
  tokens_entrada: number
  tokens_salida: number
}
```

`contenido_llm` se agregó al modelo `Escalacion`: `EscalationResult` traía el
contenido corregido pero se perdía al terminar el pipeline, y el panel de revisión
compara "lo que leyó el motor" contra "lo que corrigió el modelo". La Capa 5 ahora
vuelca sus resultados sobre el bloque que los originó.

**La cola de revisión no es un endpoint aparte**, es este mismo con
`?estado_revision=pendiente&orden=confianza`. Un endpoint separado duplicaría los
filtros.

### `GET /documentos/{id}/paginas` — **implementado**

```json
{ "total_paginas": 34,
  "paginas": [ { "pagina": 0, "ancho_px": 1654, "alto_px": 2339, "dpi": 200, "bloques": 141 } ] }
```

El frontend necesita `ancho_px`/`alto_px` para desnormalizar los bbox antes de que
cargue la imagen, y así reservar el espacio sin saltos de layout.

### `GET /documentos/{id}/paginas/{n}` — **implementado**

```
→ 200 image/png
    Cache-Control: private, max-age=86400
    ETag: "<documento_id>:<n>:<dpi>"
→ 404 si la página no existe o el documento no es del usuario
```

Query opcional `?ancho=` para pedir una versión reescalada (el visor a 86 % no
necesita 1654 px). Sirve la imagen de la página completa, no el recorte: el
overlay se dibuja encima en el cliente, y así una misma imagen sirve para todos
los bloques de la página.

---

## 6. Revisión — implementado

### `POST /revision/{documento_id}/decision` — **implementado**

El cuerpo actual pide `bloque_id`, `decision`, `contenido_final`, `comentarios` y
`confianza_usuario`, y guarda `tipo_bloque=""`, `pagina=0` y `confianza_engine=0.0`
porque el cliente no los manda.

Eso rompe el auto-ajuste: `AjustadorUmbrales.calcular_umbrales_optimos` agrupa las
decisiones por `d['tipo_bloque']`, que siempre vale `""`. El loop de feedback está
cortado en ese punto.

**El servidor los completa desde el bloque**, no el cliente:

```
{ "bloque_id": "…", "decision": "aceptar"|"rechazar"|"editar"|"escalar",
  "contenido_final": "…", "confianza_usuario": 0.9, "comentarios": "" }
→ 200 { "decision_id": 12, "siguiente_bloque_id": "…" | null }
```

Además la decisión debe **escribirse en el bloque**: `contenido_final` y
`estado_revision="resuelto"`. Hoy sólo se registra en `decisiones` y el bloque
queda igual, con lo que la exportación seguiría entregando el texto sin corregir.

`siguiente_bloque_id` evita un round-trip: el visor avanza sin volver a pedir la cola.

`422 codigo=bloque_no_pertenece_al_documento`.

### `POST /revision/{documento_id}/decisiones`

Lote, mismo cuerpo en una lista. Para "aceptar todo lo que quedó arriba de 0.9".

---

## 7. Umbrales

Hoy `AjustadorUmbrales` lee y escribe `umbrales_config.json` con **ruta relativa**
y **sin usuario**: es la misma trampa que ya se corrigió en `persistence` — el
archivo se escribe en el cwd y se pierde en cada despliegue — y además haría que
un usuario le cambiara los umbrales a todos los demás. Los umbrales pasan a una
tabla `umbrales` con `usuario_id`.

### `GET /umbrales`

```json
{ "capa3": { "parrafo": 0.75, "formula_display": 0.70, "…": 0.0 },
  "capa4": { "estructura_rota": 0.80, "inconsistencia": 1.00 },
  "globales": { "umbral_confianza_engine": 0.75,
                "umbral_escalacion_micro_segmento": 0.6,
                "umbral_confianza_global_escalacion": 0.70 },
  "actualizado_en": "2026-08-24T18:00:00Z" }
```

### `PUT /umbrales`

Los sliders de la pantalla. Acepta un objeto parcial con la misma forma; valida
`0 ≤ v ≤ 1` y devuelve el estado completo resultante.

### `GET /umbrales/recomendaciones`

Los calcula **sin aplicarlos**. Hoy `POST /auto-ajuste` calcula y aplica en un solo
paso, así que la pantalla no puede mostrar la propuesta antes de decidir.

```json
{ "decisiones_analizadas": 47,
  "recomendaciones": [
    { "ambito": "capa3", "clave": "formula_display", "actual": 0.60, "propuesto": 0.68,
      "confianza": 0.82, "razon": "62 % de rechazos sobre lo que el motor daba por bueno",
      "aplicable": true } ] }
```

`aplicable` reproduce `UmbralOptimo.aplicable()`: confianza > 0.7 y cambio > 0.02.

### `POST /umbrales/aplicar`

Reemplaza a `POST /auto-ajuste`. Recibe las claves a aplicar (o todas las
aplicables), guarda un backup y devuelve el resultado de la validación.

**Advertencia:** `AjustadorUmbrales.validar_cambios` hoy devuelve valores fijos
(`"razon": "Simulado - requiere validación real"`). La pantalla muestra "revertido
automáticamente porque la confianza bajó 4.1 %", que sería inventado. O se
implementa la validación contra un lote real, o el endpoint devuelve
`validacion: null` y la interfaz no promete lo que no hace.

Y `GestorDecisiones._decisiones_cache` es un diccionario de módulo: se vacía en
cada reinicio, así que el auto-ajuste sólo ve las decisiones de la sesión actual.
Debe leer de la tabla `decisiones`.

---

## 8. API keys — implementado

Hoy se crean por CLI (`gestion_usuarios.py`).

```
GET    /api-keys        → [ { id, nombre, prefijo: "moc_8kQ2vf", creada_en, ultimo_uso_en, revocada_en } ]
POST   /api-keys        { "nombre": "notebook local" } → 201 { …, "api_key": "moc_…" }   ← una sola vez
DELETE /api-keys/{id}   → 204
```

`ultimo_uso_en` obliga a un `UPDATE` por request autenticado con clave. Con SQLite
conviene escribirlo con granularidad de minutos para no serializar la base en cada
llamada.

La clave se movió de la fila `usuarios` a una tabla `api_keys` con `usuario_id`,
para que un usuario pueda tener varias y revocar una sin perder las demás.
`ocr_engine/persistence/migraciones.py` mueve las claves de una base ya
desplegada, y es idempotente.

Los tres endpoints exigen **cookie de sesión**, no API key: si una clave filtrada
pudiera emitir claves nuevas, revocarla no serviría de nada.

---

## 9. Consumo

### `GET /consumo` — **amplía el existente**

Hoy devuelve totales. La pantalla necesita además la serie diaria y el desglose.

```
?desde=2026-08-01&hasta=2026-08-31
```

```json
{ "usuario": "Rimy Ortega", "plan": "libre",
  "limites": { "paginas_mes": 200, "gasto_llm_mes_usd": 2.0 },
  "totales": { "documentos": 11, "paginas": 228, "llamadas_llm": 16,
               "tokens_entrada": 20640, "tokens_salida": 3432, "costo_llm_usd": 0.0204 },
  "serie_diaria": [ { "fecha": "2026-08-24", "micro_segmento_usd": 0.0031,
                      "inconsistencia_documental_usd": 0.0006 } ],
  "por_documento": [ { "documento_id": "…", "titulo": "c7.pdf", "llamadas": 14,
                       "tokens_entrada": 18420, "tokens_salida": 3106, "costo_usd": 0.0182 } ] }
```

`limites` no existe todavía: los planes están sólo como el string
`usuarios.plan`. Hay que definirlos en algún lado para poder mostrar la barra de
consumo y para poder rechazar con `402`.

---

## 10. Exportación

### `GET /documentos/{id}/export?formato=graphify|markdown|ipynb`

Devuelve el documento con `contenido_final` aplicado donde la revisión humana lo
haya dejado, cayendo a `latex` o `texto_plano` cuando no. `graphify` es el JSON de
bloques que consume el indexador; los otros dos son archivos.

Para documentos grandes conviene generarlo como job y devolver `202` con una URL
de descarga, en vez de armar 31 000 bloques dentro del request.

---

## 11. Resumen

| Endpoint | Estado |
|---|---|
| `POST /auth/registro`, `/auth/login`, `/auth/logout`, `GET /auth/yo` | **implementados** |
| `POST /procesar` | **implementado** · asíncrono, `202` (sin `opciones`) |
| `GET /documentos/{id}/estado` | **implementado** |
| `GET /documentos` | **implementado** · filtros y cursor |
| `GET /documentos/{id}` | existe · sin cambios |
| `GET /documentos/{id}/bloques` | **implementado** |
| `GET /documentos/{id}/paginas` | nuevo |
| `GET /documentos/{id}/paginas/{n}` | nuevo |
| `POST /revision/{id}/decision` | **implementado** · completa campos y escribe el bloque |
| `POST /revision/{id}/decisiones` | nuevo |
| `GET /umbrales` | **implementado** · por usuario |
| `PUT /umbrales` | **implementado** |
| `GET /umbrales/recomendaciones` | **implementado** · calcula sin aplicar |
| `POST /umbrales/aplicar` | **implementado** · reemplaza a `POST /auto-ajuste`, que se eliminó |
| `GET/POST/DELETE /api-keys` | **implementados** |
| `GET /consumo` | **implementado** · rango, serie diaria y desglose |
| `GET /documentos/{id}/export` | **implementado** · latex, markdown, ipynb, graphify |
| `DELETE /documentos/{id}` | **implementado** · borra el documento y sus archivos |

### Orden de construcción

1. ~~**Sesión y lista.**~~ Hecho: `auth/*`, `api-keys/*` y `GET /documentos` con
   filtros y cursor. El SPA ya puede arrancar contra esto.
2. ~~**Jobs.**~~ Hecho: `POST /procesar` asíncrono y `GET /estado`, con el callback
   de progreso en `Pipeline`. Falta `opciones` y los límites de plan.
3. ~~**Bloques.**~~ Hecho: tabla `bloques`, retención del PDF, bbox normalizado,
   `GET /bloques` y `/paginas/{n}`. El visor de revisión ya funciona.
4. ~~**Umbrales.**~~ Hecho: tabla `umbrales` por usuario, recomendaciones
   calculadas desde la tabla `decisiones` y separadas de la aplicación.
   `validar_cambios` sigue devolviendo valores fijos, así que el endpoint
   responde `validacion: null` en vez de mostrar un número inventado.
5. ~~**Consumo y exportación.**~~ Hecho: `GET /consumo` con rango, serie diaria
   y desglose por documento, y `GET /export` en los tres formatos con
   `contenido_final` aplicado.

Los pasos 1 y 2 se pueden hacer en paralelo. El 4 depende del 3.
