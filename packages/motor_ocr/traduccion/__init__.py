"""Traducción de documentos ya convertidos.

Se traduce **después** de procesar y no dentro del pipeline, por tres razones que
se refuerzan: el contenido ya tiene aplicadas las correcciones humanas, se paga
sólo cuando alguien la pide, y de un mismo procesamiento salen todos los idiomas
que hagan falta.

Y se traduce **bloque a bloque**, no sobre el archivo ya renderizado. Si se le
pasara el `.tex` terminado, el modelo traduciría dentro de `\\begin{equation}` y
rompería el LaTeX. Es la misma distinción que ya hace el exportador entre prosa y
verbatim: las dos preguntan si esto es lenguaje natural.
"""

from .cliente import traducir_lote
from .glosario import extraer_terminos
from .motor import TIPOS_NO_TRADUCIBLES, ContextoTraduccion, bloques_a_traducir

__all__ = [
    "traducir_lote",
    "extraer_terminos",
    "ContextoTraduccion",
    "bloques_a_traducir",
    "TIPOS_NO_TRADUCIBLES",
]
