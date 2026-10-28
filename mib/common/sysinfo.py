"""Lightweight Raspberry Pi health metrics read straight from /proc and /sys."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path


def board_model() -> str:
    try:
        return Path("/proc/device-tree/model").read_text().rstrip("\x00").strip()
    except OSError:
        return os.uname().machine


def hostname() -> str:
    return socket.gethostname()


class SysSampler:
    """Call ``sample()`` periodically; CPU % is computed from the delta since the last call."""

    def __init__(self) -> None:
        self._last_cpu: tuple[int, int] | None = None
        self._throttled: str | None = None
        self._throttled_at = 0.0
        self._vcgencmd = shutil.which("vcgencmd")

    def _cpu_pct(self) -> float | None:
        try:
            fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        except OSError:
            return None
        values = [int(v) for v in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        last, self._last_cpu = self._last_cpu, (idle, total)
        if not last or total == last[1]:
            return None
        return round(100.0 * (1 - (idle - last[0]) / (total - last[1])), 1)

    def _throttled_state(self) -> str | None:
        if not self._vcgencmd or time.monotonic() - self._throttled_at < 60:
            return self._throttled
        self._throttled_at = time.monotonic()
        try:
            out = subprocess.run([self._vcgencmd, "get_throttled"], capture_output=True, text=True, timeout=2).stdout
            self._throttled = out.strip().split("=", 1)[-1] or None
        except (OSError, subprocess.SubprocessError):
            self._throttled = None
        return self._throttled

    def sample(self) -> dict:
        mem: dict[str, int] = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, _, rest = line.partition(":")
                mem[key] = int(rest.split()[0]) * 1024
        except OSError:
            pass
        total = mem.get("MemTotal", 0)
        used = total - mem.get("MemAvailable", total)
        try:
            temp = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
        except (OSError, ValueError):
            temp = None
        disk = shutil.disk_usage("/")
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except OSError:
            uptime = None
        return {
            "cpu_pct": self._cpu_pct(),
            "load": [round(x, 2) for x in os.getloadavg()],
            "mem_used": used,
            "mem_total": total,
            "temp_c": temp,
            "disk_used": disk.used,
            "disk_total": disk.total,
            "uptime_s": int(uptime) if uptime is not None else None,
            "throttled": self._throttled_state(),
        }
