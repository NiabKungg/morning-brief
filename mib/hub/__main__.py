"""python -m mib.hub — serve the hub (API, live events, worker link, web UI) with uvicorn."""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run("mib.hub.api:create_app", factory=True, host=os.environ.get("MIB_BIND", "0.0.0.0"),
                port=int(os.environ.get("MIB_PORT", "8800")), log_level="info", access_log=False,
                ws_ping_interval=20, ws_ping_timeout=30)


if __name__ == "__main__":
    main()
