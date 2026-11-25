"""Known resource names for dynamic permissions (Requirements 3.1, 3.3)."""
from __future__ import annotations

TABLE = "TABLE"
FUNCTION = "FUNCTION"
RESOURCE_TYPES: tuple[str, ...] = (TABLE, FUNCTION)

TABLES: tuple[str, ...] = (
    "question1",
    "question2",
    "question3",
    "question4",
    "question5",
    "critical",
    "summary_df",
)

FUNCTIONS: tuple[str, ...] = (
    "get_truck_location",
    "get_material_truck_allocation",
    "get_truck_route_info",
    "get_delayed_truck",
    "get_truck_tobearrived",
    "get_critical_part_status",
)

# Authentication tables: never grantable (Requirement 3.3).
AUTH_TABLES: frozenset[str] = frozenset({"role_user", "permissions"})

_KNOWN = {TABLE: frozenset(TABLES), FUNCTION: frozenset(FUNCTIONS)}


def is_known_resource(resource_type: str, resource: str) -> bool:
    return resource in _KNOWN.get(resource_type, frozenset())
