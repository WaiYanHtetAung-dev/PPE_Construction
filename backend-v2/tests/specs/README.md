# Acceptance-case specifications

Each `P<N>_ACCEPTANCE.md` is a **design/test checklist**, not an executable test suite. All scenarios are initially **Not run**, even Phase 1 cases which may overlap with already passing pytest tests, until someone records exact per-case evidence. Copy case ID into code test docstring when implemented and update status based on executed evidence. Keep real camera/network performance checks separate from mock-based tests.

Phase 1 runnable tests: `tests/test_api.py`, `tests/test_inference_contract.py`, `tests/test_phase1_safety.py`, `tests/test_contract_fixtures.py`, `tests/test_architecture_boundaries.py`.
