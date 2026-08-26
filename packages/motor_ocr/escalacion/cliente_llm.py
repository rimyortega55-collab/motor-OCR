"""Cliente del proveedor de IA para las llamadas de escalación.

Modelo con capacidad de visión (no solo texto) — necesario porque el error
casi siempre viene de algo que el engine determinista no pudo interpretar
bien visualmente. Salida estructurada (JSON) con contenido corregido +
confianza propia del modelo, para marcar casos de doble baja confianza
(engine determinista + LLM) para revisión humana.

El proveedor es configurable (Capa 5 no está atada a Anthropic): "anthropic"
usa el SDK oficial, "openai_compatible" habla con cualquier servidor que
implemente `/chat/completions` al estilo OpenAI (un gateway propio, vLLM,
Ollama, etc.) por URL y clave, y "local" queda pendiente — no hay todavía un
modelo propio entrenado para OCR matemático, así que se comporta como
"LLM no disponible" hasta que exista uno. `configurar_proveedor` es lo que usa
`motor_ocr_api` para aplicar en caliente lo que el panel de administración
guarda en base de datos, sin reiniciar el proceso.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

from motor_ocr.config.settings import settings
from motor_ocr.modelos import EscalationResult, Costo

# Config activa del proceso. Arranca de las variables de entorno (comportamiento
# de siempre) y `configurar_proveedor` la reemplaza cuando el panel de
# administración guarda un cambio.
_configuracion = {
    "proveedor": "anthropic",
    "modelo": settings.modelo_escalacion,
    "base_url": None,
    "api_key": None,
}

_proveedor_activo: "_Proveedor | None" = None


def configurar_proveedor(
    proveedor: str,
    modelo: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> None:
    """Aplica la configuración de proveedor de IA. Ver `_configuracion` arriba."""
    global _proveedor_activo
    _configuracion["proveedor"] = proveedor
    _configuracion["modelo"] = modelo or settings.modelo_escalacion
    _configuracion["base_url"] = base_url
    _configuracion["api_key"] = api_key
    _proveedor_activo = None  # se reconstruye en el próximo uso


class RespuestaProveedor:
    def __init__(self, texto: str, tokens_entrada: int, tokens_salida: int):
        self.texto = texto
        self.tokens_entrada = tokens_entrada
        self.tokens_salida = tokens_salida


class _Proveedor(Protocol):
    def completar(self, prompt: str, imagen_base64: str | None) -> RespuestaProveedor: ...


class _ProveedorAnthropic:
    """SDK oficial de Anthropic (`/v1/messages`)."""

    def __init__(self, modelo: str, api_key: str | None):
        from anthropic import Anthropic

        self._modelo = modelo
        # Sin api_key explícita, el SDK lee ANTHROPIC_API_KEY del entorno.
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def completar(self, prompt: str, imagen_base64: str | None) -> RespuestaProveedor:
        contenido: list[dict] = []
        if imagen_base64:
            contenido.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": imagen_base64},
            })
        contenido.append({"type": "text", "text": prompt})

        mensaje = self._client.messages.create(
            model=self._modelo,
            max_tokens=8192,
            messages=[{"role": "user", "content": contenido}],
        )

        # No se puede tomar `message.content[0].text`: en los modelos con thinking
        # adaptativo el primer bloque es un `ThinkingBlock` sin atributo `text`, y
        # la llamada moría con "'ThinkingBlock' object has no attribute 'text'"
        # antes de registrar ningún costo. Recorrer y filtrar por tipo funciona
        # con thinking y sin él.
        texto = "".join(
            bloque.text for bloque in mensaje.content if getattr(bloque, "type", None) == "text"
        ).strip()

        return RespuestaProveedor(texto, mensaje.usage.input_tokens, mensaje.usage.output_tokens)


class _ProveedorOpenAICompatible:
    """Cualquier servidor con API de chat compatible con OpenAI, por URL y clave.

    Cubre desde proveedores comerciales (OpenAI, OpenRouter, Groq, ...) hasta un
    servidor auto-hospedado (vLLM, Ollama, LM Studio): todos exponen el mismo
    contrato de `/chat/completions`, así que un único cliente les habla a todos.
    """

    def __init__(self, modelo: str, base_url: str, api_key: str | None):
        import httpx

        self._modelo = modelo
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=120.0,
        )

    def completar(self, prompt: str, imagen_base64: str | None) -> RespuestaProveedor:
        if imagen_base64:
            contenido = [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{imagen_base64}"}},
                {"type": "text", "text": prompt},
            ]
        else:
            contenido = prompt

        respuesta = self._client.post(
            "/chat/completions",
            json={
                "model": self._modelo,
                "max_tokens": 8192,
                "messages": [{"role": "user", "content": contenido}],
            },
        )
        respuesta.raise_for_status()
        cuerpo = respuesta.json()

        texto = (cuerpo.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        uso = cuerpo.get("usage") or {}

        return RespuestaProveedor(
            texto.strip(),
            uso.get("prompt_tokens", 0),
            uso.get("completion_tokens", 0),
        )


def _get_proveedor() -> "_Proveedor | None":
    """Construye (una vez) el cliente del proveedor configurado.

    Devuelve None cuando no hay proveedor disponible: "local" está pendiente de
    implementar (no hay todavía un modelo propio entrenado), "openai_compatible"
    sin base_url es una configuración incompleta, y cualquier error al armar el
    cliente (SDK no instalado, credenciales ausentes) degrada de la misma forma
    que antes, a "LLM no disponible", en vez de tirar el request.
    """
    global _proveedor_activo
    if _proveedor_activo is not None:
        return _proveedor_activo

    proveedor = _configuracion["proveedor"]
    modelo = _configuracion["modelo"] or settings.modelo_escalacion

    try:
        if proveedor == "anthropic":
            _proveedor_activo = _ProveedorAnthropic(modelo, _configuracion["api_key"])
        elif proveedor == "openai_compatible":
            base_url = _configuracion["base_url"]
            if not base_url:
                print("[LLM] openai_compatible configurado sin base_url")
                return None
            _proveedor_activo = _ProveedorOpenAICompatible(
                modelo, base_url, _configuracion["api_key"]
            )
        elif proveedor == "local":
            # Pendiente: entrenar un modelo propio de OCR matemático es la
            # dirección declarada del proyecto, pero todavía no existe. Hasta
            # entonces, "local" se comporta como "sin LLM disponible".
            print("[LLM] proveedor 'local' todavía no está implementado (pendiente)")
            return None
        else:
            print(f"[LLM] proveedor desconocido: {proveedor}")
            return None
    except ImportError as e:
        print(f"[LLM] dependencia faltante para el proveedor '{proveedor}': {e}")
        return None
    except Exception as e:
        print(f"[LLM] no se pudo inicializar el proveedor '{proveedor}': {e}")
        return None

    return _proveedor_activo


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

    proveedor = _get_proveedor()
    if proveedor is None:
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
        imagen_base64 = _codificar_imagen(imagen_recorte)

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

        respuesta = proveedor.completar(prompt, imagen_base64)

        try:
            start_idx = respuesta.texto.find('{')
            end_idx = respuesta.texto.rfind('}') + 1
            json_str = respuesta.texto[start_idx:end_idx]
            respuesta_json = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            respuesta_json = {
                "contenido_corregido": resultado_engine,
                "confianza": 0.3,
                "ambiguo": True,
                "razon": "Respuesta LLM no estructurada"
            }

        return EscalationResult(
            cola_origen="micro_segmento",
            contenido_final=respuesta_json.get("contenido_corregido", resultado_engine),
            confianza_llm=respuesta_json.get("confianza", 0.5),
            requiere_revision_humana=respuesta_json.get("ambiguo", False),
            costo=Costo(
                tokens_entrada=respuesta.tokens_entrada,
                tokens_salida=respuesta.tokens_salida,
                modelo_usado=[_configuracion["modelo"] or settings.modelo_escalacion]
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

    proveedor = _get_proveedor()
    if proveedor is None:
        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final="",
            confianza_llm=0.0,
            requiere_revision_humana=True,
            costo=Costo(),
            razon_escalacion="LLM no disponible"
        )

    try:
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

        respuesta = proveedor.completar(prompt, None)

        try:
            start_idx = respuesta.texto.find('{')
            end_idx = respuesta.texto.rfind('}') + 1
            json_str = respuesta.texto[start_idx:end_idx]
            respuesta_json = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            respuesta_json = {
                "análisis": respuesta.texto,
                "confianza": 0.3,
                "requiere_humano": True,
                "sugerencia": "Revisar manualmente"
            }

        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final=respuesta_json.get("análisis", ""),
            confianza_llm=respuesta_json.get("confianza", 0.5),
            requiere_revision_humana=respuesta_json.get("requiere_humano", True),
            costo=Costo(
                tokens_entrada=respuesta.tokens_entrada,
                tokens_salida=respuesta.tokens_salida,
                modelo_usado=[_configuracion["modelo"] or settings.modelo_escalacion]
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
