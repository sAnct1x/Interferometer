"""Verify Thorlabs Kinesis and ThorCam dependencies on this PC."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Print environment check results and return exit code 0 or 1."""
    ok = True
    print("=== Thorlabs environment check ===\n")

    # 1) FTDI / Kinesis path (pyft232 -> ftd2xx.dll)
    print("1) FTDI D2XX (required for K-Cube / Kinesis over USB)")
    try:
        import ft232  # noqa: F401

        print("    OK: pyft232 (ft232) imports.\n")
    except Exception as e:
        ok = False
        print(f"    FAIL: {e}")
        print(
            "    Fix: Install FTDI D2XX drivers so ftd2xx.dll is available.\n"
            "         https://ftdichip.com/drivers/d2xx-drivers/\n"
            "    Thorlabs also ships a copy under Kinesis/APT; see pylablib docs.\n"
        )

    # 2) Kinesis enumeration
    print("2) Kinesis device list")
    try:
        from pylablib.devices import Thorlabs

        devs = Thorlabs.list_kinesis_devices()
        print(f"    OK: list_kinesis_devices() -> {devs if devs else '(none connected)'}\n")
    except Exception as e:
        ok = False
        print(f"    FAIL: {e}\n")

    # 3) ThorCam DLL folder (pylablib default)
    print("3) ThorCam SDK DLL folder (Scientific Imaging / ThorCam)")
    thorcam = Path(r"C:\Program Files\Thorlabs\Scientific Imaging\ThorCam")
    dll = thorcam / "thorlabs_tsi_camera_sdk.dll"
    if dll.is_file():
        print(f"    OK: found {dll}\n")
    else:
        ok = False
        print(f"    FAIL: expected camera SDK at:\n      {dll}")
        print(
            "    Fix: Install ThorCam / Scientific Imaging from Thorlabs (not only .NET runtime).\n"
            "         https://www.thorlabs.com/en/software-pages/thorcam/\n"
            "    pylablib loads thorlabs_tsi_camera_sdk.dll from that folder by default.\n"
        )

    # 4) TLCam list
    print("4) TLCam serial list")
    try:
        from pylablib.devices import Thorlabs

        cams = Thorlabs.list_cameras_tlcam()
        print(f"    OK: list_cameras_tlcam() -> {cams if cams else '(none connected)'}\n")
    except Exception as e:
        ok = False
        print(f"    FAIL: {e}\n")

    if ok:
        print("=== All checks passed (or devices simply unplugged). ===")
        return 0
    print("=== Some checks failed. Fix drivers/software above, then re-run. ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
