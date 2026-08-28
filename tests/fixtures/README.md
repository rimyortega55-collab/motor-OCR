# Fixtures

Dos mecanismos que se complementan:

- **`sinteticos.py`** — genera PDF en tiempo de prueba con PyMuPDF. No se
  versiona ningún binario, se versiona el generador. Cubre casos de borde y
  contratos: cero páginas, sin capa de texto, con fuente matemática, perfiles
  mixtos. Determinista y liviano.
- **PDF con licencia redistribuible** en este mismo directorio, para medir
  fidelidad sobre material real. Cada uno lleva su fila en
  [MANIFEST.md](MANIFEST.md), que es también donde están las reglas de qué
  licencia entra y cuál no.

El corpus viejo (`pruebas/pdfs_de_prueba/`) son libros de texto con copyright:
está en `.gitignore` y no se publica.
