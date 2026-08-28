/** Íconos de trazo, dibujados a mano sobre una grilla de 24.
 *
 * Inline y no de una librería: son seis, y una dependencia entera para eso
 * pesaría más que el resto del bundle.
 */

type Props = { tam?: number }

const base = (tam: number) => ({
  width: tam,
  height: tam,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
})

export const IconoDocumento = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <rect x="4" y="3" width="16" height="18" rx="2" />
    <path d="M8 9h8M8 13h6" />
  </svg>
)

export const IconoRevision = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M8 12l3 3 5-6" />
  </svg>
)

export const IconoDeslizadores = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <path d="M4 7h16M4 12h16M4 17h16" />
    <circle cx="9" cy="7" r="2.2" fill="var(--superficie-2)" />
    <circle cx="15" cy="12" r="2.2" fill="var(--superficie-2)" />
    <circle cx="7" cy="17" r="2.2" fill="var(--superficie-2)" />
  </svg>
)

export const IconoLlave = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <circle cx="8" cy="12" r="4" />
    <path d="M12 12h9M18 12v3" />
  </svg>
)

export const IconoSubir = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <path d="M12 16V4M7 9l5-5 5 5" />
    <path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />
  </svg>
)

export const IconoBuscar = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <circle cx="11" cy="11" r="7" />
    <path d="M16.5 16.5L21 21" />
  </svg>
)

export const IconoAlerta = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v6M12 16.5v.5" />
  </svg>
)

export const IconoSalir = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <path d="M15 17l5-5-5-5M20 12H9M12 3H5a1 1 0 00-1 1v16a1 1 0 001 1h7" />
  </svg>
)

export const IconoMas = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)

export const IconoEngranaje = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 3v2.4M12 18.6V21M4.5 7.5l2 1.2M17.5 15.3l2 1.2M3 12h2.4M18.6 12H21M4.5 16.5l2-1.2M17.5 8.7l2-1.2M7.5 4.5l1.2 2M15.3 17.5l1.2 2M16.5 4.5l-1.2 2M8.7 17.5l-1.2 2" />
  </svg>
)

export const IconoRobot = ({ tam = 16 }: Props) => (
  <svg {...base(tam)}>
    <rect x="5" y="9" width="14" height="10" rx="2" />
    <path d="M12 5.5V9M9.5 3.5h5" />
    <circle cx="9.5" cy="14" r="1" fill="currentColor" stroke="none" />
    <circle cx="14.5" cy="14" r="1" fill="currentColor" stroke="none" />
    <path d="M9 17h6M2.5 12v4M21.5 12v4" />
  </svg>
)
