"""Qué se traduce y con qué contexto."""

from __future__ import annotations

from dataclasses import dataclass, field

# Tipos que nunca se traducen. No es una preferencia: traducir una fórmula la
# destruye, y traducir código lo vuelve inejecutable. Sobre el documento de
# prueba de 213 páginas son 1.371 bloques, así que dejarlos afuera además abarata.
TIPOS_NO_TRADUCIBLES = frozenset({
    "formula_display",
    "formula_inline",
    "codigo",
    "figura",
    "ruido",
    "tabla",  # llega como Markdown; traducir la estructura la rompe
})

TONOS = {
    "academico": (
        "Registro académico y preciso, como el de un artículo o un libro de texto "
        "universitario. Se conserva la terminología técnica."
    ),
    "accesible": (
        "Registro claro y didáctico, para alguien que está aprendiendo el tema. "
        "Se puede desatar una construcción muy densa en frases más simples, sin "
        "cambiar lo que dice ni simplificar el contenido."
    ),
}


@dataclass
class ContextoTraduccion:
    """Lo que el usuario decide sobre cómo se traduce su documento.

    Es la diferencia entre una traducción técnica utilizable y una literal:
    saber que es un libro de álgebra cambia cómo se traduce "ring", y el glosario
    evita que el mismo término aparezca de tres formas en 200 páginas.
    """

    idioma: str
    descripcion: str = ""
    tono: str = "academico"
    glosario: dict[str, str] = field(default_factory=dict)

    def instrucciones(self) -> str:
        """El bloque de contexto que viaja en cada llamada al modelo."""

        partes = [f"Traducí al {self.idioma}."]

        if self.descripcion.strip():
            partes.append(f"El documento es: {self.descripcion.strip()}")

        partes.append(TONOS.get(self.tono, TONOS["academico"]))

        if self.glosario:
            # El glosario va como reglas y no como sugerencia: es lo único que
            # garantiza que el término se traduzca igual en todo el documento,
            # porque cada llamada ve sólo su fragmento y no las demás.
            lineas = "\n".join(f"  {origen} → {destino}" for origen, destino in self.glosario.items())
            partes.append(
                "Respetá exactamente estas traducciones de términos, sin variar:\n" + lineas
            )

        partes.append(
            "Conservá intactos los comandos LaTeX, las fórmulas entre $…$, los "
            "identificadores y los números. No agregues ni quites contenido."
        )

        return "\n\n".join(partes)


def bloques_a_traducir(bloques: list, seleccion: dict | None = None) -> list:
    """Filtra los bloques que corresponde traducir.

    `seleccion` puede acotar por página y por tipo; vacío significa todo lo
    traducible. Traducir sólo los enunciados y dejar las demostraciones en el
    idioma original es un caso real, y sale mucho más barato que el documento
    completo.
    """

    seleccion = seleccion or {}
    paginas = seleccion.get("paginas")
    tipos = seleccion.get("tipos")

    elegidos = []
    for bloque in bloques:
        if bloque.tipo in TIPOS_NO_TRADUCIBLES:
            continue
        if paginas and bloque.pagina not in paginas:
            continue
        if tipos and bloque.tipo not in tipos:
            continue
        if not (bloque.contenido_final or bloque.texto_plano or "").strip():
            continue
        elegidos.append(bloque)

    return elegidos
