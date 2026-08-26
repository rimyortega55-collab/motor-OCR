# motor-OCR — frontend

SPA en React + TypeScript + Vite: la interfaz para usuarios que no programan
del proyecto [motor-OCR](../README.md). Subida de documentos, seguimiento de
estados, revisión de bloques de baja confianza, traducción y administración
de cuenta.

## Desarrollo

```bash
npm install
npm run dev
```

Levanta Vite en `:5173` y proxea `/api` hacia el backend FastAPI en `:8000`
(ver [`vite.config.ts`](vite.config.ts)). Con el backend corriendo
(`uvicorn motor_ocr_api.api:app --reload` desde la raíz del repo), la app
queda funcional en `http://localhost:5173`.

## Build

```bash
npm run build
```

El resultado en `dist/` es servido directamente por FastAPI
([`motor_ocr_api/estaticos.py`](../packages/motor_ocr_api/estaticos.py)), así
que en producción la API y el frontend cuelgan de un solo origen.

## Estructura

```
src/
  api/          cliente HTTP y tipos de la API
  componentes/  piezas reutilizables (armazón, guards de ruta, íconos, exportar)
  rutas/        una pantalla por ruta (subida, documentos, revisión, umbrales, ...)
```
