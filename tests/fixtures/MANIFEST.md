# Corpus de fixtures

Los PDF de este directorio se versionan en el repositorio público, así que
**todos tienen que ser redistribuibles**. Es la regla dura del directorio y no
admite excepciones "temporales": el corpus anterior (`pruebas/pdfs_de_prueba/`)
son libros de texto con copyright, está en `.gitignore` y no puede publicarse.

Cada archivo lleva su fila en la tabla de procedencia. Un PDF sin fila es un
PDF que nadie puede auditar y hay que sacarlo.

## Por qué conviven corpus real y generador sintético

`sinteticos.py` genera PDF en tiempo de prueba y cubre casos de borde y
contratos: cero páginas, sin capa de texto, con fuente matemática, perfiles
mixtos, dos columnas. Es determinista, no pesa nada y se lee en un diff.

Lo que no puede hacer es medir fidelidad. Una página nacida de PyMuPDF tiene
capa de texto perfecta y tipografía limpia, y una rasterizada no tiene ruido,
inclinación ni artefactos de compresión. El motor se juzga por lo que hace con
material real; por eso el sintético fija el comportamiento y el corpus real
mide la calidad.

## Perfiles y cobertura

| Perfil | Archivo | Por qué está |
| --- | --- | --- |
| Texto plano narrativo | `texto_narrativo.pdf` | El caso barato: nativo-digital sin fórmulas, se saltea el OCR entero |
| Fórmulas densas | `formulas_densas.pdf` | El caso que justifica el proyecto |
| Tablas | `tablas.pdf` | Estructura que el flujo de lectura debe preservar al exportar |
| Escaneado sin capa de texto | `escaneado.pdf` | Obliga al pase visual completo; escaneo genuino, con ruido e inclinación reales |
| Escaneado con capa de OCR ajena | `escaneado_con_ocr.pdf` | Un escaneo que *parece* nativo-digital porque alguien le pegó una capa de OCR imperfecta |
| Dos columnas | `sinteticos.pdf_dos_columnas()` | Orden de lectura; es geometría, no fidelidad, así que se genera |

## Tabla de procedencia

| Archivo | Obra y autoría | Licencia | Origen | Páginas |
| --- | --- | --- | --- | --- |
| `texto_narrativo.pdf` | *Introduction to Philosophy / The Branches of Philosophy*, colaboradores de Wikibooks | CC BY-SA 4.0 | https://en.wikibooks.org/wiki/Introduction_to_Philosophy/The_Branches_of_Philosophy | las 3 del export |
| `formulas_densas.pdf` | *Physics*, OpenStax (Rice University) | CC BY 4.0 | https://openstax.org/details/books/physics | 367-370 del PDF completo |
| `tablas.pdf` | *Introductory Statistics*, OpenStax (Rice University) | CC BY 4.0 | https://openstax.org/details/books/introductory-statistics | 79-80 y 429-430 |
| `escaneado_con_ocr.pdf` | NASA Technical Memorandum, informe técnico del gobierno de EE.UU. | Dominio público | https://archive.org/details/nasa_techdoc_19750005443 | 3-6 |
| `escaneado.pdf` | El mismo informe, **derivado**: se conservó sólo la imagen de cada página y se descartó la capa de OCR que agrega archive.org | Dominio público | derivado del anterior | 3-6 |

Peso total del directorio: menos de 1 MB. De referencia, el corpus privado son
2,7 MB en 11 PDF completos.

## Licencias aceptables

- **CC0, CC BY, CC BY-SA** — redistribuibles citando autoría. La atribución de
  este archivo es lo que cumple esa condición, y por eso las filas no son
  decorativas.
- **Dominio público** — verificar fecha y jurisdicción, sin confiar en que el
  sitio lo diga. Algunos escaneos reclaman derechos propios sobre una obra que
  sí es de dominio público.

## Licencias que NO entran

- **CC BY-NC / CC BY-ND** y toda variante no comercial o sin derivados. El
  proyecto es AGPL-3.0 y el repositorio es público: no puede arrastrar material
  que restrinja el uso comercial de quien lo clone. Esto no es teórico: de los
  129 libros de OpenStax, **72 son CC BY-NC-SA y sólo 46 son CC BY**. Cálculo,
  el candidato más obvio para un motor de OCR matemático, es de los excluidos.
  Hay que mirar la licencia de cada título, nunca asumirla.
- **La licencia por defecto de arXiv.** Autoriza a arXiv a distribuir el paper,
  no a terceros. Sólo sirven los que el autor subió con licencia CC explícita.
- **Cualquier cosa con copyright, recortada o no.** Quedarse con dos páginas de
  un libro de texto no crea una licencia.

## Procedimiento para agregar un archivo

1. Verificar la licencia en la fuente y anotar la URL de esa declaración.
2. Recortar a las páginas mínimas que ejerciten el perfil. Conviene
   `doc.insert_pdf(src, from_page=a, to_page=b)` sobre un documento nuevo y no
   `doc.select(...)` sobre el original: en un libro de 900 páginas, `select`
   con recolección de basura tarda minutos y `insert_pdf` tarda segundos.
3. Nombrar el archivo por perfil, no por procedencia: los tests leen el perfil,
   no el libro.
4. Agregar la fila a la tabla de procedencia.
