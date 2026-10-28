from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mib.common.sysinfo import hostname


@dataclass(frozen=True)
class WorkerConfig:
    hub_ws: str
    token: str
    worker_id: str
    data_dir: Path
    chromium: str | None
    http_concurrency: int


def load() -> WorkerConfig:
    hub_ws = os.environ.get("MIB_HUB_WS")
    token = os.environ.get("MIB_TOKEN")
    if not hub_ws or not token:
        raise SystemExit("MIB_HUB_WS and MIB_TOKEN must be set (see deploy/pi4/worker.env.example)")
    data_dir = Path(os.environ.get("MIB_DATA_DIR", "~/mib/data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    chromium = os.environ.get("MIB_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
    return WorkerConfig(
        hub_ws=hub_ws,
        token=token,
        worker_id=os.environ.get("MIB_WORKER_ID") or hostname(),
        data_dir=data_dir,
        chromium=chromium,
        http_concurrency=int(os.environ.get("MIB_HTTP_CONCURRENCY", "6")),
    )
