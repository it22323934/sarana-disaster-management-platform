"""Domain rules for alerting-svc: CAP documents, templates, fan-out and delivery proof."""

from __future__ import annotations

from alerting_svc.domain.cap import (
    CAP_NAMESPACE,
    Area,
    CapAlert,
    CapInvalid,
    cap_case,
    parse_problems,
    to_xml,
    validate,
)
from alerting_svc.domain.delivery import (
    GAP_THRESHOLD,
    DeliverySummary,
    DivisionGap,
    DryRun,
    dry_run,
    fan_out,
    gaps,
    summarise,
)
from alerting_svc.domain.templates import (
    ALLOWED_PARAMETER_TYPES,
    RenderResult,
    ReviewIncomplete,
    TemplateInvalid,
    TemplateReview,
    assert_publishable,
    render,
    validate_template,
)

__all__ = [
    "ALLOWED_PARAMETER_TYPES",
    "CAP_NAMESPACE",
    "GAP_THRESHOLD",
    "Area",
    "CapAlert",
    "CapInvalid",
    "DeliverySummary",
    "DivisionGap",
    "DryRun",
    "RenderResult",
    "ReviewIncomplete",
    "TemplateInvalid",
    "TemplateReview",
    "assert_publishable",
    "cap_case",
    "dry_run",
    "fan_out",
    "gaps",
    "parse_problems",
    "render",
    "summarise",
    "to_xml",
    "validate",
    "validate_template",
]
