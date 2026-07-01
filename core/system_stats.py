"""Host CPU, memory, and active network name for the System Status tile."""

from __future__ import annotations

import platform
import socket
import subprocess
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

try:
    import psutil
except ImportError:  # pragma: no cover - optional until pip install completes
    psutil = None  # type: ignore

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NETWORK_CACHE_TTL_S = 60.0
_network_cache: str = "—"
_network_cache_ts: float = 0.0


@dataclass
class SystemStats:
    """Snapshot of CPU, RAM, and active connection name for the status tile."""

    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_detail: str = "—"
    network: str = "—"


def _gb(bytes_val: int) -> str:
    return f"{bytes_val / (1024 ** 3):.1f} GB"


def _check_internet(timeout_s: float = 1.2) -> bool:
    for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except OSError:
            continue
    return False


def _run_text(cmd: list[str], timeout_s: float = 3.0) -> str | None:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            return None
        text = proc.stdout.strip()
        return text or None
    except (OSError, subprocess.SubprocessError):
        return None


def _windows_wifi_ssid() -> str | None:
    out = _run_text(["netsh", "wlan", "show", "interfaces"])
    if not out:
        return None
    for line in out.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("ssid") and "bssid" not in lower:
            _, _, val = stripped.partition(":")
            val = val.strip()
            if val:
                return val
    return None


def _windows_connection_profile() -> str | None:
    script = (
        "(Get-NetConnectionProfile | Where-Object {"
        "$_.IPv4Connectivity -ne 'Disconnected' -or $_.IPv6Connectivity -ne 'Disconnected'"
        "} | Select-Object -First 1).Name"
    )
    return _run_text(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout_s=4.0,
    )


def _macos_connection_name() -> str | None:
    for iface in ("en0", "en1"):
        out = _run_text(["networksetup", "-getairportnetwork", iface])
        if out and "not associated" not in out.lower():
            _, _, val = out.partition(":")
            val = val.strip()
            if val:
                return val
    return None


def _linux_connection_name() -> str | None:
    out = _run_text(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
    if out:
        for line in out.splitlines():
            active, _, ssid = line.partition(":")
            if active == "yes" and ssid:
                return ssid
    out = _run_text(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active"])
    if out:
        for line in out.splitlines():
            name, _, typ = line.partition(":")
            if name and typ in ("802-3-ethernet", "ethernet", "wifi"):
                return name
    return None


def _read_connection_name() -> str | None:
    system = platform.system()
    if system == "Windows":
        return _windows_wifi_ssid() or _windows_connection_profile()
    if system == "Darwin":
        return _macos_connection_name()
    if system == "Linux":
        return _linux_connection_name()
    return None


def read_network_name() -> str:
    """Return the active Wi-Fi SSID or OS connection profile name (cached)."""
    global _network_cache, _network_cache_ts
    now = time.monotonic()
    if now - _network_cache_ts < _NETWORK_CACHE_TTL_S:
        return _network_cache

    name = _read_connection_name()
    if name:
        _network_cache = name
    elif _check_internet():
        _network_cache = "Internet"
    else:
        _network_cache = "Offline"
    _network_cache_ts = now
    return _network_cache


def read_system_stats() -> SystemStats:
    """Sample CPU/RAM (when psutil is available) and the active connection name."""
    network = read_network_name()

    if psutil is None:
        return SystemStats(network=network)

    cpu = float(psutil.cpu_percent(interval=None))
    mem = psutil.virtual_memory()
    ram_pct = float(mem.percent)
    ram_detail = f"{ram_pct:.1f}% · {_gb(mem.used)} / {_gb(mem.total)}"

    return SystemStats(
        cpu_percent=cpu,
        ram_percent=ram_pct,
        ram_detail=ram_detail,
        network=network,
    )


class SystemStatsWorker(QThread):
    """Sample host stats off the UI thread (network lookup may spawn subprocesses)."""

    stats_ready = Signal(object)

    def run(self) -> None:
        self.stats_ready.emit(read_system_stats())
