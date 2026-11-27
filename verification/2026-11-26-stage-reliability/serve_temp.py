"""Serve the real FastAPI app with isolated temporary stores for web E2E tests."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import uvicorn

from app.config import get_settings
from app.experiments.store import ExperimentStore
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2])
    root.mkdir(parents=True, exist_ok=True)
    settings = replace(
        get_settings(),
        data_dir=root,
        experiments_dir=root / "experiments",
    )
    app = create_app(
        settings=settings,
        process_store=ProcessStore(root / "processes"),
        reliability_store=ReliabilityStore(root / "reliability"),
        experiment_store=ExperimentStore(root / "experiments"),
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
