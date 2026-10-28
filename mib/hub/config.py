from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from mib.common.timeutil import local_zone


@dataclass(frozen=True)
class HubConfig:
    data_dir: Path
    bind: str
    port: int
    token: str
    llm_url: str
    llm_model: str
    tz: ZoneInfo


def load() -> HubConfig:
    token = os.environ.get("MIB_TOKEN")
    if not token:
        raise SystemExit("MIB_TOKEN must be set (shared secret for the worker, see deploy/pi5/hub.env.example)")
    data_dir = Path(os.environ.get("MIB_DATA_DIR", "~/mib/data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return HubConfig(
        data_dir=data_dir,
        bind=os.environ.get("MIB_BIND", "0.0.0.0"),
        port=int(os.environ.get("MIB_PORT", "8800")),
        token=token,
        llm_url=os.environ.get("MIB_LLM_URL", "http://127.0.0.1:8081").rstrip("/"),
        llm_model=os.environ.get("MIB_LLM_MODEL", "LFM3-1.7B-QAD-Q4_0"),
        tz=local_zone(),
    )
