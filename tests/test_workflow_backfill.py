from pathlib import Path


def test_distributed_backfill_workflow_extends_synthesize_timeout():
    workflow = Path(".github/workflows/backfill-distributed.yml").read_text(
        encoding="utf-8"
    )

    assert "synthesize:\n" in workflow
    assert "timeout-minutes: 840" in workflow
