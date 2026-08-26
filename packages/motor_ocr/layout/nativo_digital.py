"""Segmentación de páginas nativo-digitales por estructura del PDF.

Los bloques se derivan directamente de la estructura que ya trae el PDF
—bloque, línea y span— en vez de reagrupar los spans por cuenta propia: es más
preciso y más barato que la segmentación visual, porque no hay pérdida de
información al no pasar por una imagen rasterizada.

La versión anterior recorría los spans en plano y abría un bloque nuevo cada
vez que cambiaba el nombre de la fuente o cada vez que el centro vertical se
alejaba más de 15 pt del centro de la *primera* línea del bloque. Las dos
reglas rompían el texto:

- Con interlineado de 12 pt, el umbral fijo contra la primera línea cortaba
  todo párrafo en trozos de dos renglones.
- Una palabra en cursiva en medio de una frase cambia de fuente, así que
  partía la frase en tres bloques que después el orden de lectura barajaba
  ("Mathematical Writing" salía antes que la frase que la introduce).

Acá se conserva la jerarquía del PDF: las líneas que comparten renglón se unen
en una fila, las filas se agrupan en párrafos por interlineado y sangría, y
recién ahí se arma el Bloque.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from uuid import uuid4

import pymupdf as fitz

from motor_ocr.modelos import (
    Bloque,
    Contenido,
    Documento,
    Layout,
    OrigenContenido,
    Provenance,
    SegmentoCrudo,
    TipoBloque,
)
from motor_ocr.triage.deteccion_fuentes import FUENTES_MATEMATICAS_CONOCIDAS

from .bbox import normalizar_bbox
from .taxonomia import clasificar_bloque

# Los nombres PostScript no son un estándar: el mismo peso aparece como
# "Times-Bold", "AdvGTIMES-B" o "ABCDEF+Arial,BoldMT". Los bits de `flags` de
# PyMuPDF tampoco son confiables (este corpus los trae en 4 —serif— para todo),
# así que se combinan las dos señales.
_NEGRITA = re.compile(r"(bold|black|heavy|semibold|demi|[-,]b$|[-,]bd$)", re.I)
_CURSIVA = re.compile(r"(italic|oblique|[-,]i$|[-,]it$)", re.I)
_FLAG_CURSIVA = 1 << 1
_FLAG_NEGRITA = 1 << 4

# Glifos que el PDF no sabe mapear a Unicode llegan como caracteres de control.
# En el .md se ven como basura y no aportan nada.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ESPACIOS = re.compile(r"\s+")

# Puntos guía de un índice: ". . . . . . 13". Se normalizan a una elipsis y la
# fila se trata como una entrada independiente.
_PUNTOS_GUIA = re.compile(r"\.(?:\s*\.){3,}")

# Marca de ítem al principio de un renglón: viñeta o numeración. Las iniciales
# de un nombre ("F. Vivaldi") quedan afuera a propósito: admitir una sola letra
# convertiría en lista cualquier línea de créditos.
_MARCA_ITEM = re.compile(r"^(?:[•·▪‣◦∙]|\d{1,3}[.)]\s)")

# Sangría (en puntos) a partir de la cual una fila se lee como primera línea de
# un párrafo nuevo y no como continuación de la anterior.
_SANGRIA_PARRAFO = 3.0
# Un salto vertical mayor que este múltiplo del interlineado separa párrafos.
_FACTOR_SALTO = 1.45
# Diferencia de cuerpo que ya no es la misma corrida de texto.
_SALTO_CUERPO = 0.6
# Franja superior/inferior donde viven los folios corrientes.
_MARGEN_RUIDO = 0.09

# Un span más chico que este factor del cuerpo de línea, y desplazado
# verticalmente respecto a él, se lee como superíndice o subíndice aunque
# comparta la fuente del texto corrido (p.ej. un exponente en Times-Roman
# reducido, no en una fuente matemática dedicada).
_UMBRAL_TAMANO_INDICE = 0.9
_UMBRAL_OFFSET_INDICE = 0.12

_Tramo = tuple[bool, str, "tuple[float, float, float, float] | None"]


@dataclass
class _Fila:
    """Un renglón visual: una o más `lines` del PDF que comparten altura."""

    texto: str
    x0: float
    y0: float
    x1: float
    y1: float
    tamano: float
    negrita: bool
    cursiva: bool
    # Tramos (es_formula, texto, bbox_pdf_o_None) de la línea en orden de
    # lectura. bbox sólo se completa para tramos de fórmula: es lo que permite
    # recortar la región exacta de la página renderizada en Capa 3.
    tramos: list[_Tramo] = field(default_factory=list)

    @property
    def alto(self) -> float:
        return max(self.y1 - self.y0, 1.0)


def construir_vocabulario(ruta_pdf: str) -> set[str]:
    """Palabras completas del documento, para decidir guiones de corte.

    Al unir renglones hay que distinguir "resour-/ces" (partición tipográfica,
    el guion se va) de "second-/year" (guion del autor, se queda). Sin
    diccionario la única señal barata es el propio documento: si las dos
    mitades aparecen sueltas en alguna otra parte del texto, el guion es real.

    Se descartan las dos mitades de cada corte: la última palabra de una línea
    terminada en guion y la primera de la línea siguiente. Descartando sólo una,
    "com-/mented" dejaría "mented" en el vocabulario y esa misma entrada haría
    pasar el corte por un guion legítimo la próxima vez.
    """

    palabra = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
    vocabulario: set[str] = set()

    documento = fitz.open(ruta_pdf)
    try:
        for pagina in documento:
            venia_cortada = False
            for linea in pagina.get_text().splitlines():
                encontradas = palabra.findall(linea)
                corta = linea.rstrip().endswith(("-", "­"))

                if venia_cortada:
                    encontradas = encontradas[1:]
                if corta:
                    encontradas = encontradas[:-1]

                vocabulario.update(p.lower() for p in encontradas)
                if linea.strip():
                    venia_cortada = corta
    finally:
        documento.close()

    return vocabulario


def segmentar_nativo_digital(
    documento: Documento,
    ruta_pdf: str,
    pagina: int,
    vocabulario: set[str] | None = None,
) -> list[Bloque]:
    """Segmenta una página nativo-digital respetando la estructura del PDF."""

    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        doc.close()
        return []

    page = doc[pagina]
    text_dict = page.get_text("dict")
    # PyMuPDF da los bbox en puntos PDF (72 dpi). Se guardan normalizados a la
    # caja de la página para que el bbox de un bloque signifique lo mismo venga
    # de acá o del camino escaneado, donde sale en píxeles del render.
    caja = (page.rect.width or 1.0, page.rect.height or 1.0)
    doc.close()

    bloques_pdf: list[list[_Fila]] = []
    for bloque_pdf in text_dict.get("blocks", []):
        if bloque_pdf.get("type") != 0:  # only text blocks
            continue
        filas = _filas_de_bloque(bloque_pdf)
        if filas:
            bloques_pdf.append(filas)

    if not bloques_pdf:
        return []

    cuerpo = _tamano_cuerpo([f for filas in bloques_pdf for f in filas])
    alto_pagina = caja[1]

    bloques: list[Bloque] = []
    for filas in bloques_pdf:
        for parrafo in _partir_en_parrafos(filas):
            bloque = _crear_bloque(
                caja,
                documento,
                pagina,
                parrafo,
                len(bloques),
                cuerpo,
                alto_pagina,
                vocabulario or set(),
            )
            if bloque is not None:
                bloques.append(bloque)

    return bloques


def _filas_de_bloque(bloque_pdf: dict) -> list[_Fila]:
    """Convierte las `lines` de un bloque del PDF en renglones visuales.

    Un índice general pone el número de capítulo, el título y la página como
    tres `lines` distintas a la misma altura. Tratarlas por separado desarma la
    entrada; agruparlas por renglón la deja legible.
    """

    lineas: list[_Fila] = []
    for linea in bloque_pdf.get("lines", []):
        fila = _fila_de_linea(linea)
        if fila is not None:
            lineas.append(fila)

    if not lineas:
        return []

    lineas.sort(key=lambda f: (f.y0, f.x0))

    filas: list[_Fila] = []
    grupo: list[_Fila] = [lineas[0]]
    for linea in lineas[1:]:
        anterior = grupo[-1]
        if abs(linea.y0 - anterior.y0) <= anterior.alto * 0.5:
            grupo.append(linea)
        else:
            filas.append(_fusionar_renglon(grupo))
            grupo = [linea]
    filas.append(_fusionar_renglon(grupo))

    return filas


def _fila_de_linea(linea: dict) -> _Fila | None:
    spans = linea.get("spans", [])
    if not spans:
        return None

    # Los spans se concatenan tal cual: en muchos PDF cada espacio es su propio
    # span, así que unirlos con " " duplica separaciones y mete un espacio
    # después del guion de corte ("second- year").
    texto = _limpiar("".join(s.get("text", "") for s in spans))
    if not texto:
        return None

    x0, y0, x1, y1 = linea.get("bbox", (0.0, 0.0, 0.0, 0.0))

    return _Fila(
        texto=texto,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        tamano=max((s.get("size", 0.0) for s in spans), default=0.0),
        negrita=_peso_dominante(spans, _es_negrita),
        cursiva=_peso_dominante(spans, _es_cursiva),
        tramos=_tramos_de_spans(spans, (x0, y0, x1, y1)),
    )


def _es_fuente_matematica(font_name: str) -> bool:
    nombre = _subfuente(font_name).upper()
    return any(m.upper() in nombre for m in FUENTES_MATEMATICAS_CONOCIDAS)


def _tamano_dominante(spans: list[dict]) -> float:
    """Tamaño que cubre más caracteres en la línea: el cuerpo de ese renglón."""
    conteo: dict[float, int] = {}
    for s in spans:
        clave = round(s.get("size", 0.0), 1)
        conteo[clave] = conteo.get(clave, 0) + len(s.get("text", ""))
    if not conteo:
        return 0.0
    return max(conteo.items(), key=lambda par: par[1])[0]


def _centro_vertical_dominante(spans: list[dict], tamano_linea: float) -> float:
    """Centro vertical de los spans que están al tamaño dominante de la línea.

    Sirve de línea base para detectar superíndices/subíndices: un span que se
    aparta de este centro más de lo normal, y además es más chico, está
    elevado o hundido respecto al renglón.
    """
    centros = [
        (s["bbox"][1] + s["bbox"][3]) / 2
        for s in spans
        if abs(s.get("size", 0.0) - tamano_linea) < 0.05 and "bbox" in s
    ]
    if not centros:
        centros = [(s["bbox"][1] + s["bbox"][3]) / 2 for s in spans if "bbox" in s]
    return sum(centros) / len(centros) if centros else 0.0


def _es_span_matematico(span: dict, tamano_linea: float, centro_linea: float) -> bool:
    """Señal geométrica de que un span es matemática, no texto corrido.

    Dos casos, la misma idea que triage/deteccion_fuentes.py: una fuente
    matemática conocida (símbolos, operadores extendidos), o un span visible-
    mente más chico y desplazado de la línea base (exponente o subíndice),
    aunque comparta la fuente del texto — un exponente numérico normalmente
    usa la misma fuente que el resto, sólo que reducida y elevada.
    """
    if _es_fuente_matematica(span.get("font", "")):
        return True

    if tamano_linea <= 0 or "bbox" not in span:
        return False

    tam = span.get("size", 0.0)
    if tam <= 0 or tam >= tamano_linea * _UMBRAL_TAMANO_INDICE:
        return False

    centro = (span["bbox"][1] + span["bbox"][3]) / 2
    return abs(centro - centro_linea) > tamano_linea * _UMBRAL_OFFSET_INDICE


def _tramos_de_spans(
    spans: list[dict], bbox_linea: tuple[float, float, float, float]
) -> list[_Tramo]:
    """Agrupa los spans de una línea en tramos consecutivos de texto/fórmula."""

    if not spans:
        return []

    tamano_linea = _tamano_dominante(spans)
    centro_linea = _centro_vertical_dominante(spans, tamano_linea)

    grupos: list[tuple[bool, list[dict]]] = []
    for span in spans:
        es_formula = _es_span_matematico(span, tamano_linea, centro_linea)
        if grupos and grupos[-1][0] == es_formula:
            grupos[-1][1].append(span)
        else:
            grupos.append((es_formula, [span]))

    lx0, ly0, lx1, ly1 = bbox_linea
    # Medio carácter de margen a cada lado: un exponente o subíndice recortado
    # solo, sin la base que lo precede, no le da a pix2tex ninguna pista visual
    # de que va elevado o hundido — necesita ver el carácter de referencia.
    margen = max(tamano_linea * 0.5, 1.0)

    tramos: list[_Tramo] = []
    for es_formula, grupo in grupos:
        texto = _limpiar("".join(s.get("text", "") for s in grupo))
        if not texto:
            continue
        bbox = None
        if es_formula:
            x0 = max(lx0, min(s["bbox"][0] for s in grupo) - margen)
            x1 = min(lx1, max(s["bbox"][2] for s in grupo) + margen)
            # Alto completo del renglón, no sólo el del tramo: así la base a
            # tamaño normal y el índice elevado/hundido quedan ambos visibles
            # en el recorte, con su posición relativa intacta.
            bbox = (x0, ly0, x1, ly1)
        tramos.append((es_formula, texto, bbox))

    return tramos


def _fusionar_renglon(grupo: list[_Fila]) -> _Fila:
    if len(grupo) == 1:
        return grupo[0]

    grupo = sorted(grupo, key=lambda f: f.x0)
    largo = sum(len(f.texto) for f in grupo) or 1

    return _Fila(
        texto=_limpiar(" ".join(f.texto for f in grupo)),
        x0=min(f.x0 for f in grupo),
        y0=min(f.y0 for f in grupo),
        x1=max(f.x1 for f in grupo),
        y1=max(f.y1 for f in grupo),
        tamano=max(f.tamano for f in grupo),
        negrita=sum(len(f.texto) for f in grupo if f.negrita) * 2 >= largo,
        cursiva=sum(len(f.texto) for f in grupo if f.cursiva) * 2 >= largo,
        tramos=[t for f in grupo for t in f.tramos],
    )


def _limpiar(texto: str) -> str:
    return _ESPACIOS.sub(" ", _CONTROL.sub("", texto)).strip()


def _peso_dominante(spans: list[dict], predicado) -> bool:
    """True si el predicado cubre la mayoría de los caracteres de la línea."""
    total = sum(len(s.get("text", "")) for s in spans)
    if not total:
        return False
    marcados = sum(len(s.get("text", "")) for s in spans if predicado(s))
    return marcados * 2 >= total


def _es_negrita(span: dict) -> bool:
    if span.get("flags", 0) & _FLAG_NEGRITA:
        return True
    return bool(_NEGRITA.search(_subfuente(span.get("font", ""))))


def _es_cursiva(span: dict) -> bool:
    if span.get("flags", 0) & _FLAG_CURSIVA:
        return True
    return bool(_CURSIVA.search(_subfuente(span.get("font", ""))))


def _subfuente(nombre: str) -> str:
    """Quita el prefijo de subconjunto ("ABCDEF+Arial,Bold" -> "Arial,Bold")."""
    return nombre.split("+", 1)[-1]


def _tamano_cuerpo(filas: list[_Fila]) -> float:
    """Cuerpo de texto de la página: el tamaño que cubre más caracteres.

    Es la referencia contra la que se mide si algo es un título (más grande) o
    un folio corriente (más chico).
    """
    conteo: dict[float, int] = {}
    for fila in filas:
        clave = round(fila.tamano, 1)
        conteo[clave] = conteo.get(clave, 0) + len(fila.texto)

    if not conteo:
        return 10.0
    return max(conteo.items(), key=lambda par: par[1])[0] or 10.0


def _margen_modal(filas: list[_Fila]) -> float:
    """Borde izquierdo que más renglones comparten: el margen del cuerpo."""
    conteo: dict[float, int] = {}
    for fila in filas:
        clave = round(fila.x0, 1)
        conteo[clave] = conteo.get(clave, 0) + 1

    # A igualdad de renglones gana el margen más a la izquierda, que es el del
    # cuerpo del texto y no el de una sangría.
    return max(conteo.items(), key=lambda par: (par[1], -par[0]))[0]


def _partir_en_parrafos(filas: list[_Fila]) -> list[list[_Fila]]:
    """Corta un bloque del PDF donde empieza un párrafo nuevo.

    Un bloque del PDF puede contener varios párrafos. Las señales son las
    tipográficas de siempre: un salto vertical mayor que el interlineado, la
    sangría de primera línea, la marca de un ítem, y un cambio de cuerpo.

    La sangría se mide contra el margen *modal* del bloque y no contra el
    mínimo. En una lista con sangría francesa la marca del ítem sobresale a la
    izquierda, así que el mínimo es el borde de la marca y todas las líneas de
    continuación parecen sangradas: medir contra él parte cada ítem en tantos
    párrafos como renglones tenga.
    """

    if len(filas) <= 1:
        return [filas]

    saltos = [b.y0 - a.y0 for a, b in zip(filas, filas[1:]) if b.y0 - a.y0 > 0]
    interlineado = statistics.median(saltos) if saltos else filas[0].alto
    margen = _margen_modal(filas)

    grupos: list[list[_Fila]] = [[filas[0]]]
    for anterior, fila in zip(filas, filas[1:]):
        nuevo = (
            (fila.y0 - anterior.y0) > interlineado * _FACTOR_SALTO
            or fila.x0 > margen + _SANGRIA_PARRAFO
            # Una viñeta o un "3." abren ítem sin depender de la geometría, que
            # en una lista con sangría francesa no distingue nada.
            or bool(_MARCA_ITEM.match(fila.texto))
            or abs(fila.tamano - anterior.tamano) > _SALTO_CUERPO
            # Cada entrada de un índice general es una unidad propia: unirlas
            # produce un párrafo ilegible de cientos de puntos suspensivos.
            or bool(_PUNTOS_GUIA.search(fila.texto))
            or bool(_PUNTOS_GUIA.search(anterior.texto))
        )
        if nuevo:
            grupos.append([fila])
        else:
            grupos[-1].append(fila)

    return grupos


def _unir_filas(filas: list[_Fila], vocabulario: set[str]) -> str:
    """Une los renglones de un párrafo resolviendo los guiones de corte."""

    texto = ""
    for fila in filas:
        if not texto:
            texto = fila.texto
        elif texto.endswith("\u00ad"):
            texto = texto[:-1] + fila.texto
        elif texto.endswith("-"):
            texto = _unir_por_guion(texto, fila.texto, vocabulario)
        else:
            texto = f"{texto} {fila.texto}"

    return texto


def _unir_por_guion(izquierda: str, derecha: str, vocabulario: set[str]) -> str:
    tronco = izquierda[:-1]
    fin = re.search(r"[^\W\d_]+$", tronco, re.UNICODE)
    inicio = re.match(r"[^\W\d_]+", derecha, re.UNICODE)

    # "pp. 3-" + "4", o cualquier cosa que no sean dos mitades de palabra: el
    # guion no es de partición y se conserva tal cual.
    if not fin or not inicio:
        return izquierda + derecha

    if fin.group().lower() in vocabulario and inicio.group().lower() in vocabulario:
        return izquierda + derecha

    return tronco + derecha


def _segmentos_de_filas(
    filas: list[_Fila], vocabulario: set[str], caja: tuple[float, float]
) -> list[SegmentoCrudo]:
    """Reconstruye la secuencia [texto, fórmula, texto, ...] de un párrafo.

    Sigue el mismo criterio de unión que `_unir_filas` (guion de partición vs.
    guion de autor) pero sin aplanar todo a un string: una fórmula detectada
    por fuente/tamaño de span conserva su bbox de página para que Capa 3 la
    recorte y la mande a pix2tex. Derivar esto del `texto_plano` ya unido no
    alcanza — una vez que el exponente se pegó al número base no queda
    ninguna marca de dónde cortar.
    """

    segmentos: list[SegmentoCrudo] = []

    for idx, fila in enumerate(filas):
        tramos = fila.tramos or [(False, fila.texto, None)]
        for i, (es_formula, texto, bbox_pdf) in enumerate(tramos):
            if not texto:
                continue

            tipo = "formula" if es_formula else "texto"
            mismo_renglon = not (i == 0 and idx > 0)

            if mismo_renglon and segmentos and segmentos[-1].tipo == "texto" == tipo:
                segmentos[-1] = SegmentoCrudo(tipo="texto", texto=segmentos[-1].texto + texto)
                continue

            if not mismo_renglon and segmentos and segmentos[-1].tipo == "texto" == tipo:
                anterior = segmentos[-1].texto
                if anterior.endswith("­"):
                    fusion = anterior[:-1] + texto
                elif anterior.endswith("-"):
                    fusion = _unir_por_guion(anterior, texto, vocabulario)
                else:
                    fusion = f"{anterior} {texto}"
                segmentos[-1] = SegmentoCrudo(tipo="texto", texto=fusion)
                continue

            bbox_norm = normalizar_bbox(bbox_pdf, caja) if bbox_pdf else None
            segmentos.append(SegmentoCrudo(tipo=tipo, texto=texto, bbox=bbox_norm))

    return segmentos


def _es_ruido(fila: _Fila, cuerpo: float, alto_pagina: float) -> bool:
    """Folio corriente o número de página.

    Van solos en el margen superior o inferior, en un cuerpo menor que el del
    texto. Se conservan como bloques —el visor de revisión los dibuja— pero la
    exportación los omite: en el .md no son contenido, son ruido de imprenta.
    """
    if alto_pagina <= 0 or len(fila.texto) > 80:
        return False
    if fila.tamano > cuerpo * 0.95:
        return False
    return (
        fila.y1 <= alto_pagina * _MARGEN_RUIDO
        or fila.y0 >= alto_pagina * (1 - _MARGEN_RUIDO)
    )


def _crear_bloque(
    caja: tuple[float, float],
    documento: Documento,
    pagina: int,
    filas: list[_Fila],
    orden_lectura: int,
    cuerpo: float,
    alto_pagina: float,
    vocabulario: set[str],
) -> Bloque | None:
    """Crea un Bloque a partir de las filas de un párrafo."""

    texto = _unir_filas(filas, vocabulario)
    if not texto:
        return None

    x0 = min(f.x0 for f in filas)
    y0 = min(f.y0 for f in filas)
    x1 = max(f.x1 for f in filas)
    y1 = max(f.y1 for f in filas)

    escala = (max(f.tamano for f in filas) / cuerpo) if cuerpo else 1.0

    if len(filas) == 1 and _es_ruido(filas[0], cuerpo, alto_pagina):
        tipo_bloque = TipoBloque.RUIDO
    elif _PUNTOS_GUIA.search(texto):
        # Entrada de índice: los puntos guía se normalizan a una elipsis para
        # que el .md no arrastre cuarenta puntos por línea.
        texto = _limpiar(_PUNTOS_GUIA.sub(" … ", texto))
        tipo_bloque = TipoBloque.LISTA
    else:
        tipo_bloque = clasificar_bloque(
            texto,
            filas[0].negrita,
            escala_fuente=escala,
            filas=len(filas),
        )

    segmentos = (
        _segmentos_de_filas(filas, vocabulario, caja)
        if tipo_bloque not in (TipoBloque.RUIDO, TipoBloque.LISTA)
        else []
    )
    if not any(s.tipo == "formula" for s in segmentos):
        segmentos = []

    return Bloque(
        id=uuid4(),
        documento_id=documento.documento_id,
        pagina=pagina,
        tipo=tipo_bloque,
        layout=Layout(
            bbox=normalizar_bbox((x0, y0, x1, y1), caja),
            orden_lectura=orden_lectura,
            confianza_layout=0.95,  # high confidence for native-digital
        ),
        origen_contenido=OrigenContenido.TEXTO_NATIVO,
        contenido=Contenido(texto_plano=texto),
        segmentos_capa2=segmentos,
        provenance=Provenance(creado_por_capa="segmentation_nativo_digital"),
    )
