from pathlib import Path

from deal_intel.contracts.schemas import RunRequest
from deal_intel.control_plane.authorization import AuthorizationEngine


def test_authorized_owner_receives_fixture_scoped_capabilities() -> None:
    decision = AuthorizationEngine(Path("synthetic_data")).authorize(
        RunRequest(opportunity_id="OPP-1003", requester_id="USR-5003"),
        run_id="RUN-1",
    )

    assert decision.allowed
    assert len(decision.capabilities) == 3
    assert {capability.account_id for capability in decision.capabilities} == {"ACC-2003"}
    assert all(capability.can_view_restricted_account for capability in decision.capabilities)
    assert all(capability.can_view_sensitive_pricing for capability in decision.capabilities)
    assert all(capability.can_request_approval for capability in decision.capabilities)


def test_unauthorized_restricted_request_has_non_leaking_denial() -> None:
    decision = AuthorizationEngine(Path("synthetic_data")).authorize(
        RunRequest(opportunity_id="OPP-1003", requester_id="USR-5007"),
        run_id="RUN-2",
    )

    assert not decision.allowed
    assert decision.safe_reason == "access_denied"
    assert decision.capabilities == []
    assert decision.identity is None


def test_unknown_identifiers_use_same_safe_denial() -> None:
    engine = AuthorizationEngine(Path("synthetic_data"))
    unknown_user = engine.authorize(
        RunRequest(opportunity_id="OPP-1001", requester_id="USR-9999"),
        run_id="RUN-3",
    )
    unknown_opportunity = engine.authorize(
        RunRequest(opportunity_id="OPP-9999", requester_id="USR-5001"),
        run_id="RUN-4",
    )

    assert unknown_user.safe_reason == unknown_opportunity.safe_reason == "access_denied"
