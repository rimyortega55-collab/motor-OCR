"""Orquestador de Capa 6 (Interfaz de Revisión Humana + Feedback Loop)."""

from __future__ import annotations

from uuid import UUID
from motor_ocr.modelos import Bloque, Documento

from .vista_bloques import VistaInteractiva
from .gestor_decisiones import GestorDecisiones, DecisionRevision
from .feedback_umbrales import AnalizadorFeedback


def iniciar_sesion_revision(
    documento: Documento,
    bloques: list[Bloque],
    bloques_para_revisar: list[UUID] = None,
    archivo_decisiones: str = "decisiones_revision.jsonl"
) -> dict:
    """Inicia sesión interactiva de revisión de bloques.

    Args:
        documento: Documento siendo revisado
        bloques: Todos los bloques del documento
        bloques_para_revisar: IDs específicos a revisar (None = todos problemáticos)
        archivo_decisiones: Dónde guardar las decisiones

    Returns:
        {
            "bloques_revisados": int,
            "decisiones": {...},
            "recomendaciones": [...],
            "archivo_decisiones": str
        }
    """

    vista = VistaInteractiva()
    gestor = GestorDecisiones(archivo_decisiones)

    # Filtrar bloques a revisar
    if bloques_para_revisar:
        bloques_ids_set = set(bloques_para_revisar)
        bloques_revision = [b for b in bloques if b.id in bloques_ids_set]
    else:
        # Revisar solo bloques con baja confianza o que requieren escalación
        bloques_revision = [
            b for b in bloques
            if (b.layout.confianza_layout < 0.7 or
                any(ms.confianza_engine < 0.6 for ms in (b.ocr.micro_segmentos or [])))
        ]

    if not bloques_revision:
        return {
            "bloques_revisados": 0,
            "decisiones": {},
            "recomendaciones": [],
            "archivo_decisiones": str(archivo_decisiones)
        }

    # Sesión interactiva
    revisados = 0
    saltados = 0

    for bloque in bloques_revision:
        # Preparar contexto
        contenido_engine = bloque.contenido.texto_plano or ""
        contenido_llm = None
        confianza_llm = None
        razon_escalacion = ""

        # Mostrar bloque y recibir decisión
        resultado = vista.mostrar_bloque(
            bloque_id=bloque.id,
            pagina=bloque.pagina,
            tipo=bloque.tipo.value,
            contenido_engine=contenido_engine,
            contenido_llm=contenido_llm,
            confianza_engine=bloque.layout.confianza_layout,
            confianza_llm=confianza_llm,
            razon_escalacion=razon_escalacion
        )

        # Procesar decisión
        if resultado.get("decision") == "quit":
            print("\nSesión terminada por usuario.")
            break

        elif resultado.get("decision") == "saltar":
            saltados += 1
            continue

        # Registrar decisión
        decision = DecisionRevision(
            bloque_id=bloque.id,
            documento_id=documento.documento_id,
            pagina=bloque.pagina,
            tipo_bloque=bloque.tipo.value,
            decision=resultado.get("decision", "desconocido"),
            contenido_original=contenido_engine,
            contenido_final=resultado.get("contenido_final", contenido_engine),
            confianza_engine=bloque.layout.confianza_layout,
            confianza_llm=confianza_llm,
            confianza_usuario=resultado.get("confianza_usuario", 0.5),
            comentarios=resultado.get("comentarios", ""),
            revisor="usuario"
        )

        gestor.registrar_decision(decision)
        revisados += 1

    # Mostrar resumen
    estadisticas = gestor.obtener_estadisticas(str(documento.documento_id))
    vista.mostrar_resumen(estadisticas)

    # Generar recomendaciones
    analizador = AnalizadorFeedback(gestor._decisiones_cache)
    analizador.mostrar_recomendaciones()
    analizador.mostrar_resumen_mejoras()

    return {
        "bloques_revisados": revisados,
        "bloques_saltados": saltados,
        "decisiones": estadisticas,
        "patrones": analizador.obtener_resumen_mejoras(),
        "archivo_decisiones": str(archivo_decisiones)
    }


def procesar_decisiones_offline(
    archivo_decisiones: str = "decisiones_revision.jsonl"
) -> dict:
    """Procesa decisiones guardadas para análisis offline.

    Útil para generar reportes después de una sesión de revisión.

    Args:
        archivo_decisiones: Ruta al archivo de decisiones

    Returns:
        {
            "estadisticas": {...},
            "patrones": {...},
            "recomendaciones": [...]
        }
    """

    gestor = GestorDecisiones(archivo_decisiones)
    analizador = AnalizadorFeedback(gestor._decisiones_cache)

    return {
        "estadisticas": gestor.obtener_estadisticas(),
        "patrones": analizador.obtener_resumen_mejoras(),
        "recomendaciones": analizador.generar_recomendaciones()
    }


def exportar_decisiones(
    archivo_entrada: str = "decisiones_revision.jsonl",
    archivo_salida: str = "decisiones_revision.csv"
) -> None:
    """Exporta decisiones a CSV para análisis en Excel."""

    gestor = GestorDecisiones(archivo_entrada)
    gestor.exportar_csv(archivo_salida)


__all__ = [
    "iniciar_sesion_revision",
    "procesar_decisiones_offline",
    "exportar_decisiones",
    "GestorDecisiones",
    "AnalizadorFeedback",
    "VistaInteractiva",
]
