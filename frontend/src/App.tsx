import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import Armazon from './componentes/Armazon'
import Guard from './componentes/Guard'
import Consumo from './rutas/Consumo'
import Cuenta from './rutas/Cuenta'
import Documentos from './rutas/Documentos'
import Entrar from './rutas/Entrar'
import Pendiente from './rutas/Pendiente'
import Revision from './rutas/Revision'
import Subir from './rutas/Subir'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/entrar" element={<Entrar />} />

        {/* El visor ocupa la pantalla entera, así que va fuera del armazón. */}
        <Route element={<Guard />}>
          <Route path="/documentos/:documentoId/revision" element={<Revision />} />
        </Route>

        {/* Todo lo autenticado cuelga del armazón, que hace de guard. */}
        <Route element={<Armazon />}>
          <Route path="/documentos" element={<Documentos />} />
          <Route path="/subir" element={<Subir />} />
          <Route path="/consumo" element={<Consumo />} />
          <Route path="/cuenta" element={<Cuenta />} />


          <Route
            path="/umbrales"
            element={
              <Pendiente
                titulo="Umbrales y auto-ajuste"
                paso="Paso 4 del contrato"
                descripcion="Los umbrales que deciden qué se escala al modelo y qué va a revisión humana, más los ajustes que el motor recomienda a partir de tus decisiones. Hoy los umbrales son globales y viven en un archivo de ruta relativa, así que un usuario se los cambiaría a todos."
                bloqueadoPor={[
                  'PUT /umbrales',
                  'GET /umbrales/recomendaciones',
                  'tabla umbrales por usuario',
                ]}
              />
            }
          />

        </Route>

        <Route path="*" element={<Navigate to="/documentos" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
