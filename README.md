# Dreamo Robot Torso SDK 🤖

**Reachy Mini is an open-source, expressive robot made for hackers and AI builders.**

## ⚡️ Build and start your own robot

### Prerequisites

- Ubuntu 24.04+
- Rust
- WebRTC Plugin

### Raspberry Pi swap

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

#### Ubuntu Dependencies

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