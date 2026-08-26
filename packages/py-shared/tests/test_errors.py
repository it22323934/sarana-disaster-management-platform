from uuid import uuid4

from sarana_shared.errors import NotFound, ValidationFailed


def test_problem_detail_shape() -> None:
    err = NotFound("Incident INC-260901-K3F9QZ was not found", instance="/api/v1/incidents/123")
    correlation_id = uuid4()
    problem = err.to_problem_detail(correlation_id=correlation_id)

    assert problem.status == 404
    assert problem.type == "https://sarana.lk/errors/not-found"
    assert problem.title == "Not found"
    assert problem.detail == "Incident INC-260901-K3F9QZ was not found"
    assert problem.instance == "/api/v1/incidents/123"
    assert problem.correlation_id == correlation_id


def test_validation_failed_carries_field_errors() -> None:
    from sarana_shared.errors import FieldError

    err = ValidationFailed(
        "Entitlement exceeds schedule bound",
        errors=[FieldError(field="cost_estimate", code="above_cap")],
    )
    problem = err.to_problem_detail()
    assert problem.status == 422
    assert problem.errors[0].field == "cost_estimate"
    assert problem.errors[0].code == "above_cap"
    assert problem.correlation_id is None
