from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from uto_routing.config import RuntimeSettings, get_settings
from uto_routing.models import (
    Dataset,
    Edge,
    Node,
    Priority,
    Shift,
    Task,
    Vehicle,
    Well,
    resolve_start_day,
)
from uto_routing.sample_data import create_sample_dataset


REQUIRED_BASENAMES = [
    "road_nodes",
    "road_edges",
    "wells",
    "vehicles",
    "tasks",
    "compatibility",
]


SAFE_TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def load_dataset(
    data_dir: str | None = None,
    *,
    settings: RuntimeSettings | None = None,
) -> Dataset:
    runtime = settings or get_settings()
    if data_dir is not None:
        return load_directory_dataset(Path(data_dir))
    if runtime.data_source == "sample":
        return create_sample_dataset()
    if runtime.data_source == "directory":
        if not runtime.data_dir:
            raise ValueError("UTO_DATA_DIR is required when UTO_DATA_SOURCE=directory")
        return load_directory_dataset(Path(runtime.data_dir))
    if runtime.data_source == "postgres":
        return load_postgres_dataset(runtime)
    raise ValueError(f"Unsupported data source: {runtime.data_source}")


def load_directory_dataset(data_dir: Path) -> Dataset:
    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")

    records = {basename: _load_records(data_dir, basename) for basename in REQUIRED_BASENAMES}

    nodes = [
        Node(
            node_id=int(record["node_id"]),
            lon=float(record["lon"]),
            lat=float(record["lat"]),
        )
        for record in records["road_nodes"]
    ]
    edges = [
        Edge(
            source=int(record["source"]),
            target=int(record["target"]),
            weight_m=float(record["weight"] if "weight" in record else record["weight_m"]),
        )
        for record in records["road_edges"]
    ]
    wells = [
        Well(
            uwi=str(record["uwi"]),
            lon=float(record["longitude"] if "longitude" in record else record["lon"]),
            lat=float(record["latitude"] if "latitude" in record else record["lat"]),
            well_name=str(record.get("well_name", record["uwi"])),
            nearest_node_id=(
                int(record["nearest_node_id"]) if record.get("nearest_node_id") not in (None, "") else None
            ),
        )
        for record in records["wells"]
    ]

    compatibility = _parse_compatibility(records["compatibility"])
    vehicles = []
    for record in records["vehicles"]:
        skills = _parse_skills(record.get("skills"))
        vehicle_type = str(record["vehicle_type"])
        if not skills:
            skills = {task_type for task_type, vehicle_types in compatibility.items() if vehicle_type in vehicle_types}
        vehicles.append(
            Vehicle(
                vehicle_id=int(record["vehicle_id"]),
                name=str(record["name"]),
                vehicle_type=vehicle_type,
                current_node=int(record["current_node"]),
                lon=float(record["lon"]),
                lat=float(record["lat"]),
                available_at=_parse_datetime(record["available_at"]),
                avg_speed_kmph=float(record["avg_speed_kmph"]),
                skills=skills,
                registration_plate=record.get("registration_plate"),
            )
        )

    tasks = [
        Task(
            task_id=str(record["task_id"]),
            priority=Priority(str(record["priority"]).lower()),
            planned_start=(planned_start := _parse_datetime(record["planned_start"])),
            planned_duration_hours=float(record["planned_duration_hours"]),
            destination_uwi=str(record["destination_uwi"]),
            task_type=str(record["task_type"]),
            shift=(shift := Shift(str(record["shift"]).lower())),
            start_day=resolve_start_day(planned_start, shift, record.get("start_day")),
        )
        for record in records["tasks"]
    ]

    return Dataset(
        nodes=nodes,
        edges=edges,
        wells=wells,
        vehicles=vehicles,
        tasks=tasks,
        compatibility=compatibility,
        metadata={
            "dataset_mode": "directory",
            "dataset_path": str(data_dir),
        },
    )


def load_postgres_dataset(settings: RuntimeSettings) -> Dataset:
    if not settings.database_url:
        raise ValueError("UTO_DATABASE_URL is required when UTO_DATA_SOURCE=postgres")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("psycopg is not installed. Add it to runtime dependencies.") from exc

    nodes_query = f"SELECT node_id, lon, lat FROM {_validate_table(settings.pg_table_road_nodes)} ORDER BY node_id"
    edges_query = (
        f"SELECT source, target, weight "
        f"FROM {_validate_table(settings.pg_table_road_edges)} ORDER BY source, target"
    )
    wells_query = (
        f"SELECT uwi, longitude, latitude, well_name, nearest_node_id "
        f"FROM {_validate_table(settings.pg_table_wells)} ORDER BY uwi"
    )
    vehicles_query = (
        f"SELECT vehicle_id, name, vehicle_type, current_node, lon, lat, available_at, avg_speed_kmph, "
        f"skills, registration_plate "
        f"FROM {_validate_table(settings.pg_table_vehicles)} ORDER BY vehicle_id"
    )
    tasks_query = (
        f"SELECT task_id, priority, planned_start, start_day, planned_duration_hours, "
        f"destination_uwi, task_type, shift "
        f"FROM {_validate_table(settings.pg_table_tasks)} ORDER BY planned_start, task_id"
    )
    compatibility_query = (
        f"SELECT task_type, vehicle_type FROM {_validate_table(settings.pg_table_compatibility)} "
        f"ORDER BY task_type, vehicle_type"
    )

    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            nodes_records = cursor.execute(nodes_query).fetchall()
            edges_records = cursor.execute(edges_query).fetchall()
            wells_records = cursor.execute(wells_query).fetchall()
            compatibility_records = cursor.execute(compatibility_query).fetchall()
            vehicles_records = cursor.execute(vehicles_query).fetchall()
            tasks_records = cursor.execute(tasks_query).fetchall()

    nodes = [
        Node(
            node_id=int(record["node_id"]),
            lon=float(record["lon"]),
            lat=float(record["lat"]),
        )
        for record in nodes_records
    ]
    node_lookup = {node.node_id: node for node in nodes}
    edges = [
        Edge(
            source=int(record["source"]),
            target=int(record["target"]),
            weight_m=float(record["weight"]),
        )
        for record in edges_records
    ]
    wells = [
        Well(
            uwi=str(record["uwi"]),
            lon=float(record["longitude"]),
            lat=float(record["latitude"]),
            well_name=str(record["well_name"]),
            nearest_node_id=_resolve_nearest_node_id(
                nodes=node_lookup,
                candidate=record.get("nearest_node_id"),
                lon=float(record["longitude"]),
                lat=float(record["latitude"]),
            ),
        )
        for record in wells_records
    ]

    compatibility = _parse_compatibility(compatibility_records)
    vehicles = []
    for record in vehicles_records:
        skills = _parse_skills(record.get("skills"))
        vehicle_type = str(record["vehicle_type"])
        if not skills:
            skills = {task_type for task_type, vehicle_types in compatibility.items() if vehicle_type in vehicle_types}
        lon = float(record["lon"])
        lat = float(record["lat"])
        vehicles.append(
            Vehicle(
                vehicle_id=int(record["vehicle_id"]),
                name=str(record["name"]),
                vehicle_type=vehicle_type,
                current_node=_resolve_nearest_node_id(
                    nodes=node_lookup,
                    candidate=record.get("current_node"),
                    lon=lon,
                    lat=lat,
                ),
                lon=lon,
                lat=lat,
                available_at=_parse_datetime(record["available_at"]),
                avg_speed_kmph=float(record["avg_speed_kmph"]),
                skills=skills,
                registration_plate=record.get("registration_plate"),
            )
        )

    tasks = []
    for record in tasks_records:
        planned_start = _parse_datetime(record["planned_start"])
        shift = Shift(str(record["shift"]).lower())
        tasks.append(
            Task(
                task_id=str(record["task_id"]),
                priority=Priority(str(record["priority"]).lower()),
                planned_start=planned_start,
                planned_duration_hours=float(record["planned_duration_hours"]),
                destination_uwi=str(record["destination_uwi"]),
                task_type=str(record["task_type"]),
                shift=shift,
                start_day=resolve_start_day(planned_start, shift, record.get("start_day")),
            )
        )

    return Dataset(
        nodes=nodes,
        edges=edges,
        wells=wells,
        vehicles=vehicles,
        tasks=tasks,
        compatibility=compatibility,
        metadata={
            "dataset_mode": "postgres",
            "database_url": _redact_database_url(settings.database_url),
        },
    )


def dataset_summary(dataset: Dataset) -> dict[str, Any]:
    return {
        "mode": dataset.metadata.get("dataset_mode", "unknown"),
        "nodes": len(dataset.nodes),
        "edges": len(dataset.edges),
        "wells": len(dataset.wells),
        "vehicles": len(dataset.vehicles),
        "tasks": len(dataset.tasks),
        "task_types": sorted(dataset.compatibility.keys()),
        "vehicle_types": sorted({vehicle.vehicle_type for vehicle in dataset.vehicles}),
    }


def _load_records(data_dir: Path, basename: str) -> list[dict[str, Any]]:
    for suffix in (".json", ".csv"):
        path = data_dir / f"{basename}{suffix}"
        if not path.exists():
            continue
        if suffix == ".json":
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict) and "records" in loaded:
                return list(loaded["records"])
            if isinstance(loaded, list):
                return loaded
            raise ValueError(f"Unsupported JSON structure in {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    raise FileNotFoundError(
        f"Expected {basename}.json or {basename}.csv in {data_dir}"
    )


def _parse_compatibility(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    compatibility: dict[str, set[str]] = {}
    for record in records:
        task_type = str(record["task_type"])
        vehicle_type = str(record["vehicle_type"])
        compatibility.setdefault(task_type, set()).add(vehicle_type)
    return compatibility


def _parse_skills(raw_value: Any) -> set[str]:
    if raw_value in (None, ""):
        return set()
    if isinstance(raw_value, list):
        return {str(item) for item in raw_value}
    return {item.strip() for item in str(raw_value).split("|") if item.strip()}


def _parse_datetime(raw_value: Any) -> datetime:
    if isinstance(raw_value, datetime):
        return raw_value
    return datetime.fromisoformat(str(raw_value))


def _validate_table(table_name: str) -> str:
    if not SAFE_TABLE_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def _resolve_nearest_node_id(
    *,
    nodes: dict[int, Node],
    candidate: Any,
    lon: float,
    lat: float,
) -> int:
    if candidate not in (None, ""):
        return int(candidate)
    best_node_id = -1
    best_distance = float("inf")
    for node_id, node in nodes.items():
        distance = (node.lon - lon) ** 2 + (node.lat - lat) ** 2
        if distance < best_distance:
            best_distance = distance
            best_node_id = node_id
    if best_node_id == -1:
        raise ValueError("Could not resolve nearest node.")
    return best_node_id


def _redact_database_url(database_url: str) -> str:
    if "@" not in database_url:
        return database_url
    prefix, suffix = database_url.split("@", 1)
    if "://" not in prefix:
        return f"***@{suffix}"
    scheme, _credentials = prefix.split("://", 1)
    return f"{scheme}://***@{suffix}"

