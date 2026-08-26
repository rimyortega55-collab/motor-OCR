"""Umbrales de confianza de la instancia (§7 del contrato).

Antes vivían en `umbrales_config.json`, con ruta relativa y sin dueño: se
perdía en cada despliegue. Después pasaron a una fila por cuenta. Ahora, sin
cuentas, viven en una única fila global en la tabla `umbrales`: son los
umbrales de esta instancia, no de nadie en particular.

Las recomendaciones se calculan a partir de la tabla `decisiones` y no del caché
en memoria de `GestorDecisiones`, que se vacía al reiniciar el proceso: el
auto-ajuste sólo veía las decisiones de la sesión en curso, con lo que el loop de
feedback de la Capa 7 nunca acumulaba historia.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from motor_ocr_api.persistencia import DecisionAlmacenada, UmbralesGlobales, obtener_sesion

from .ajuste_umbrales import AjustadorUmbrales

router = APIRouter(tags=["umbrales"])


# Los globales no están en AjustadorUmbrales: son los de config/settings.py, que
# hasta ahora sólo se podían tocar por variable de entorno.
GLOBALES_POR_DEFECTO = {
    "umbral_confianza_engine": 0.75,
    "umbral_confianza_estructural": 0.75,
    "umbral_confianza_global_escalacion": 0.70,
    "umbral_escalacion_micro_segmento": 0.6,
}


class AjusteUmbrales(BaseModel):
    """Actualización parcial: sólo llegan los ámbitos que se tocaron."""

    capa3: dict[str, float] | None = None
    capa4: dict[str, float] | None = None
    globales: dict[str, float] | None = None

    @field_validator("capa3", "capa4", "globales")
    @classmethod
    def _entre_cero_y_uno(cls, valores):
        if valores is None:
            return None
        for clave, valor in valores.items():
            if not 0.0 <= valor <= 1.0:
                raise ValueError(f"{clave}={valor} está fuera de [0, 1]")
        return valores


class Aplicacion(BaseModel):
    """Qué recomendaciones aplicar. Lista vacía = todas las aplicables."""

    claves: list[str] = Field(default_factory=list)


def _defaults() -> dict:
    base = AjustadorUmbrales()._cargar_umbrales()
    return {
        "capa3": dict(base.get("capa3", {})),
        "capa4": dict(base.get("capa4", {})),
        "globales": dict(GLOBALES_POR_DEFECTO),
    }


def obtener_o_crear(sesion: Session) -> UmbralesGlobales:
    """La fila global de umbrales, sembrada con los valores por defecto la primera vez."""

    fila = sesion.get(UmbralesGlobales, "global")
    if fila is not None:
        return fila

    valores = _defaults()
    fila = UmbralesGlobales(
        id="global",
        capa3=valores["capa3"],
        capa4=valores["capa4"],
        globales=valores["globales"],
    )
    sesion.add(fila)
    sesion.commit()
    return fila


def _iso(momento: datetime | None) -> str | None:
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.isoformat()


def _serializar(fila: UmbralesGlobales) -> dict:
    return {
        "capa3": fila.capa3 or {},
        "capa4": fila.capa4 or {},
        "globales": fila.globales or {},
        "actualizado_en": _iso(fila.actualizado_en),
    }


def _decisiones(sesion: Session) -> list[dict]:
    """Todas las decisiones registradas, en la forma que espera `AjustadorUmbrales`."""

    filas = sesion.query(DecisionAlmacenada).all()

    return [
        {
            "tipo_bloque": f.tipo_bloque or "",
            "decision": f.decision,
            "confianza_engine": f.confianza_engine or 0.0,
            "confianza_usuario": f.confianza_usuario or 0.0,
        }
        for f in filas
        # Sin tipo no se puede agrupar: juntarlas bajo "" armaría un cubo que no
        # representa a ningún tipo de bloque y recomendaría sobre esa mezcla.
        if f.tipo_bloque
    ]


def _ajustador(fila: UmbralesGlobales) -> AjustadorUmbrales:
    """AjustadorUmbrales apuntando a los umbrales vigentes de la instancia.

    Se le reemplaza el diccionario en vez de dejar que lea su archivo, que es lo
    que hacía que los umbrales fueran los mismos para cualquier despliegue.
    """
    ajustador = AjustadorUmbrales()
    ajustador.umbrales = {
        "capa3": dict(fila.capa3 or {}),
        "capa4": dict(fila.capa4 or {}),
    }
    return ajustador


@router.get("/umbrales")
async def leer_umbrales(sesion: Session = Depends(obtener_sesion)):
    """Umbrales de la instancia. La primera vez se siembran con los del motor."""
    return _serializar(obtener_o_crear(sesion))


@router.put("/umbrales")
async def actualizar_umbrales(
    ajuste: AjusteUmbrales,
    sesion: Session = Depends(obtener_sesion),
):
    """Actualiza los ámbitos recibidos y devuelve el estado completo."""

    fila = obtener_o_crear(sesion)

    for ambito in ("capa3", "capa4", "globales"):
        nuevos = getattr(ajuste, ambito)
        if nuevos is None:
            continue
        # Copia nueva y no mutación in situ: SQLAlchemy no detecta cambios dentro
        # de un JSON ya asignado, y el UPDATE no saldría.
        actual = dict(getattr(fila, ambito) or {})
        actual.update(nuevos)
        setattr(fila, ambito, actual)

    fila.actualizado_en = datetime.now(timezone.utc)
    sesion.commit()

    return _serializar(fila)


@router.get("/umbrales/recomendaciones")
async def recomendaciones(sesion: Session = Depends(obtener_sesion)):
    """Calcula recomendaciones **sin aplicarlas**.

    Separar el cálculo de la aplicación es lo que permite mostrar la propuesta
    antes de decidir; el antiguo `POST /auto-ajuste` hacía las dos cosas juntas.
    """

    decisiones = _decisiones(sesion)
    fila = obtener_o_crear(sesion)
    propuestas = _ajustador(fila).calcular_umbrales_optimos(decisiones)

    return {
        "decisiones_analizadas": len(decisiones),
        "recomendaciones": [
            {
                "ambito": f"capa{p.capa}",
                "clave": p.tipo_bloque,
                "actual": p.umbral_anterior,
                "propuesto": p.umbral_nuevo,
                "confianza": p.confianza,
                "razon": p.razon,
                "aplicable": p.aplicable(),
            }
            for p in propuestas
        ],
    }


@router.post("/umbrales/aplicar")
async def aplicar(
    peticion: Aplicacion,
    sesion: Session = Depends(obtener_sesion),
):
    """Aplica las recomendaciones indicadas, o todas las aplicables.

    `validacion` viaja en `null` a propósito. `AjustadorUmbrales.validar_cambios`
    devuelve números fijos con la razón "Simulado - requiere validación real";
    mostrarlos como "revertido porque la confianza bajó 4,1 %" sería inventarle un
    número que nunca se midió. Cuando exista una validación contra un lote real,
    este campo la lleva.
    """

    decisiones = _decisiones(sesion)
    fila = obtener_o_crear(sesion)

    propuestas = [
        p for p in _ajustador(fila).calcular_umbrales_optimos(decisiones)
        if p.aplicable()
    ]

    if peticion.claves:
        pedidas = set(peticion.claves)
        propuestas = [p for p in propuestas if p.tipo_bloque in pedidas]

    if not propuestas:
        return {
            "status": "no_cambios",
            "razon": "No hay recomendaciones aplicables",
            "cambios_aplicados": 0,
            "umbrales": _serializar(fila),
            "validacion": None,
        }

    anterior = {"capa3": dict(fila.capa3 or {}), "capa4": dict(fila.capa4 or {})}

    capa3 = dict(fila.capa3 or {})
    capa4 = dict(fila.capa4 or {})
    for p in propuestas:
        destino = capa3 if p.capa == 3 else capa4
        destino[p.tipo_bloque] = p.umbral_nuevo

    fila.capa3 = capa3
    fila.capa4 = capa4
    fila.actualizado_en = datetime.now(timezone.utc)
    sesion.commit()

    return {
        "status": "ok",
        "cambios_aplicados": len(propuestas),
        "anterior": anterior,
        "umbrales": _serializar(fila),
        "detalles": [
            {
                "clave": p.tipo_bloque,
                "de": p.umbral_anterior,
                "a": p.umbral_nuevo,
                "razon": p.razon,
            }
            for p in propuestas
        ],
        "validacion": None,
    }
