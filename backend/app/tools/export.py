from pathlib import Path
from typing import Any


def report_export(report: dict[str, Any], run_id: str, export_dir: Path | None = None) -> dict[str, Any]:
    base = export_dir or Path(__file__).parent.parent.parent / "exports"
    base.mkdir(parents=True, exist_ok=True)
    title = report.get("title", "requirements-report").lower().replace(" ", "-")
    path = base / f"{run_id}-{title}.md"
    path.write_text(report.get("markdown", ""), encoding="utf-8")
    return {"format": "markdown", "path": str(path), "status": "exported"}
