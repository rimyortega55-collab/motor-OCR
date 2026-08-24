"""Cliente del API de Anthropic (`/v1/messages`) para las llamadas de escalación.

Modelo con capacidad de visión (no solo texto) — necesario porque el error
casi siempre viene de algo que el engine determinista no pudo interpretar
bien visualmente. Salida estructurada (JSON) con contenido corregido +
confianza propia del modelo, para marcar casos de doble baja confianza
(engine determinista + LLM) para revisión humana.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

from ocr_engine.models import EscalationResult, Costo

_client = None

def _get_client():
    """Lazy loader para cliente Anthropic."""
    global _client
    if _client is None:
        try:
            from anthropic import Anthropic
            _client = Anthropic()
        except ImportError:
            print("[LLM] Anthropic SDK no instalado")
            return None
    return _client

def llamar_llm_micro_segmento(
    imagen_recorte,
    contexto_texto: str,
    resultado_engine: str,
    tipo_segmento: str = "texto"
) -> EscalationResult:
    """Llama al LLM para corregir micro-segmento de baja confianza.

    Args:
        imagen_recorte: numpy array de la región problemática
        contexto_texto: Texto de contexto antes/después
        resultado_engine: Lo que el engine determinista extrajo
        tipo_segmento: "texto" o "formula_inline"

    Returns:
        EscalationResult con contenido corregido por LLM
    """

    client = _get_client()
    if client is None:
        # Fallback: mantener resultado del engine
        return EscalationResult(
            cola_origen="micro_segmento",
            contenido_final=resultado_engine,
            confianza_llm=0.0,
            requiere_revision_humana=True,
            costo=Costo(),
            razon_escalacion="LLM no disponible"
        )

    try:
        # Codificar imagen en base64
        imagen_base64 = _codificar_imagen(imagen_recorte)

        # Prompt específico por tipo
        if tipo_segmento == "formula_inline":
            prompt = f"""Revisa esta fórmula matemática extraída por OCR de baja confianza.

El engine extrajó: {resultado_engine}

Contexto (texto circundante): {contexto_texto}

Devuelve un JSON con:
{{
    "contenido_corregido": "<la fórmula corregida en LaTeX>",
    "confianza": <0.0 a 1.0>,
    "ambiguo": <true si no hay suficiente contexto para decidir>,
    "razon": "<breve explicación de la corrección>"
}}

Solo corrige si estás seguro. Si es ambiguo, pon ambiguo=true."""

        else:  # texto
            prompt = f"""Revisa este texto extraído por OCR de baja confianza.

El engine extrajó: {resultado_engine}

Contexto: {contexto_texto}

Devuelve un JSON con:
{{
    "contenido_corregido": "<texto corregido>",
    "confianza": <0.0 a 1.0>,
    "cambios": ["<cambio 1>", "<cambio 2>"],
    "razon": "<por qué cambió>"
}}"""

        # Construir mensaje con imagen
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": imagen_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )

        # Parsear respuesta
        respuesta_texto = message.content[0].text

        try:
            # Extraer JSON de la respuesta
            start_idx = respuesta_texto.find('{')
            end_idx = respuesta_texto.rfind('}') + 1
            json_str = respuesta_texto[start_idx:end_idx]
            respuesta_json = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            # Si no hay JSON válido, mantener resultado del engine
            respuesta_json = {
                "contenido_corregido": resultado_engine,
                "confianza": 0.3,
                "ambiguo": True,
                "razon": "Respuesta LLM no estructurada"
            }

        # Extraer tokens de uso
        tokens_entrada = message.usage.input_tokens
        tokens_salida = message.usage.output_tokens

        return EscalationResult(
            cola_origen="micro_segmento",
            contenido_final=respuesta_json.get("contenido_corregido", resultado_engine),
            confianza_llm=respuesta_json.get("confianza", 0.5),
            requiere_revision_humana=respuesta_json.get("ambiguo", False),
            costo=Costo(
                tokens_entrada=tokens_entrada,
                tokens_salida=tokens_salida,
                modelo_usado=["claude-3-5-sonnet-20241022"]
            ),
            razon_escalacion=respuesta_json.get("razon", "")
        )

    except Exception as e:
        print(f"[LLM] Error en micro-segmento: {e}")
        return EscalationResult(
            cola_origen="micro_segmento",
            contenido_final=resultado_engine,
            confianza_llm=0.0,
            requiere_revision_humana=True,
            costo=Costo(),
            razon_escalacion=f"Error LLM: {str(e)}"
        )

def llamar_llm_inconsistencia(
    indice_estructural: dict,
    fragmentos_contexto: list[dict]
) -> EscalationResult:
    """Llama al LLM para resolver inconsistencia documental.

    Args:
        indice_estructural: Índice de teoremas/lemas del documento
        fragmentos_contexto: Lista de {tipo, detalle, contexto_antes, contexto_despues}

    Returns:
        EscalationResult con análisis de la inconsistencia
    """

    client = _get_client()
    if client is None:
        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final="",
            confianza_llm=0.0,
            requiere_revision_humana=True,
            costo=Costo(),
            razon_escalacion="LLM no disponible"
        )

    try:
        # Formatear índice estructural
        teoremas_str = "\n".join([
            f"  - {t['numero']}: página {t['pagina']}"
            for t in indice_estructural.get("teoremas", [])
        ])

        fragmentos_str = "\n".join([
            f"- {f['tipo']}: {f['detalle']} (contexto: {f.get('contexto_antes', '')[:50]}...{f.get('contexto_despues', '')[:50]})"
            for f in fragmentos_contexto
        ])

        prompt = f"""Analiza esta inconsistencia documental detectada en un documento académico.

Índice estructural del documento:
{teoremas_str}

Inconsistencia detectada:
{fragmentos_str}

Devuelve un JSON con:
{{
    "análisis": "<explicación de la inconsistencia>",
    "es_error_ocr": <true si probablemente es error de OCR>,
    "es_falta_contenido": <true si falta un bloque>,
    "sugerencia": "<qué hacer: verificar, reprocesar, o revisar manualmente>",
    "confianza": <0.0 a 1.0>,
    "requiere_humano": <true si no es automáticamente resoluble>
}}

IMPORTANTE: No generes contenido nuevo. Solo analiza lo que existe."""

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        )

        respuesta_texto = message.content[0].text

        try:
            start_idx = respuesta_texto.find('{')
            end_idx = respuesta_texto.rfind('}') + 1
            json_str = respuesta_texto[start_idx:end_idx]
            respuesta_json = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            respuesta_json = {
                "análisis": respuesta_texto,
                "confianza": 0.3,
                "requiere_humano": True,
                "sugerencia": "Revisar manualmente"
            }

        tokens_entrada = message.usage.input_tokens
        tokens_salida = message.usage.output_tokens

        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final=respuesta_json.get("análisis", ""),
            confianza_llm=respuesta_json.get("confianza", 0.5),
            requiere_revision_humana=respuesta_json.get("requiere_humano", True),
            costo=Costo(
                tokens_entrada=tokens_entrada,
                tokens_salida=tokens_salida,
                modelo_usado=["claude-3-5-sonnet-20241022"]
            ),
            razon_escalacion=respuesta_json.get("sugerencia", "")
        )

    except Exception as e:
        print(f"[LLM] Error en inconsistencia: {e}")
        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final="",
            confianza_llm=0.0,
            requiere_revision_humana=True,
            costo=Costo(),
            razon_escalacion=f"Error LLM: {str(e)}"
        )

def _codificar_imagen(imagen_recorte) -> str:
    """Codifica imagen numpy a base64 PNG."""
    try:
        import numpy as np
        from PIL import Image
        import io

        # Convertir a PIL Image
        if isinstance(imagen_recorte, np.ndarray):
            if len(imagen_recorte.shape) == 2:
                # Grayscale
                pil_img = Image.fromarray(imagen_recorte, mode='L')
            else:
                # RGB/BGR
                if imagen_recorte.shape[2] == 3:
                    pil_img = Image.fromarray(imagen_recorte, mode='RGB')
                else:
                    pil_img = Image.fromarray(imagen_recorte[:, :, :3], mode='RGB')
        else:
            pil_img = imagen_recorte

        # Convertir a PNG base64
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return img_base64

    except Exception as e:
        print(f"[LLM] Error codificando imagen: {e}")
        return ""
