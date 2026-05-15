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
import math
from typing import Callable, Optional

import usb.core

from dreambo_torso.media.audio_control_utils import ReSpeaker, init_respeaker_usb

logger = logging.getLogger(__name__)

# DoA reader: takes the raw response list and returns (angle_rad, speech).
# Returning None signals "this firmware doesn't speak this variant", so the
# probe loop should move on to the next reader.
DoAReader = Callable[[list], Optional[tuple[float, bool]]]


def _read_radians_variant(result: list) -> Optional[tuple[float, bool]]:
    # Older Reachy Mini Audio (38FB:1001) firmware: cmdid 19 returns
    # (angle_radians: float, speech_detected: float-as-bool).
    if result is None or len(result) < 2:
        return None
    return float(result[0]), bool(result[1])


def _read_degrees_variant(result: list) -> Optional[tuple[float, bool]]:
    # XVF3800 firmware (2886:001E and friends): cmdid 18 returns two
    # little-endian uint16 values; the first is degrees, the second
    # carries the speech-detected flag in its low byte.
    if result is None or len(result) < 2:
        return None
    return math.radians(int(result[0])), bool(int(result[1]) & 0xFF)


# Ordered list of (PARAMETERS key, decoder). The first entry that the
# firmware accepts wins and is cached for subsequent reads. We try the
# radian variant first so older firmware that supports both still gets
# the higher-precision native-radian answer.
_DOA_VARIANTS: tuple[tuple[str, DoAReader], ...] = (
    ("DOA_VALUE_RADIANS", _read_radians_variant),
    ("DOA_VALUE", _read_degrees_variant),
)


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
        # Cached (parameter_name, decoder) chosen on the first successful
        # read. ``None`` means "not yet probed". If every variant fails
        # ``_doa_unsupported`` is latched so we don't spam the bus.
        self._doa_variant: Optional[tuple[str, DoAReader]] = None
        self._doa_unsupported: bool = False

    def _try_variant(
        self, name: str, decoder: DoAReader
    ) -> Optional[tuple[float, bool]]:
        """Issue one read with *name* and return its decoded reading, or None."""
        assert self._respeaker is not None
        try:
            raw = self._respeaker.read(name)
        except usb.core.USBError:
            # LIBUSB_ERROR_PIPE = firmware STALLed (variant not implemented).
            return None
        except ValueError:
            # Unknown status byte from the device protocol.
            return None
        return decoder(raw)

    def get_DoA(self) -> tuple[float, bool] | None:
        """Read the current Direction of Arrival from the ReSpeaker.

        Returns:
            A tuple ``(angle_radians, speech_detected)`` or ``None`` when
            the device is not available, the firmware does not expose DoA,
            or the read fails.

        """
        if not self._respeaker or self._doa_unsupported:
            return None

        # Fast path: we've already discovered which variant this firmware
        # speaks. Reuse it without probing.
        if self._doa_variant is not None:
            name, decoder = self._doa_variant
            return self._try_variant(name, decoder)

        # Cold path: probe each variant until one returns a reading.
        for name, decoder in _DOA_VARIANTS:
            reading = self._try_variant(name, decoder)
            if reading is not None:
                self._doa_variant = (name, decoder)
                logger.info(
                    "ReSpeaker DoA protocol resolved to %s.", name
                )
                return reading

        # No variant worked — disable to avoid hammering the bus.
        self._doa_unsupported = True
        logger.warning(
            "ReSpeaker firmware did not respond to any known DoA vendor "
            "request. Disabling DoA on this device."
        )
        return None

    def close(self) -> None:
        """Release the USB resource."""
        if self._respeaker:
            self._respeaker.close()
            self._respeaker = None


def main() -> None:
    """Poll Direction of Arrival at ~10 Hz and print results."""
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
