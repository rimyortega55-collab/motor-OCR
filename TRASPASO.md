# Traspaso — frontend de motor-OCR

> Archivo temporal para continuar el trabajo en otra sesión. Borralo cuando ya no
> haga falta. Fecha: 2026-08-25.

## Qué es esto

`motor-OCR` es un pipeline de 7 capas para OCR de documentos matemáticos
(triage → segmentación → OCR especializado → corrección determinista →
escalación al LLM → revisión humana → auto-ajuste de umbrales).

En esta sesión se diseñó y construyó el **frontend SaaS**: wireframes, contrato
de API, y los pasos 1 a 3 del plan de implementación.

**Estado: pasos 1, 2 y 3 hechos. Faltan el 4 y el 5.**

## Cómo correr

Es Windows. El intérprete del proyecto es `.venv/Scripts/python.exe`.

```bash
# Pruebas (58 pasan, 15 se saltean por falta de modelos pesados)
.venv/Scripts/python.exe -m pytest ocr_engine/tests/ -q

# API
.venv/Scripts/python.exe -m uvicorn ocr_engine.web_interface.api:app --reload

# Frontend en desarrollo (Vite en :5173, proxea /api a :8000)
cd frontend && npm run dev

# Frontend compilado (lo sirve el propio FastAPI, un solo origen)
cd frontend && npm run build
```

Variables de entorno útiles:

| Variable | Para qué |
|---|---|
| `MOTOR_OCR_DATA_DIR` | Dónde viven la base SQLite, los PDF y el caché de páginas. Por defecto `datos/` |
| `MOTOR_OCR_COOKIE_SEGURA=0` | Apaga el flag `Secure` de la cookie. Hace falta para servir por HTTP plano; en `localhost` no |
| `DATABASE_URL` | Apuntar a Postgres sin tocar código |
| `MOTOR_OCR_UMBRAL_CONFIANZA_GLOBAL_ESCALACION=0.97` | Sube el umbral para que entren bloques a la cola de revisión y se pueda probar el visor |

## Documentos de referencia

- **`docs/CONTRATO_API_FRONTEND.md`** — el contrato completo, endpoint por
  endpoint, con el estado de cada uno. Es la fuente de verdad; mantenelo al día.
- **`design/wireframes/`** — los wireframes de las 9 pantallas más el mapa de
  navegación, como archivos `.dc.html` + `canvas.json`.
- Artefactos publicados (los mismos contenidos, para leer):
  - Wireframes: https://claude.ai/code/artifact/54db1832-ef00-4a05-978d-e9ee28bf5511
  - Contrato: https://claude.ai/code/artifact/7c4ccbfb-2c0e-4d5f-bf36-2f64633c3e55

---

## Decisiones tomadas (no las revientas sin motivo)

Estas se tomaron con una razón concreta. Si vas a cambiarlas, que sea a
sabiendas.

### 1. Toda la API cuelga de `/api`

`GET /documentos` era a la vez el endpoint de datos y la ruta principal del SPA:
un navegador que entraba ahí recibía JSON en vez de la aplicación, y `/revision`
daba 404. Todo lo que no empiece con `/api` (ni `/docs`, `/redoc`,
`/openapi.json`) lo resuelve el router de React. Hay una prueba que lo fija:
`test_las_rutas_del_spa_no_chocan_con_las_de_la_api`.

### 2. Dos credenciales, dos hashes distintos

- **Navegador**: cookie `motor_ocr_sesion`, HttpOnly, SameSite=Lax. Las sesiones
  se guardan en base (tabla `sesiones`) y no como JWT, para poder revocarlas: un
  token firmado sigue valiendo hasta que expira.
- **Máquinas**: cabecera `X-API-Key`.
- La **contraseña** usa `hashlib.scrypt` (lento, de la biblioteca estándar — se
  evitó bcrypt/argon2 para no sumar una dependencia con extensiones en C que
  compilar en Windows). La **API key** usa SHA-256 (rápido) porque es un secreto
  aleatorio de 256 bits: no hay diccionario que probar.
- Los tres endpoints de `/api-keys` exigen **cookie, no API key**. Si una clave
  filtrada pudiera emitir claves nuevas, revocarla no serviría de nada.

### 3. `bbox` siempre normalizado a `[0, 1]`

Los dos caminos de segmentación producían el bbox en unidades distintas:
`nativo_digital` en puntos PDF (72 dpi), `escaneado` en píxeles del render. Ver
`ocr_engine/segmentation/bbox.py`. Quien necesita píxeles desnormaliza con el
tamaño de la imagen que tiene en la mano. En el frontend el bbox va **directo a
porcentajes de CSS**, así que el overlay no necesita saber el DPI.

### 4. La cola de revisión no es un endpoint aparte

Es `GET /api/documentos/{id}/bloques?estado_revision=pendiente&orden=confianza`.
Uno separado duplicaría todos los filtros para devolver las mismas filas.

### 5. Paginación por cursor, no por OFFSET

Con 31 000 bloques por documento, `OFFSET` obliga a la base a recorrer todo lo
salteado. El cursor es keyset sobre `(pagina, orden_lectura)` para bloques y
sobre `(creado_en, id)` para documentos. **El `id` desempata a propósito**: dos
documentos subidos en el mismo instante harían que la paginación saltee o repita
filas si el orden no fuera total. Hay una prueba para eso.

### 6. Errores con sobre uniforme

```json
{ "detail": { "codigo": "limite_plan_superado", "detail": "texto para mostrar" } }
```

El frontend ramifica por `codigo`, nunca parseando el mensaje. `404` y no `403`
para recursos de otro usuario: no se confirma que existan.

### 7. Los trabajos son hilos del proceso, no una cola

`web_interface/trabajos.py`. Alcanza para una instancia. Se escribe
`documentos.latido_en` y `marcar_colgados()` —que corre al arrancar la API—
cierra como error lo que lleve más de diez minutos sin latir, para que un proceso
caído no deje documentos en `procesando` para siempre. Cuando haga falta escalar,
se reemplaza por RQ/Celery/`arq` **sin tocar los endpoints**.

---

## Lo que se construyó

### Paso 1 — sesión, API keys, listado

| Archivo | Qué hace |
|---|---|
| `ocr_engine/web_interface/auth.py` | Contraseñas, sesiones, resolución por cookie **o** API key |
| `ocr_engine/web_interface/rutas_cuenta.py` | `auth/registro`, `auth/login`, `auth/logout`, `auth/yo`, `GET/POST/DELETE /api-keys` |
| `ocr_engine/persistence/models.py` | Tablas `api_keys` y `sesiones`; `password_hash` en `Usuario` |
| `ocr_engine/persistence/migraciones.py` | Migraciones idempotentes para bases ya desplegadas |
| `api.py::listar_documentos` | Filtros (`estado`, `buscar`, `necesita_revision`) y cursor |

### Paso 2 — procesamiento asíncrono

| Archivo | Qué hace |
|---|---|
| `ocr_engine/web_interface/trabajos.py` | Worker en hilo, progreso por capa, `marcar_colgados()` |
| `ocr_engine/pipeline.py` | `Pipeline(al_progresar=...)`, avisa al entrar y salir de cada capa |
| `api.py::procesar_pdf` | Responde **202** y encola |
| `api.py::estado_documento` | `GET /api/documentos/{id}/estado` con el avance de las 5 capas |

La Capa 3 avisa cada 1 % de avance (avisar bloque por bloque satura la base). La
Capa 5 se marca **`omitida`**, no `completada`, cuando no hay credenciales de
Anthropic: mostrarla como completada haría creer que el modelo revisó bloques que
nunca vio.

### Paso 3 — bloques, páginas y decisiones

| Archivo | Qué hace |
|---|---|
| `ocr_engine/segmentation/bbox.py` | `normalizar_bbox` / `desnormalizar_bbox` |
| `ocr_engine/web_interface/almacen.py` | Guarda PDFs y renderiza páginas a demanda con caché |
| `ocr_engine/web_interface/rutas_bloques.py` | `GET /bloques`, `/bloques/{id}`, `/paginas`, `/paginas/{n}` |
| `persistence/models.py::BloqueAlmacenado` | Tabla `bloques` con dos índices |
| `api.py::registrar_decision` | Completa los campos desde el bloque y **escribe la decisión en el bloque** |

Dos bugs de fondo arreglados acá:

- **La corrección del modelo se perdía.** `EscalationResult` traía el contenido
  corregido pero nadie lo escribía en el bloque. Se agregó `contenido_llm` al
  modelo `Escalacion` y `escalation/_aplicar_al_bloque` lo vuelca. Sin esto el
  panel de revisión no tenía qué comparar.
- **El feedback loop seguía cortado.** La decisión guardaba `tipo_bloque=""` y
  `AjustadorUmbrales.calcular_umbrales_optimos` agrupa justamente por ese campo.
  Ahora lo completa el servidor.

### Frontend

React 19 + Vite 8 + TypeScript en `frontend/`. TanStack Query para la API.

```
frontend/src/
  api/cliente.ts      fetch con sobre de error normalizado; antepone /api
  api/consultas.ts    todos los hooks de TanStack Query
  api/tipos.ts        tipos del contrato, escritos a mano
  componentes/Armazon.tsx   layout con barra lateral + guard de sesión
  componentes/Guard.tsx     guard sin layout (para el visor a pantalla completa)
  rutas/Entrar.tsx     login y registro
  rutas/Documentos.tsx listado con filtros y cursor
  rutas/Subir.tsx      dropzone y barra por capas
  rutas/Revision.tsx   el visor: cola + página con overlay + panel de decisión
  rutas/Cuenta.tsx     API keys
  rutas/Consumo.tsx    totales
  rutas/Pendiente.tsx  pantalla honesta para lo que todavía no existe
  estilos.css          sistema visual, con tema claro y oscuro
```

El sistema visual continúa el de los wireframes: papel cálido, tinta, indigo
`#4F4CDE` para lo accionable y ámbar `#A8551A` para lo que pide atención. IBM
Plex Sans + IBM Plex Mono.

---

## Trampas conocidas

1. **`c1.pdf` no genera cola de revisión.** docTR tiene confianza 0,89–0,99 en ese
   documento, todo por encima del umbral de 0,70. La cola vacía es correcta.
   Para probar el visor: `MOTOR_OCR_UMBRAL_CONFIANZA_GLOBAL_ESCALACION=0.97`.

2. **Los documentos procesados antes del paso 3 no tienen PDF guardado.**
   `GET /paginas` devuelve `409 pdf_no_disponible` y lo explica. Hay que volver a
   subirlos.

3. **`SessionLocal` usa `autoflush=False`.** Si modificás un objeto y después
   consultás contando, la consulta no ve el cambio. Hace falta `sesion.flush()`
   explícito. Ya mordió una vez en `registrar_decision`.

4. **Los JSON de `pruebas/resultados_capa*/` están modificados en el working tree
   y nadie de esta sesión los tocó.** Los escribe `pruebas/test_capa2.py` y
   compañía, que son scripts sueltos, no pruebas de pytest. Después del cambio de
   bbox quedaron desactualizados: registran bboxes absolutos y una corrida nueva
   los escribiría normalizados. Decidí no regenerarlos porque tardan mucho.

5. **Los heredocs de bash con comillas dentro se rompen** en este entorno. Para
   escribir archivos con HTML o CSS, usá la herramienta Write, no `cat <<EOF`.

6. **`app.routes` no muestra las rutas de los routers incluidos** en FastAPI
   0.141: aparecen envueltas en `_IncludedRouter`. Para listarlas, iterá
   `router.routes` de cada router. Me hizo creer que había roto el cableado.

7. **`GET /api/documentos` devuelve `{items, siguiente_cursor, total}`**, no una
   lista suelta. Es un cambio incompatible respecto de la versión anterior.

8. **Alguien editó `persistence/db.py` durante la sesión** para poner
   `create_all` antes de `migrar`. Es correcto y arregla un bug real que yo tenía:
   al revés, el backfill de claves fallaba con "no such table: api_keys" en una
   base vieja. No lo revientas.

---

## Qué falta

### Paso 4 — umbrales por usuario (el que sigue)

Es lo que cierra el feedback loop de la Capa 7. Tres cosas:

1. **Los umbrales son globales y viven en un archivo.**
   `web_interface/ajuste_umbrales.py` lee y escribe `umbrales_config.json` con
   **ruta relativa** y **sin usuario**: es la misma trampa que ya se corrigió en
   `persistence` (se pierde en cada despliegue), y además un usuario le cambiaría
   los umbrales a todos. Hay que moverlos a una tabla `umbrales` con `usuario_id`.

2. **`GestorDecisiones._decisiones_cache` es un diccionario de módulo.** Se vacía
   en cada reinicio, así que el auto-ajuste sólo ve las decisiones de la sesión
   actual. Debe leer de la tabla `decisiones`, que ahora sí tiene `tipo_bloque`
   bien poblado.

3. **`AjustadorUmbrales.validar_cambios` devuelve valores fijos**, con
   `"razon": "Simulado - requiere validación real"`. El wireframe de la pantalla
   muestra "revertido automáticamente porque la confianza bajó 4.1 %" — eso sería
   inventado. **O se implementa la validación contra un lote real, o el endpoint
   devuelve `validacion: null` y la interfaz no promete lo que no hace.** No
   dibujes el número simulado.

Endpoints: `GET /umbrales` (por usuario), `PUT /umbrales`,
`GET /umbrales/recomendaciones` (calcula sin aplicar) y `POST /umbrales/aplicar`
(reemplaza a `POST /auto-ajuste`). El detalle está en la sección 7 del contrato.

En el frontend, `rutas/Pendiente.tsx` ya ocupa `/umbrales` y dice qué falta;
reemplazalo por la pantalla real.

### Paso 5 — consumo y exportación

- `GET /consumo` con serie diaria, desglose por documento y por cola, y los
  límites del plan. Los planes hoy son sólo el string `usuarios.plan`: hay que
  definirlos en algún lado para poder mostrar la barra y rechazar con `402`.
- `GET /documentos/{id}/export?formato=graphify|markdown|ipynb`, con
  `contenido_final` aplicado donde la revisión humana lo dejó.

### Pendientes sueltos

- **`opciones` de `POST /procesar`** (idioma, DPI, `tope_gasto_usd`) está en el
  contrato pero no implementado. El endpoint sólo acepta el archivo. La pantalla
  de subida lo dice explícitamente en vez de mostrar controles muertos.
  `tope_gasto_usd` es el que más trabajo pide: hay que chequearlo en el bucle de
  `escalation.procesar_escalaciones` y, al alcanzarlo, marcar los bloques
  restantes como `estado_revision="pendiente"` en vez de escalarlos.
- **`segundos_estimados_restantes`** en `GET /estado`: haría falta medir el ritmo
  real de la Capa 3 para no inventar un número.
- **`POST /revision/{id}/decisiones`** en lote, para "aceptar todo lo que quedó
  arriba de 0.9".
- **Política de retención del PDF**: ahora se guarda y nadie lo borra. Hay que
  decidir por cuánto tiempo y borrarlo al borrar la cuenta.

---

## Cómo trabajar acá

- El proyecto está en castellano: nombres, comentarios y mensajes. Seguí esa
  convención.
- Los comentarios explican **por qué**, no qué. Hay bastante contexto histórico
  guardado en ellos ("antes esto se hacía así y fallaba porque…"); es
  deliberado.
- Cada paso implementado tiene su archivo de pruebas: `test_auth_api.py`,
  `test_trabajos.py`, `test_bloques.py`. Seguí el patrón: base SQLite temporal
  por archivo, `DATABASE_URL` fijada antes de importar nada del motor.
- Cuando implementes algo del contrato, **actualizá
  `docs/CONTRATO_API_FRONTEND.md`**. Dejar ahí un "no implementado" que ya está
  hecho —o al revés— es peor que no tener el documento.
