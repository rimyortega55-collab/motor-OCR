import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** Rutas que atiende FastAPI y no el SPA.
 *
 * En desarrollo se proxean para que el navegador vea un solo origen: así la
 * cookie de sesión viaja sin CORS y sin `SameSite=None`, igual que en
 * producción, donde el propio FastAPI sirve el build.
 *
 * Toda la API cuelga de /api, así que alcanza con proxear ese prefijo y la
 * documentación interactiva.
 */
const RUTAS_API = ['/api', '/docs', '/openapi.json']

const API = process.env.MOTOR_OCR_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      RUTAS_API.map((ruta) => [ruta, { target: API, changeOrigin: false }]),
    ),
  },
  build: {
    // El build va adentro del paquete Python para que FastAPI lo sirva desde el
    // mismo origen: sin segundo despliegue y sin CORS.
    outDir: '../ocr_engine/web_interface/estatico',
    emptyOutDir: true,
  },
})
