# Dreamo Robot Torso SDK 🤖

**Reachy Mini is an open-source, expressive robot made for hackers and AI builders.**

## ⚡️ Build and start your own robot

### Prerequisites

- Ubuntu 24.04+
- Rust
- WebRTC Plugin

#### Ubuntu Dependencies

```bash
sudo sed -i 's|http://ports.ubuntu.com/ubuntu-ports|https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports|g' /etc/apt/sources.list.d/ubuntu.sources
sudo apt update
sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev gcc

sudo apt install -y gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav

sudo apt-get install \
    libgstreamer-plugins-bad1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer1.0-dev \
    libglib2.0-dev \
    libssl-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    libportaudio2 \
    libnice10 \
    gstreamer1.0-plugins-good \
    gstreamer1.0-alsa \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-nice \
    python3-gi \
    python3-gi-cairo
    
sudo apt install -y libpulse0 alsa-utils
````

#### Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

```bash
source .venv/bin/activate
pip install -e .
```

#### WebRTC Plugin

```bash
# Clone the GStreamer Rust plugins repository
git clone https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs.git
cd gst-plugins-rs
git checkout 0.14.1

# Install the cargo-c build tool
cargo install cargo-c

# Create installation directory
sudo mkdir -p /opt/gst-plugins-rs
sudo chown $USER /opt/gst-plugins-rs

# Build and install the WebRTC plugin (this may take several minutes)
cargo cinstall -p gst-plugin-webrtc --prefix=/opt/gst-plugins-rs --release

# Add plugin path to your environment
echo 'export GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/x86_64-linux-gnu:$GST_PLUGIN_PATH' >> ~/.bashrc
source ~/.bashrc
```

Note: For ARM64 systems (like Raspberry Pi), replace x86_64-linux-gnu with aarch64-linux-gnu in the export command.

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


---

## Mujuco Simulation

The MuJoCo **mujoco==3.3.0** extra must be installed:

```bash
uv sync --extra mujoco       # or: uv pip install 'mujoco==3.3.0'
```

```bash
# With the GUI viewer (recommended first time)
dreambo-daemon --sim --scene empty

# Headless (no viewer, just physics + WS server)
dreambo-daemon --sim --headless --scene empty

# Other built-in scene
dreambo-daemon --sim --scene minimal
```