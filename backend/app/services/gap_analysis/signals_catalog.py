"""
Canonical capability signals for gap analysis (keyword-grounded; no invented employers).

Each signal maps to phrases searched in resume text; matching is deterministic.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, TypedDict


class SignalSpec(TypedDict):
    label: str
    keywords: Tuple[str, ...]
    """Heuristic: tool-like gaps often need portfolio depth."""
    tool_like: bool


SIGNAL_CATALOG: Dict[str, SignalSpec] = {
    "sql_data": {
        "label": "SQL / relational data querying",
        "keywords": (
            "sql",
            "tsql",
            "t-sql",
            "query",
            "queries",
            "join",
            "select",
            "database",
            "relational",
            "stored procedure",
        ),
        "tool_like": True,
    },
    "metrics_reporting": {
        "label": "Metrics, KPIs, and reporting",
        "keywords": (
            "kpi",
            "metrics",
            "dashboard",
            "reporting",
            "sla",
            "performance indicator",
            "scorecard",
        ),
        "tool_like": False,
    },
    "metrics_dashboards": {
        "label": "Dashboards and visualization",
        "keywords": (
            "dashboard",
            "power bi",
            "tableau",
            "visualization",
            "chart",
            "looker",
        ),
        "tool_like": True,
    },
    "reporting_dashboard_ownership": {
        "label": "Reporting / dashboard ownership",
        "keywords": (
            "owned the",
            "owned reporting",
            "report owner",
            "dashboard owner",
            "accountable for",
            "reporting pack",
            "executive deck",
            "board deck",
            "monthly business review",
            "metric pack",
        ),
        "tool_like": False,
    },
    "stakeholder_communication": {
        "label": "Stakeholder communication and alignment",
        "keywords": (
            "stakeholder",
            "executive",
            "alignment",
            "cross-functional",
            "cross functional",
            "business partner",
            "readout",
            "presentation",
        ),
        "tool_like": False,
    },
    "process_improvement": {
        "label": "Process improvement / operational efficiency",
        "keywords": (
            "process improvement",
            "operational excellence",
            "workflow",
            "streamline",
            "efficiency",
            "lean",
            "six sigma",
        ),
        "tool_like": False,
    },
    "workflow_optimization": {
        "label": "Workflow optimization and throughput",
        "keywords": (
            "workflow redesign",
            "bottleneck",
            "cycle time",
            "throughput",
            "handoff",
            "sla improvement",
            "queue",
            "backlog reduction",
        ),
        "tool_like": False,
    },
    "cross_functional_coordination": {
        "label": "Cross-functional program coordination",
        "keywords": (
            "program",
            "initiative",
            "cross-functional",
            "cross functional",
            "coordination",
            "roadmap",
            "rollout",
        ),
        "tool_like": False,
    },
    "executive_readouts": {
        "label": "Executive-facing updates and governance",
        "keywords": (
            "executive",
            "governance",
            "steerco",
            "steering",
            "qbr",
            "board",
            "leadership update",
            "escalation path",
            "decision forum",
        ),
        "tool_like": False,
    },
    "operating_cadence": {
        "label": "Operating cadence and business rhythm",
        "keywords": (
            "cadence",
            "weekly business review",
            "wbr",
            "operating plan",
            "business rhythm",
            "ops review",
            "operating review",
            "monthly operating",
        ),
        "tool_like": False,
    },
    "pilots_and_experiments": {
        "label": "Pilots, experiments, and phased rollouts",
        "keywords": (
            "pilot",
            "proof of concept",
            "poc",
            "phased rollout",
            "trial",
            "experiment",
            "canary",
            "beta program",
        ),
        "tool_like": False,
    },
    "financial_modeling": {
        "label": "Financial / unit-economics modeling",
        "keywords": (
            "financial model",
            "forecast",
            "budget",
            "variance",
            "unit economics",
            "p&l",
            "revenue model",
        ),
        "tool_like": False,
    },
    "vendor_management": {
        "label": "Vendor, procurement, and third-party management",
        "keywords": (
            "vendor",
            "third-party",
            "third party",
            "procurement",
            "sow",
            "contractor",
            "rfp",
            "purchase order",
            "supplier",
        ),
        "tool_like": False,
    },
    "product_discovery": {
        "label": "Product discovery and problem framing",
        "keywords": (
            "discovery",
            "problem statement",
            "hypothesis",
            "user problem",
            "product requirements",
            "prd",
            "use case",
        ),
        "tool_like": False,
    },
    "experimentation_ab": {
        "label": "Experimentation / A-B testing",
        "keywords": (
            "a/b",
            "ab test",
            "experiment",
            "randomized",
            "feature flag",
            "cohort analysis",
        ),
        "tool_like": True,
    },
    "user_research_signals": {
        "label": "User research and feedback loops",
        "keywords": (
            "user research",
            "interview",
            "usability",
            "survey",
            "feedback loop",
            "customer insight",
        ),
        "tool_like": False,
    },
    "roadmapping": {
        "label": "Roadmapping and prioritization",
        "keywords": (
            "roadmap",
            "prioritization",
            "backlog",
            "rice",
            "moscow",
            "okr",
        ),
        "tool_like": False,
    },
    "operational_excellence": {
        "label": "Operations rigor and service delivery",
        "keywords": (
            "operations",
            "operational",
            "runbook",
            "playbook",
            "service delivery",
            "incident",
            "on-call",
            "on call",
        ),
        "tool_like": False,
    },
    "reporting_automation": {
        "label": "Reporting automation and repeatable pipelines",
        "keywords": (
            "automation",
            "pipeline",
            "scheduled report",
            "etl",
            "job",
            "script",
            "python",
        ),
        "tool_like": True,
    },
    "business_partnering": {
        "label": "Business partnering and decision support",
        "keywords": (
            "business partner",
            "decision support",
            "ad hoc analysis",
            "what-if",
            "scenario",
            "business case",
        ),
        "tool_like": False,
    },
}


def list_signal_ids() -> List[str]:
    return sorted(SIGNAL_CATALOG.keys())
