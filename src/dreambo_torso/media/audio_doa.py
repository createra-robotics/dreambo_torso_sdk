"""Direction of Arrival (DoA) estimation via the ReSpeaker microphone array.

This module wraps the ReSpeaker USB device to provide Direction of Arrival
readings.  It is used by ``GStreamerAudio`` and ``MediaManager`` to expose
DoA data without coupling it to a specific audio backend.

The spatial angle is given in radians:
    0 radians is left, π/2 radians is front/back, π radians is right.

Note:
    The microphone array requires firmware version 2.1.0 or higher.
    The firmware is located in ``src/reachy_mini/assets/firmware/*.bin``.
    Refer to https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/#update-firmware
    for the upgrade process.

"""

import logging
from typing import Optional

import usb.core

from dreambo_torso.media.audio_control_utils import ReSpeaker, init_respeaker_usb

logger = logging.getLogger(__name__)


class AudioDoA:
    """Direction of Arrival helper backed by a ReSpeaker USB device.

    Attributes:
        _respeaker: The underlying ReSpeaker device, or ``None`` if no
            compatible hardware was detected at init time.

    Example::

        doa = AudioDoA()
        result = doa.get_DoA()
        if result is not None:
            angle, speech = result
            print(f"Sound at {angle:.2f} rad, speech={speech}")
        doa.close()

    """

    def __init__(self) -> None:
        """Initialize the DoA helper, probing for a ReSpeaker USB device."""
        self._respeaker: Optional[ReSpeaker] = init_respeaker_usb()
        # Some XU316 ReSpeaker Lite firmwares STALL the XVF DoA control
        # transfer because they use a different vendor-tuning protocol than
        # the XVF3800 firmware this SDK was authored against. Track that
        # state so we stop hammering the device once we know it can't answer.
        self._doa_unsupported: bool = False

    def get_DoA(self) -> tuple[float, bool] | None:
        """Read the current Direction of Arrival from the ReSpeaker.

        Returns:
            A tuple ``(angle_radians, speech_detected)`` or ``None`` when
            the device is not available, the firmware does not expose DoA,
            or the read fails.

        """
        if not self._respeaker or self._doa_unsupported:
            return None

        try:
            result = self._respeaker.read("DOA_VALUE_RADIANS")
        except usb.core.USBError as e:
            # ERRNO 32 == LIBUSB_ERROR_PIPE (device STALLed the request) =>
            # firmware doesn't speak the XVF tuning protocol the dreambo_torso
            # SDK expects. Latch the flag so we don't spam the bus.
            self._doa_unsupported = True
            logging.getLogger(__name__).warning(
                "ReSpeaker firmware rejected the DoA vendor request "
                "(%s). Disabling DoA on this device.", e
            )
            return None
        except ValueError:
            # Read protocol error (unknown status byte). Treat the same way.
            self._doa_unsupported = True
            return None

        if result is None:
            return None
        return float(result[0]), bool(result[1])

    def close(self) -> None:
        """Release the USB resource."""
        if self._respeaker:
            self._respeaker.close()
            self._respeaker = None


def main() -> None:
    """Poll Direction of Arrival at ~10 Hz and print results."""
    import math
    import time

    logging.basicConfig(level=logging.INFO)

    doa = AudioDoA()
    if doa._respeaker is None:
        print("No ReSpeaker device found. Exiting.")
        return

    print("Reading DoA — press Ctrl+C to stop.\n")
    try:
        while True:
            result = doa.get_DoA()
            if result is not None:
                angle, speech = result
                print(
                    f"angle={math.degrees(angle):6.1f}°  "
                    f"({angle:.2f} rad)  "
                    f"speech={speech}"
                )
            else:
                print("no reading")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        doa.close()


if __name__ == "__main__":
    main()
