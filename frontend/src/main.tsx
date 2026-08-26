import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import './estilos.css'

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      // La pestaña vuelve al frente constantemente mientras se revisa un PDF en
      // otra ventana; refetchear en cada foco haria parpadear las tablas.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={cliente}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
