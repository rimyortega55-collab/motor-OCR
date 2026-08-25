"""Llamadas al modelo para traducir, en lotes.

El batcheo no es una optimización: con 27 903 bloques traducibles en un documento
de 213 páginas, una llamada por bloque tardaría media hora sólo esperando el
límite de 1 000 peticiones por minuto, sin contar la latencia. Se mandan varios
bloques por llamada y se piden de vuelta identificados, para poder devolver cada
traducción a su bloque.
"""

from __future__ import annotations

import json

from ocr_engine.config.settings import settings
from ocr_engine.escalation.costo_tracking import calcular_costo_usd

from .motor import ContextoTraduccion

# Cuántos bloques por llamada. Lotes grandes gastan menos en repetir el contexto,
# pero acercan la respuesta al techo de tokens. Cuando se pasa, `traducir_lote`
# parte el lote y reintenta, así que este número es un punto de partida y no un
# límite duro.
BLOQUES_POR_LOTE = 12

_cliente = None


def _obtener_cliente():
    global _cliente
    if _cliente is None:
        try:
            from anthropic import Anthropic

            _cliente = Anthropic()
        except ImportError:
            print("[TRADUCCION] SDK de Anthropic no instalado")
            return None
    return _cliente


def _texto_de_respuesta(mensaje) -> str:
    """Concatena los bloques de texto de la respuesta.

    No se puede tomar `content[0].text`: con thinking adaptativo -activado por
    omisión en Claude Opus 5- el primer bloque es un ThinkingBlock y no tiene
    atributo `text`.
    """
    return "".join(
        bloque.text for bloque in mensaje.content if getattr(bloque, "type", None) == "text"
    ).strip()


def traducir_lote(
    fragmentos: list[tuple[str, str]],
    contexto: ContextoTraduccion,
    modelo: str | None = None,
) -> tuple[dict[str, str], float, int, int]:
    """Traduce un lote de (id, texto).

    Devuelve (traducciones por id, costo en USD, tokens de entrada, de salida).
    Ante un fallo devuelve el lote vacío en vez de propagar: perder un lote deja
    esos bloques sin traducir y el resto del documento sigue, que es mejor que
    tirar abajo un trabajo de media hora por una respuesta mal formada.
    """

    if not fragmentos:
        return {}, 0.0, 0, 0

    cliente = _obtener_cliente()
    if cliente is None:
        return {}, 0.0, 0, 0

    modelo = modelo or settings.modelo_escalacion

    entrada = json.dumps(
        [{"id": identificador, "texto": texto} for identificador, texto in fragmentos],
        ensure_ascii=False,
    )

    prompt = f"""{contexto.instrucciones()}

Te paso fragmentos de un documento en JSON. Devolvé **solo** un JSON con la misma
forma y los mismos `id`, con el campo `texto` traducido. Sin explicaciones.

{entrada}"""

    try:
        # Streaming y no `create`: el SDK lo exige para max_tokens grandes, que
        # acá hacen falta porque el thinking adaptativo consume del mismo techo
        # que la respuesta. `get_final_message` devuelve el mensaje completo, así
        # que el resto del código no cambia.
        with cliente.messages.stream(
            model=modelo,
            max_tokens=32000,
            messages=[{"role": "user", "content": prompt}],
        ) as flujo:
            mensaje = flujo.get_final_message()
    except Exception as e:
        print(f"[TRADUCCION] Error en el lote: {e}")
        return {}, 0.0, 0, 0

    tokens_entrada = mensaje.usage.input_tokens
    tokens_salida = mensaje.usage.output_tokens
    costo = calcular_costo_usd(tokens_entrada, tokens_salida, modelo)

    # Respuesta cortada por el techo de tokens: el JSON queda a medias y no hay
    # nada que rescatar. Se parte el lote y se reintenta, en vez de perder los
    # veinte bloques. Pasa con lotes de prosa larga, sobre todo porque el
    # thinking adaptativo consume del mismo max_tokens que la respuesta.
    if mensaje.stop_reason == "max_tokens":
        if len(fragmentos) == 1:
            print("[TRADUCCION] Un solo fragmento no entra en la respuesta; se omite")
            return {}, costo, tokens_entrada, tokens_salida

        mitad = len(fragmentos) // 2
        print(f"[TRADUCCION] Respuesta cortada; se parte el lote de {len(fragmentos)} en dos")

        izq, c1, e1, s1 = traducir_lote(fragmentos[:mitad], contexto, modelo)
        der, c2, e2, s2 = traducir_lote(fragmentos[mitad:], contexto, modelo)

        return (
            {**izq, **der},
            costo + c1 + c2,
            tokens_entrada + e1 + e2,
            tokens_salida + s1 + s2,
        )

    respuesta = _texto_de_respuesta(mensaje)

    try:
        inicio = respuesta.index("[")
        fin = respuesta.rindex("]") + 1
        elementos = json.loads(respuesta[inicio:fin])
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[TRADUCCION] Respuesta no interpretable ({len(fragmentos)} bloques): {e}")
        return {}, costo, tokens_entrada, tokens_salida

    traducciones = {}
    for elemento in elementos:
        identificador = elemento.get("id")
        texto = elemento.get("texto")
        if identificador and isinstance(texto, str):
            traducciones[str(identificador)] = texto

    return traducciones, costo, tokens_entrada, tokens_salida


def armar_lotes(bloques: list, contenido_de) -> list[list[tuple[str, str]]]:
    """Parte los bloques en lotes de tamaño manejable."""

    lotes = []
    for inicio in range(0, len(bloques), BLOQUES_POR_LOTE):
        trozo = bloques[inicio : inicio + BLOQUES_POR_LOTE]
        lotes.append([(str(b.id), contenido_de(b)) for b in trozo])
    return lotes
