import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import Administracion from './rutas/Administracion'
import Armazon from './componentes/Armazon'
import Guard from './componentes/Guard'
import Documentos from './rutas/Documentos'
import Entrar from './rutas/Entrar'
import Umbrales from './rutas/Umbrales'
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

        {/* Todo lo protegido cuelga del armazón, que hace de guard. */}
        <Route element={<Armazon />}>
          <Route path="/documentos" element={<Documentos />} />
          <Route path="/subir" element={<Subir />} />
          <Route path="/umbrales" element={<Umbrales />} />
          <Route path="/admin" element={<Administracion />} />
        </Route>

        <Route path="*" element={<Navigate to="/documentos" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
