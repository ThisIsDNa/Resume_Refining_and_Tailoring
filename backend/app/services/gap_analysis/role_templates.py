"""
Role profiles for gap analysis (required vs nice-to-have capability signals).

Templates reference ``signal_id`` keys from ``signals_catalog.SIGNAL_CATALOG``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class RoleProfile:
    id: str
    display_name: str
    required_signals: Tuple[str, ...]
    nice_to_have_signals: Tuple[str, ...]


ROLE_TEMPLATES: Dict[str, RoleProfile] = {
    "strategy_operations": RoleProfile(
        id="strategy_operations",
        display_name="Strategy & Operations",
        required_signals=(
            "stakeholder_communication",
            "cross_functional_coordination",
            "metrics_reporting",
            "reporting_dashboard_ownership",
            "executive_readouts",
            "workflow_optimization",
            "operating_cadence",
            "pilots_and_experiments",
        ),
        nice_to_have_signals=(
            "financial_modeling",
            "vendor_management",
            "process_improvement",
            "metrics_dashboards",
            "experimentation_ab",
        ),
    ),
    "product_analyst": RoleProfile(
        id="product_analyst",
        display_name="Product Analyst",
        required_signals=(
            "product_discovery",
            "sql_data",
            "experimentation_ab",
            "metrics_dashboards",
            "user_research_signals",
        ),
        nice_to_have_signals=("roadmapping", "metrics_reporting"),
    ),
    "bizops": RoleProfile(
        id="bizops",
        display_name="BizOps",
        required_signals=(
            "sql_data",
            "operational_excellence",
            "cross_functional_coordination",
            "reporting_automation",
            "business_partnering",
        ),
        nice_to_have_signals=("process_improvement", "financial_modeling"),
    ),
}


def get_role_profile(role_id: str) -> RoleProfile:
    raw = (role_id or "").strip().lower()
    key = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", raw)).strip("_")
    aliases = {
        "strategy_and_operations": "strategy_operations",
        "strategy_operations": "strategy_operations",
        "strategy": "strategy_operations",
        "product": "product_analyst",
    }
    key = aliases.get(key, key)
    if key not in ROLE_TEMPLATES:
        raise KeyError(f"Unknown role_template: {role_id!r}")
    return ROLE_TEMPLATES[key]


def list_role_template_ids() -> List[str]:
    return sorted(ROLE_TEMPLATES.keys())
