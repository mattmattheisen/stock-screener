from datetime import date

from app.scripts.rebuild_market_breadth import (
    EXIT_CONFIRMATION_REQUIRED,
    EXIT_VALIDATION_REQUIRED,
    main,
)


class _FakeRebuildService:
    def __init__(self, *, valid: bool = False) -> None:
        self.valid = valid
        self.calls: list[tuple] = []

    def build(self, **kwargs):
        self.calls.append(("build", kwargs))
        return {"processed": 1}

    def validate(self, **kwargs):
        self.calls.append(("validate", kwargs))
        return {"valid": self.valid, "errors": [] if self.valid else ["invalid"]}

    def activate(self):
        self.calls.append(("activate", {}))
        return {"activated": 1}

    def cleanup(self):
        self.calls.append(("cleanup", {}))


def test_activate_requires_explicit_confirmation():
    service = _FakeRebuildService(valid=True)

    result = main(["activate"], service_factory=lambda: service)

    assert result == EXIT_CONFIRMATION_REQUIRED
    assert service.calls == []


def test_activate_refuses_unvalidated_staging_data():
    service = _FakeRebuildService(valid=False)

    assert (
        main(
            ["activate", "--confirm-replace"],
            service_factory=lambda: service,
        )
        == EXIT_VALIDATION_REQUIRED
    )
    assert [call[0] for call in service.calls] == ["validate"]


def test_build_dispatches_market_and_date_range():
    service = _FakeRebuildService()

    result = main(
        ["build", "--market", "US", "--start-date", "2026-01-01"],
        service_factory=lambda: service,
    )

    assert result == 0
    assert service.calls[0][0] == "build"
    assert service.calls[0][1]["markets"] == ("US",)
    assert service.calls[0][1]["start_date"] == date(2026, 1, 1)
