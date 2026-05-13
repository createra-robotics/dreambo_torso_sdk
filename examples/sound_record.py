"""Dreambo sound recording example.

The output audio will be saved to 'recorded_audio.wav' in the current
working directory (i.e. wherever you launched the script from, not the
examples/ folder).

Playback (after recording):

    sudo apt install pulseaudio-utils

    # PipeWire / PulseAudio — recommended, routes through your normal audio stack
    paplay recorded_audio.wav

    # ALSA — bypasses session audio, uses the kernel ALSA layer directly
    aplay recorded_audio.wav

    # GStreamer — useful if the file's format is non-standard
    gst-play-1.0 recorded_audio.wav

    # Full media player with controls
    mpv recorded_audio.wav
    # or
    ffplay -autoexit recorded_audio.wav

    # Open in the desktop's default audio app
    xdg-open recorded_audio.wav
"""

import argparse
import time

import numpy as np

from dreambo_torso import Dreambo
from dreambo_torso.media.audio_utils import save_audio_to_wav

TIMEOUT = 10
DURATION = 10  # seconds
OUTPUT_FILE = "recorded_audio.wav"


def main(backend: str) -> None:
    """Record audio for 5 seconds and save to a WAV file."""
    with Dreambo(log_level="INFO", media_backend=backend) as mini:
        audio_samples = []
        mini.media.start_recording()

        # Wait to actually get an audio sample
        print("Waiting for the microphone to be ready...")
        start_time = time.time()
        while (
            mini.media.get_audio_sample() is None and time.time() - start_time < TIMEOUT
        ):
            time.sleep(0.005)

        if time.time() - start_time >= TIMEOUT:
            print(f"Timeout: the microphone did not respond in {TIMEOUT} seconds.")
            return

        print(f"Recording for {DURATION} seconds...")

        start_time = time.time()
        while time.time() - start_time < DURATION:
            sample = mini.media.get_audio_sample()
            if sample is not None:
                audio_samples.append(sample)

        mini.media.stop_recording()

        # Concatenate all samples and save
        if audio_samples:
            audio_data = np.concatenate(audio_samples, axis=0)
            samplerate = mini.media.get_input_audio_samplerate()
            save_audio_to_wav(audio_data, samplerate, OUTPUT_FILE)
            print(f"Audio saved to {OUTPUT_FILE}")
        else:
            print("No audio data recorded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Records audio from Dreambo's microphone."
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["default", "local", "webrtc"],
        default="default",
        help="Media backend to use.",
    )

    args = parser.parse_args()
    main(backend=args.backend)

# END doc_example
