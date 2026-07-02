# Dreamo Robot Torso SDK 🤖

**Dreambo robot is an open-source, expressive robot made for hackers and AI builders.**

## ⚡️ Build and start your own robot

### Prerequisites

- Ubuntu 24.04+
- Rust
- WebRTC Plugin

### System swap

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

## Ubuntu Dependencies

### Ubuntu 24.04

```bash
sudo sed -i 's|http://ports.ubuntu.com/ubuntu-ports|https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports|g' /etc/apt/sources.list.d/ubuntu.sources
sudo apt update
sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev gcc

# Optional (Do not do this until new confirmation)
sudo apt install \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-ugly \
    libgstreamer-plugins-bad1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer1.0-dev \
    libglib2.0-dev \
    libssl-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    libportaudio2 \
    libnice10 \
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-tools \
    gstreamer1.0-plugins-good \
    gstreamer1.0-alsa \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-nice \
    python3-gi \
    python3-gi-cairo
    
sudo apt install -y libpulse0 alsa-utils
sudo apt install -y pipewire pipewire-pulse wireplumber pulseaudio-utils

# Used for audio device debug
sudo apt install gstreamer1.0-plugins-base-apps
#example: gst-device-monitor-1.0 Audio/Source 2>&1 | head -80
````

### Ubuntu 22.04

No support

---

#### Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```
Change Rust toolchain via USTC mirror

```bash
mkdir -p ~/.cargo
```

```bash
sudo nano ~/.cargo/config.toml
```

```toml
[source.crates-io]
replace-with = "ustc"
[source.ustc]
registry = "sparse+https://mirrors.ustc.edu.cn/crates.io-index/"
```

```bash
cargo install cargo-c
```

Cargo defaults to crates.io when no config.toml exists. If you want to revert to the official `crates.io`, just remove:

```bash
rm ~/.cargo/config.toml
```

#### UV

```bash
source .venv/bin/activate
pip install -e .
```

#### WebRTC Plugin

```bash
# Clone the GStreamer Rust plugins repository
git clone https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs.git ~/gst-plugins-rs
cd ~/gst-plugins-rs
git checkout 0.14.4
cargo clean

# Install the cargo-c build tool
cargo install cargo-c

# Create installation directory
sudo mkdir -p /opt/gst-plugins-rs
sudo chown $USER /opt/gst-plugins-rs

# Build and install the WebRTC plugin (this may take several minutes)
cargo cinstall -p gst-plugin-webrtc --prefix=/opt/gst-plugins-rs --release

# or build with LTO off and a single parallel job (lower peak memory)
CARGO_PROFILE_RELEASE_LTO=false CARGO_BUILD_JOBS=1 \
      cargo cinstall -p gst-plugin-webrtc \
      --prefix=/opt/gst-plugins-rs --release

# Add plugin path to your environment
echo 'export GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/aarch64-linux-gnu/gstreamer-1.0:$GST_PLUGIN_PATH' >> ~/.bashrc
source ~/.bashrc

# Confirm the plugin loads
gst-inspect-1.0 rswebrtc
gst-inspect-1.0 webrtcsink | grep -E "run-signalling-server"
gst-inspect-1.0 webrtcsink | head -5 # return: gst-inspect-1.0 webrtcsink should now print Factory Details: and Rank: primary.
```

Note: For **X86_64** systems (like Ubuntu PC), replace `aarch64-linux-gnu` with `x86_64-linux-gnu` in the export command.

#### Verify Installation

Finally, you can test your GStreamer installation as follows:

```bash
# install the optional tools
sudo apt install gstreamer1.0-tools

# Check version
gst-launch-1.0 --version

# Test basic functionalities
gst-launch-1.0 videotestsrc ! autovideosink

# Verify WebRTC plugin
gst-inspect-1.0 webrtcsrc
```

You should also be able to import GStreamer libraries in a Python environment:

```bash
python -c "import gi"
```

#### Audio

# 1. Install the full stack

```bash
sudo apt install -y pipewire pipewire-pulse wireplumber
```

# 2. Start the user services right now (no logout needed)
systemctl --user enable --now pipewire pipewire-pulse wireplumber

# 3. Verify everything is up
systemctl --user status pipewire pipewire-pulse wireplumber --no-pager | head -30

# 4. Confirm Pulse compat is alive — should say "Server Name: PulseAudio (on PipeWire ...)"
pactl info | head -5

# 5. Confirm GStreamer now sees the device with rich properties
gst-device-monitor-1.0 Audio/Source 2>&1 | grep -E 'name|node.name|alsa.card_name' | head -10

You should now see node.name = alsa_input.usb-Seeed_Studio_ReSpeaker_Lite... in step 5 — that's
the property the original code path expected. The client-rt.conf warning should be gone too (its
config file now ships with the pipewire package).

#### Audio Device Permission

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", MODE="0666"' | sudo tee /etc/udev/rules.d/60-respeaker.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the ReSpeaker Lite. Confirm

```bash
ls -la /dev/bus/usb/$(lsusb | grep 2886 | awk '{printf "%03d/%03d", $2, $4}' | tr -d ':')
# Expected: crw-rw-rw- (mode 0666) — readable/writable by everyone
```

Restart dreambo-torso-daemon

---

## Customize Video Devices

1. Run `gst-device-monitor-1.0 Video/Source` to confirm the exact display-name string and edit `src/dreambo_torso/media/device_detection.py`:

```python
DEFAULT_CAM_NAMES: Sequence[str] = ("USB Camera", "Arducam_12MP", "imx708")
DEFAULT_AUDIO_TARGET: Tuple[str, ...] = ("ReSpeaker",)
```

2. For camera, edit VID|PID from `src/dreambo_torso/media/camera_constants.py`:

```python
class DreamboTorsoCameraSpecs(CameraSpecs):
    """Dreambo Torso camera specifications."""

    name = "lite"
    available_resolutions = [
        CameraResolution.R1920x1080at60fps,
        CameraResolution.R3840x2592at30fps,
        CameraResolution.R3840x2160at30fps,
        CameraResolution.R3264x2448at30fps,
    ]
    default_resolution = CameraResolution.R1920x1080at60fps
    # HZ USB Camera (Bus 002 Device 002: ID 0ede:8093)
    vid = 0x0EDE
    pid = 0x8093
```

If a new camera still doesn't appear, run `gst-device-monitor-1.0 Video/Source` to confirm the exact display-name string
  GStreamer reports — it must contain the substring USB Camera for the match to fire.

---

## Audio Device Customizations

1. Run the following command to confirm the exact display-name string

```bash
gst-device-monitor-1.0 Audio/Source 2>/dev/null | grep -E "^\s*(name|class|node\.name|device\.api|api\.alsa\.card\.name|device\.product\.name)"
```

2. Run the `lsusb` command to find out VID:PID:

```bash
lsusb | grep -iE "seeed|xmos|respeaker|xvf"

# return
Bus 004 Device 002: ID 2886:001e Seeed Technology Co., Ltd. reSpeaker Flex XVF3800 C16K6Ch
```

---

## Calibration

1. Calibrate servos by running the following command for example:

```bash
python -m dreambo_torso.tools.calibrate_motor left_arm_pitch
```

2. Write new parameters into servo's EEPROM:

```bash
python -m dreambo_torso.tools.setup_motor  src/dreambo_torso/assets/config/hardware_config.yaml left_arm_pitch /dev/ttyACM0 --update-config
```

---

## Mujuco Simulation

The MuJoCo **mujoco==3.3.0** extra must be installed:

```bash
uv sync --extra mujoco       # or: uv pip install 'mujoco==3.3.0'
```

```bash
# With the GUI viewer (recommended first time)
dreambo-torso-daemon --sim --scene empty

# Headless (no viewer, just physics + WS server)
dreambo-torso-daemon --sim --headless --scene empty

# Other built-in scene
dreambo-torso-daemon --sim --scene minimal
```

---

## Launch Dreambo torsor Daemon

```bash
DREAMBO_DISABLE_AUDIO=1 dreambo-torso-daemon

#Or export it once for the session:
export DREAMBO_DISABLE_AUDIO=1
```

---

## Motion Library

Pre-recorded emotion clips are hosted on the
[`tonylabs/dreambo-emotions-library`](https://www.modelscope.cn/datasets/tonylabs/dreambo-emotions-library)
dataset on ModelScope. Each clip is a per-frame trajectory JSON paired
with an audio cue WAV of the same basename (`yes1.json` ↔ `yes1.wav`).
The SDK loads them via `dreambo_torso.motion.recorded_move.RecordedMoves`,
which resolves the JSON–WAV pairing client-side at playback time.

### Startup prefetch, then local-only playback

When the daemon finishes starting up it spawns a background thread that
calls `prefetch_dataset(DEFAULT_EMOTION_LIBRARY)` — a content-addressed
refresh against ModelScope's `master` revision. Unchanged blobs stay on
disk; only new or modified files cross the network. The refresh runs
out of band, so daemon readiness is not delayed.

Once the prefetch completes (typically a couple of seconds for a
no-change refresh), every subsequent

- `GET /api/move/recorded-move-datasets/list/{dataset}`
- `POST /api/move/play/recorded-move-dataset/{dataset}/{clip}`

resolves **only from the local cache** — `RecordedMoves` never touches
the network on construction. Play buttons stay responsive.

The local snapshot lives at
`~/.cache/modelscope/hub/datasets/<namespace>/<dataset>/`. If the Pi is
offline at daemon launch, the prefetch logs a warning and the daemon
serves whatever the cache already has. The first-ever launch on a fresh
machine still has a fallback path: if no cache exists, `RecordedMoves`
performs a one-time bootstrap fetch on first request.

**Net effect for operators**: record a new clip with
`scripts/emotion_library/record.py` → push lands on ModelScope → restart
the consumer daemon → it pulls the change at startup → play button
serves the new clip from disk on the next click.

### Recording new clips

New emotion clips are captured by hand-puppeteering the arms while
`scripts/emotion_library/record.py` samples the servo positions at
100 Hz, then auto-pushes the resulting JSON to ModelScope. Run it on
the Pi connected to the robot.

#### Prerequisites

- The Feetech serial bus and CAN interface that the daemon uses must be
  available (`/dev/ttyACM0` and `can0` are the defaults). The recorder talks to the motor controller
  directly, so **stop the daemon first** — the two cannot share the
  same serial port.
- A ModelScope access token from
  https://www.modelscope.cn/my/myaccesstoken with write scope on the
  target dataset. Drop it into the repo-local `.env` file (template at
  `.env.example`):

  ```dotenv
  MODELSCOPE_API_TOKEN=ms-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  ```

  The recorder loads `.env` automatically; no shell export needed.

#### Capture a single clip

```bash
uv run python scripts/emotion_library/record.py \
    --emotion yes2 \
    --description "A short affirmative — single nod, arms steady." \
    --play-wav
```

What happens, in order:

1. Connects to the motor controller and disables arm + nose torque so
   the joints go limp. Neck is untouched.
2. Prints a 3-second countdown. Position the arms / nose in their
   starting pose during this window.
3. Starts sampling at 100 Hz. The matching audio cue (e.g. `yes2.wav`
   from `scripts/emotion_library/sound/`) plays once at the start when
   `--play-wav` is set.
4. **Press `r`** to stop and save; **press `q`** to abort. A 60-second
   safety cap stops the recording automatically if neither key is
   pressed.
5. Computes upper-arm direction vectors via the spherical-5-bar FK and
   writes the JSON to `scripts/emotion_library/dataset/<emotion>.json`
   in the schema documented in
   [`src/dreambo_torso/motion/recorded_move.py`](src/dreambo_torso/motion/recorded_move.py).
   If any frame's FK fails, the recorder falls back to saving raw
   `(theta_a, theta_b)` joints and prints a hint.
6. Re-enables arm + nose torque so the daemon comes back up in a
   playable state.
7. Pushes the JSON to `tonylabs/dreambo-emotions-library` on ModelScope
   (skip with `--no-upload` to keep the recording local).

#### Useful flags

| Flag                       | Default                                | Purpose                                             |
| -------------------------- | -------------------------------------- | --------------------------------------------------- |
| `--emotion <name>`         | required                               | Clip name (also the JSON / WAV basename).            |
| `--description "..."`      | empty, or read from existing JSON      | Human-readable caption stored in the row.            |
| `--play-wav`               | off                                    | Play the matching `.wav` cue at start.               |
| `--no-upload`              | off                                    | Skip the ModelScope push; keep the JSON local only.  |
| `--max-duration <seconds>` | 60                                     | Safety cap on the recording length.                  |
| `--fps <hz>`               | 100                                    | Sampling rate.                                       |
| `--keep-torque`            | off                                    | Skip the torque-off step (headless dry-runs).        |
| `--dry-run`                | off                                    | Print a summary but do not write the JSON.           |

If a JSON with the target name already exists locally and `--description`
isn't supplied, the recorder reuses the existing description so you can
re-record a clip without retyping the caption.

#### After recording

The clip is in the cloud, but consumer daemons that are already running
will keep serving their cached snapshot — `RecordedMoves` never touches
the network once a cache exists. To propagate the new clip:

```bash
# on each consumer Pi
systemctl --user restart dreambo-torso-daemon   # or however you launch it
```

The startup prefetch on the next daemon launch pulls the change and the
new clip becomes available on the very first play-button click. No
manual `rm -rf ~/.cache/...` needed.


