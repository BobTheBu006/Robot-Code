import glob
from dataclasses import dataclass


@dataclass
class SerialPortInfo:
    device: str
    description: str | None = None
    hardware_id: str | None = None
    serial_number: str | None = None


def list_serial_ports() -> list[SerialPortInfo]:
    """Enumerate currently connected USB-serial devices (ESP32 boards, etc.).

    Shared by the ESP32 builder (workspace/board identification) and the
    hardware map's dynamic-controller verification, so both agree on what
    "the device on /dev/ttyUSB0 right now" actually is.

    Simulated controllers appear alongside the real ones. Without that, none of
    the identity/preflight path could be exercised on a machine with no boards
    attached, which is every development machine.
    """
    simulated = _simulated_ports()
    if simulated:
        return simulated + _real_serial_ports()

    return _real_serial_ports()


def _simulated_ports() -> list[SerialPortInfo]:
    # Imported lazily so this module stays dependency-free for the drivers that
    # only want the real enumeration.
    from app.controllers.simulation import simulated_controllers

    return [
        SerialPortInfo(
            device=spec.device,
            description=spec.description,
            hardware_id=spec.hardware_id,
            serial_number=spec.serial_number,
        )
        for spec in simulated_controllers.specs()
    ]


def _real_serial_ports() -> list[SerialPortInfo]:
    try:
        from serial.tools import list_ports  # type: ignore

        ports = []
        for port in list_ports.comports():
            if not (str(port.device).startswith("/dev/ttyUSB") or str(port.device).startswith("/dev/ttyACM")):
                continue

            ports.append(
                SerialPortInfo(
                    device=str(port.device),
                    description=getattr(port, "description", None),
                    hardware_id=getattr(port, "hwid", None),
                    serial_number=getattr(port, "serial_number", None),
                )
            )

        if ports:
            return sorted(ports, key=lambda item: item.device)
    except Exception:
        pass

    fallback_ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    return [SerialPortInfo(device=port) for port in fallback_ports]
