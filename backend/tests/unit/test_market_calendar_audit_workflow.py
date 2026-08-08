from pathlib import Path

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _workflow():
    return yaml.safe_load(
        (_PROJECT_ROOT / ".github/workflows/market-calendar-audit.yml").read_text(
            encoding="utf-8"
        )
    )


def test_calendar_audit_workflow_runs_weekly_and_manually():
    workflow = _workflow()
    triggers = workflow.get("on") or workflow.get(True)

    assert "workflow_dispatch" in triggers
    assert len(triggers["schedule"]) == 1
    assert triggers["schedule"][0]["cron"] == "10 7 * * 6"


def test_calendar_audit_installs_pinned_dependencies_and_keeps_warnings_nonblocking():
    workflow = _workflow()
    job = workflow["jobs"]["audit"]
    steps = job["steps"]
    rendered = str(steps)

    assert "backend/requirements.txt" in rendered
    assert "app.scripts.audit_market_calendars --github-actions" in rendered
    assert "app.scripts.build_market_calendar_data --check" in rendered
    assert "::warning::Market calendar generation drift detected" in rendered
    assert "if ! DRIFT_OUTPUT=" in rendered
    audit_step = next(
        step for step in steps if "app.scripts.audit_market_calendars" in step.get("run", "")
    )
    assert "continue-on-error" not in audit_step
    assert "if" not in audit_step
