"""Altı Strands Tool'u (Req 5). Kimlik yalnızca ``tool_context.invocation_state['userid']``."""
from __future__ import annotations

from typing import Any

from strands import ToolContext, tool

from logistic_ai_data.repository import (
    CRITICAL,
    QUESTION1,
    QUESTION2,
    QUESTION3,
    QUESTION4,
    QUESTION5,
)

from .guard import guarded_call

_Q1_FIELDS = ("Arac_Konum", "Tofas_Eta_Tarihi", "Kalan_Stop_Adet")
_Q2_COLUMNS = ("shipment_id", "quantity", "tofas_etadate", "supplier_code", "mip")
_BLOCKED = frozenset({"role_user", "permissions", "password_hash", "password"})


def _strip(row: dict) -> dict:
    """Ham JSON kolonları, ``*_parsed`` kopyaları ve kimlik/izin alanları çıkarılır."""
    parsed_names = {k[: -len("_parsed")] for k in row if k.endswith("_parsed")}
    return {
        k: v
        for k, v in row.items()
        if not k.endswith("_parsed") and k not in parsed_names and k not in _BLOCKED
    }


def _parsed_dict(row: dict, column: str) -> dict:
    parsed = row.get(f"{column}_parsed")
    return parsed if isinstance(parsed, dict) else {}


def _shape_q1(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        p = _parsed_dict(r, "question1")
        item = {"shipment_id": r.get("shipment_id")}
        for f in _Q1_FIELDS:
            item[f] = p.get(f)
        out.append(item)
    return out


def _shape_q2(rows: list[dict]) -> list[dict]:
    return [{c: r.get(c) for c in _Q2_COLUMNS} for r in rows]


def _stop_order(row: dict) -> int:
    return int(float(str(row.get("stop_sequence")).strip()))


def _shape_q3(rows: list[dict]) -> list[dict]:
    return [_strip(r) for r in sorted(rows, key=_stop_order)]


def _whole_minutes(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(round(float(value)))


def _shape_q4(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        p = _parsed_dict(r, "question4")
        item = {"shipment_id": r.get("shipment_id"), "delay_minutes": _whole_minutes(r.get("delay_time"))}
        for k, v in p.items():
            item.setdefault(k, v)
        out.append(item)
    return out


def _shape_plain(rows: list[dict]) -> list[dict]:
    return [_strip(r) for r in rows]


@tool(context=True)
def get_truck_location(shipment_id: str, tool_context: ToolContext) -> dict:
    """Bir seferin (shipment_id) güncel araç konumunu, Tofaş ETA tarihini ve kalan stop sayısını getirir.

    Args:
        shipment_id: Sefer numarası, örn. FA2002267103.
    """
    return guarded_call(
        function_name="get_truck_location",
        table=QUESTION1,
        tool_context=tool_context,
        key_param="shipment_id",
        key_value=shipment_id,
        fetch=lambda repo: repo.get_by_key(QUESTION1, shipment_id),
        shape=_shape_q1,
    )


@tool(context=True)
def get_material_truck_allocation(materialno: str, tool_context: ToolContext) -> dict:
    """Bir malzemenin (materialno) hangi seferlere, hangi miktar ve ETA ile atandığını getirir.

    Args:
        materialno: Malzeme numarası, örn. 07358034660E.
    """
    return guarded_call(
        function_name="get_material_truck_allocation",
        table=QUESTION2,
        tool_context=tool_context,
        key_param="materialno",
        key_value=materialno,
        fetch=lambda repo: repo.get_by_key(QUESTION2, materialno),
        shape=_shape_q2,
    )


@tool(context=True)
def get_truck_route_info(shipment_id: str, tool_context: ToolContext) -> dict:
    """Bir seferin rota duraklarını stop sırasına göre getirir.

    Args:
        shipment_id: Sefer numarası, örn. FA2002267103.
    """
    return guarded_call(
        function_name="get_truck_route_info",
        table=QUESTION3,
        tool_context=tool_context,
        key_param="shipment_id",
        key_value=shipment_id,
        fetch=lambda repo: repo.get_by_key(QUESTION3, shipment_id),
        shape=_shape_q3,
    )


@tool(context=True)
def get_delayed_truck(tool_context: ToolContext) -> dict:
    """Geciken tüm seferleri ve gecikme sürelerini (dakika) getirir."""
    return guarded_call(
        function_name="get_delayed_truck",
        table=QUESTION4,
        tool_context=tool_context,
        fetch=lambda repo: repo.get_all(QUESTION4),
        shape=_shape_q4,
    )


@tool(context=True)
def get_truck_tobearrived(tool_context: ToolContext) -> dict:
    """Varması beklenen tüm seferleri (ETA, sürücü bilgisi) getirir."""
    return guarded_call(
        function_name="get_truck_tobearrived",
        table=QUESTION5,
        tool_context=tool_context,
        fetch=lambda repo: repo.get_all(QUESTION5),
        shape=_shape_plain,
    )


@tool(context=True)
def get_critical_part_status(mip: str, tool_context: ToolContext) -> dict:
    """Bir MIP numarasına ait kritik parça durumlarını getirir.

    Args:
        mip: MIP numarası, örn. 47.
    """
    return guarded_call(
        function_name="get_critical_part_status",
        table=CRITICAL,
        tool_context=tool_context,
        key_param="mip",
        key_value=mip,
        fetch=lambda repo: repo.get_by_key(CRITICAL, mip),
        shape=_shape_plain,
    )


ALL_TOOLS = [
    get_truck_location,
    get_material_truck_allocation,
    get_truck_route_info,
    get_delayed_truck,
    get_truck_tobearrived,
    get_critical_part_status,
]
