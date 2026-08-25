"""Worker de traducción.

Mismo patrón que `trabajos.py`: un hilo del proceso, con el avance en la base
para que la interfaz lo sondee. Traducir un documento grande son minutos, así que
el request no puede esperarlo.

El costo se registra lote a lote y no al final: si el trabajo se corta a la mitad,
lo gastado hasta ahí ya está atribuido y el usuario no recibe una factura que no
coincide con lo que consumió.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from ocr_engine.config.settings import settings
from ocr_engine.persistence import (
    BloqueAlmacenado,
    CostoRegistrado,
    TraduccionBloque,
    TraduccionDocumento,
    session_scope,
)
from ocr_engine.translation import ContextoTraduccion, bloques_a_traducir, traducir_lote
from ocr_engine.translation.cliente import armar_lotes


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def contenido_de(bloque) -> str:
    """El texto que vale para traducir, con la corrección humana por delante."""
    return bloque.contenido_final or bloque.texto_plano or ""


def encolar_traduccion(traduccion_id: str) -> None:
    """Arranca la traducción en segundo plano y vuelve enseguida."""

    hilo = threading.Thread(
        target=_traducir,
        args=(traduccion_id,),
        name=f"trad-{traduccion_id[:8]}",
        daemon=True,
    )
    hilo.start()


def _traducir(traduccion_id: str) -> None:
    with session_scope() as sesion:
        pedido = sesion.get(TraduccionDocumento, traduccion_id)
        if pedido is None:
            return

        documento_id = pedido.documento_id
        usuario_id = pedido.documento.usuario_id
        contexto = ContextoTraduccion(
            idioma=pedido.idioma,
            descripcion=pedido.descripcion or "",
            tono=pedido.tono,
            glosario=pedido.glosario or {},
        )
        seleccion = pedido.seleccion or {}
        pedido.estado = "traduciendo"

    try:
        with session_scope() as sesion:
            bloques = (
                sesion.query(BloqueAlmacenado)
                .filter(BloqueAlmacenado.documento_id == documento_id)
                .order_by(BloqueAlmacenado.pagina, BloqueAlmacenado.orden_lectura)
                .all()
            )
            elegidos = bloques_a_traducir(bloques, seleccion)
            # Se materializan acá: la sesión se cierra al salir del bloque y
            # después no se pueden leer los atributos.
            lotes = armar_lotes(elegidos, contenido_de)

        with session_scope() as sesion:
            sesion.get(TraduccionDocumento, traduccion_id).bloques_totales = len(elegidos)

        hechos = 0
        gastado = 0.0
        tope = settings.tope_gasto_documento_usd

        for lote in lotes:
            if tope and gastado >= tope:
                # Se corta y se deja constancia: seguir gastando en silencio
                # sobre un documento enorme es justamente lo que el tope evita.
                with session_scope() as sesion:
                    pedido = sesion.get(TraduccionDocumento, traduccion_id)
                    pedido.error = (
                        f"Se alcanzó el tope de {tope} USD por documento. "
                        f"Quedaron {len(elegidos) - hechos} bloques sin traducir."
                    )
                break

            traducciones, costo, entrada, salida = traducir_lote(lote, contexto)
            gastado += costo

            with session_scope() as sesion:
                for bloque_id, texto in traducciones.items():
                    sesion.add(TraduccionBloque(
                        traduccion_id=traduccion_id,
                        bloque_id=bloque_id,
                        contenido=texto,
                        confianza=1.0 if texto.strip() else 0.0,
                    ))

                pedido = sesion.get(TraduccionDocumento, traduccion_id)
                pedido.bloques_traducidos = hechos + len(traducciones)
                pedido.costo_usd = gastado
                pedido.actualizada_en = _ahora()

                if costo > 0:
                    sesion.add(CostoRegistrado(
                        usuario_id=usuario_id,
                        documento_id=documento_id,
                        tipo_cola="traduccion",
                        modelo=settings.modelo_escalacion,
                        tokens_entrada=entrada,
                        tokens_salida=salida,
                        costo_usd=costo,
                        razon_escalacion=f"Traducción a {contexto.idioma}",
                    ))

            hechos += len(traducciones)

        with session_scope() as sesion:
            pedido = sesion.get(TraduccionDocumento, traduccion_id)
            pedido.estado = "completada"
            pedido.actualizada_en = _ahora()

    except Exception as e:
        with session_scope() as sesion:
            pedido = sesion.get(TraduccionDocumento, traduccion_id)
            if pedido is not None:
                pedido.estado = "error"
                pedido.error = str(e)[:500]
                pedido.actualizada_en = _ahora()
