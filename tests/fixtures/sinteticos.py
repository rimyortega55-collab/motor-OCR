"""PDF sinteticos generados en tiempo de prueba (complemento del corpus real).

Estos PDF no se versionan: se versiona el generador. Un binario de una pagina
rasterizada pesa varios MB, mientras que la funcion que lo produce son treinta
lineas legibles en un diff, y ademas es determinista y parametrizable.

Que cubren y que no
-------------------
Sirven para los casos de borde y los contratos: un PDF sin paginas, una pagina
sin capa de texto, una pagina con fuente matematica y otra sin ella, un
documento con perfiles distintos en paginas contiguas, una pagina a dos
columnas con el orden de lectura correcto conocido de antemano. Es lo que hace
falta para fijar el comportamiento de triage, zonificacion y orden de lectura
sin depender de ningun archivo externo.

No sirven para medir fidelidad. Una pagina nacida de PyMuPDF tiene capa de
texto perfecta y tipografia limpia; `pagina_escaneada` rasteriza, pero
rasterizar texto nitido no produce el ruido, la inclinacion ni la compresion
de un escaneo real. Para eso esta el corpus con licencia redistribuible de
`tests/fixtures/` (ver MANIFEST.md).

Sobre la fuente `symb`
----------------------
`detectar_fuentes_matematicas` busca nombres tipo CMMI, CMSY o Symbol en los
spans de la pagina. Embeber Computer Modern exigiria versionar un .ttf; la
Symbol de las base-14 ya viaja en PyMuPDF, esta en la lista de fuentes
conocidas del detector y produce la misma senal, asi que es lo que se usa para
simular notacion matematica nativa.
"""

from __future__ import annotations

import pymupdf

# Una carta en puntos PostScript: el tamano que asume PyMuPDF por defecto y el
# de los PDF del corpus real, para que los umbrales de layout no cambien de
# significado entre un fixture y otro.
ANCHO, ALTO = 612.0, 792.0

_PROSA = (
    "El metodo de los multiplicadores de Lagrange permite hallar los extremos "
    "de una funcion sujeta a restricciones sin despejar ninguna variable."
)


def _pagina_en_blanco(doc: pymupdf.Document) -> pymupdf.Page:
    return doc.new_page(width=ANCHO, height=ALTO)


def _escribir_prosa(pagina: pymupdf.Page, lineas: int, y0: float = 90.0) -> float:
    """Escribe `lineas` renglones de prosa y devuelve la y donde quedo."""
    y = y0
    for i in range(lineas):
        pagina.insert_text((72, y), f"{i + 1}. {_PROSA}", fontname="helv", fontsize=10)
        y += 16
    return y


def pdf_vacio() -> bytes:
    """Un PDF valido con cero paginas. El caso de borde que nadie prueba.

    Se arma a mano porque PyMuPDF se niega a guardar un documento sin paginas
    ("cannot save with zero pages"), asi que no hay forma de producirlo con la
    API normal. Son un catalogo, un arbol de paginas vacio y una tabla xref
    con los offsets reales: lo minimo que un lector acepta como PDF.
    """
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [] /Count 0 >>",
    ]
    salida = bytearray(b"%PDF-1.7\n")
    offsets = []
    for numero, objeto in enumerate(objetos, 1):
        offsets.append(len(salida))
        salida += b"%d 0 obj\n" % numero + objeto + b"\nendobj\n"

    # La tabla xref lleva el offset absoluto de cada objeto, por eso se arma
    # despues de escribirlos y no antes: si los offsets no coinciden byte a
    # byte, el lector entra en modo reparacion y el fixture deja de probar lo
    # que dice probar.
    inicio_xref = len(salida)
    salida += b"xref\n0 %d\n" % (len(objetos) + 1)
    salida += b"0000000000 65535 f \n"
    for offset in offsets:
        salida += b"%010d 00000 n \n" % offset
    salida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1,
        inicio_xref,
    )
    return bytes(salida)


def pdf_texto(paginas: int = 1, lineas: int = 30) -> bytes:
    """Prosa narrativa, capa de texto, sin una sola fuente matematica.

    Es el caso barato del motor: nativo-digital y sin formulas, la unica
    combinacion que se salta el OCR por completo.
    """
    doc = pymupdf.open()
    for _ in range(paginas):
        _escribir_prosa(_pagina_en_blanco(doc), lineas)
    datos = doc.tobytes()
    doc.close()
    return datos


def pdf_con_matematica(paginas: int = 1) -> bytes:
    """Prosa mas un renglon en Symbol, que el detector lee como notacion."""
    doc = pymupdf.open()
    for _ in range(paginas):
        pagina = _pagina_en_blanco(doc)
        y = _escribir_prosa(pagina, 12)
        pagina.insert_text((72, y + 20), "abgdez", fontname="symb", fontsize=12)
        _escribir_prosa(pagina, 8, y0=y + 50)
    datos = doc.tobytes()
    doc.close()
    return datos


def pdf_escaneado(paginas: int = 1, dpi: int = 150) -> bytes:
    """Paginas sin capa de texto: la prosa se rasteriza y se pega como imagen.

    Es un escaneo simulado, no uno real -no tiene ruido ni inclinacion-, pero
    para `detectar_origen` es indistinguible de uno: no hay texto que extraer.
    """
    origen = pymupdf.open()
    _escribir_prosa(_pagina_en_blanco(origen), 30)
    pixmap = origen[0].get_pixmap(dpi=dpi)
    origen.close()

    doc = pymupdf.open()
    for _ in range(paginas):
        pagina = _pagina_en_blanco(doc)
        pagina.insert_image(pagina.rect, pixmap=pixmap)
    datos = doc.tobytes()
    doc.close()
    return datos


def pdf_mixto() -> bytes:
    """Cuatro paginas: dos de prosa, una con matematica, una escaneada.

    Existe para la zonificacion, que agrupa paginas contiguas de perfil
    parecido: con un documento de perfil uniforme no se distingue una
    implementacion correcta de una que devuelve siempre una sola zona.
    """
    doc = pymupdf.open()
    doc.insert_pdf(pymupdf.open("pdf", pdf_texto(paginas=2)))
    doc.insert_pdf(pymupdf.open("pdf", pdf_con_matematica(paginas=1)))
    doc.insert_pdf(pymupdf.open("pdf", pdf_escaneado(paginas=1)))
    datos = doc.tobytes()
    doc.close()
    return datos


def pdf_dos_columnas(lineas_por_columna: int = 24) -> bytes:
    """Una pagina a dos columnas, con el orden de lectura correcto conocido.

    El perfil de dos columnas es el unico de los cinco que se genera y no se
    toma del corpus real, y es deliberado: el orden de lectura es un problema
    geometrico, no de fidelidad. Lo que hay que verificar es que el motor lea
    la columna izquierda entera antes de la derecha en vez de ir renglon por
    renglon cruzando la pagina, y para eso conviene un documento donde la
    respuesta correcta este escrita de antemano.

    Cada renglon empieza con su numero de orden, asi que la secuencia correcta
    es simplemente 1..2n: si el motor cruza columnas, los numeros salen
    intercalados y el test lo detecta sin ambiguedad.
    """
    doc = pymupdf.open()
    pagina = _pagina_en_blanco(doc)

    margen = 54.0
    canaleta = 24.0
    ancho_columna = (ANCHO - 2 * margen - canaleta) / 2
    x_izquierda = margen
    x_derecha = margen + ancho_columna + canaleta

    numero = 1
    for x in (x_izquierda, x_derecha):
        y = 90.0
        for _ in range(lineas_por_columna):
            pagina.insert_text((x, y), f"{numero:03d} renglon de la columna", fontname="helv", fontsize=9)
            numero += 1
            y += 14

    datos = doc.tobytes()
    doc.close()
    return datos
