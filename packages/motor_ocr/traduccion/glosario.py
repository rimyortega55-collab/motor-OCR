"""Extracción de los términos técnicos que conviene fijar antes de traducir.

Cada llamada al modelo ve sólo su lote, así que por sí sola no puede ser
consistente: "eigenvalue" puede salir como autovalor en la página 3, valor propio
en la 40 y eigenvalor en la 150. El glosario es lo único que lo evita, y por eso
se arma **antes** de traducir y viaja en todas las llamadas.

El motor propone y el usuario decide: se extraen los candidatos por frecuencia y
la interfaz los muestra para que los corrija. Proponer con un modelo sería más
fino, pero cuesta una llamada extra sobre el documento entero para algo que la
frecuencia resuelve bastante bien.
"""

from __future__ import annotations

import re
from collections import Counter

from .motor import TIPOS_NO_TRADUCIBLES

# Palabras que aparecen mucho y no son términos técnicos. No pretende ser
# exhaustivo: alcanza con sacar el ruido de arriba de la lista.
_VACIAS = frozenset("""
the of and to in a is that for as we be by with are this it on or an from can
which such all if then let we have has been not there each any one two both
el la los las de del que en un una es por con para se su sus como al lo más
si no ya sea son este esta estos estas cuando donde entonces sobre entre
""".split())

# Un término técnico rara vez es de dos letras, y las de más de 30 suelen ser
# basura del OCR pegada.
_PALABRA = re.compile(r"\b[A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ-]{2,29}\b")


def extraer_terminos(bloques: list, contenido_de, cuantos: int = 40) -> list[dict]:
    """Devuelve los candidatos a glosario, del más frecuente al menos.

    Se ignoran los bloques que no se traducen: un identificador que aparece
    cincuenta veces dentro de bloques de código no es un término del documento.
    """

    frecuencias: Counter[str] = Counter()
    formas: dict[str, str] = {}

    for bloque in bloques:
        if bloque.tipo in TIPOS_NO_TRADUCIBLES:
            continue

        texto = contenido_de(bloque) or ""
        for palabra in _PALABRA.findall(texto):
            clave = palabra.lower()
            if clave in _VACIAS:
                continue
            frecuencias[clave] += 1
            # Se conserva la primera forma vista, que suele traer la mayúscula
            # correcta de un nombre propio o de un término definido.
            formas.setdefault(clave, palabra)

    # Un término que aparece una o dos veces no genera inconsistencia: fijarlo
    # sólo hace más largo el prompt de cada llamada.
    candidatos = [(clave, n) for clave, n in frecuencias.most_common() if n >= 3]

    return [
        {"termino": formas[clave], "apariciones": n, "traduccion": ""}
        for clave, n in candidatos[:cuantos]
    ]
