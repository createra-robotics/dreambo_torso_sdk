# ReSpeaker

## Versions
- The ReSpeaker Lite with no XIAO versions (107990273) come with factory-installed USB audio firmware.
- The ReSpeaker Lite with XIAO ESP32S3 versions (110061601) come with factory-installed I2S firmware for MCU integration.

The Dreambo Torso SDK is using the reSpeaker Lite with XIAO ESP32S3

## Features

- **Dual Microphone Array for Far-Field Voice Capture:** The 2 high performance digital microphones capture and extract far-field speech and voice (up to 3 meters) even in noisy environments as it cancels point noise using two microphone input.
- **Onboard Audio front-end Algorithms:** Powered by XMOS XU-316 AI sound and audio chip, the kit includes Natural Language Understanding algorithms for Interference Cancellation (IC) , Acoustic Echo Cancellation, Noise Suppression, Voice-to-Noise Ratio (VNR), and Automatic Gain Control (AGC), enabling high quality voice capture.
- **Embracing Open Source:** This board is compatible with popular hardware platforms (XIAO ESP32S3 (Sense), Adafruit QT Py) via I2S, and compatible with Raspberry Pi, PC via USB (Audio Class 2.0 (UAC2)).
- **Onboard RGB LED:** The board features a programmable WS2812 RGB LED, supporting custom effects and offering a visual interface for your applications.
External Power Supply Support: this board supports external 5V power supply, which can be flexibly applied in different scenarios.
DFU for Custom Development: the board supports custom firmware update via DFU-Util.

## Specifications

---

## Firmware

1. Connect the ReSpeaker Lite Board to your PC via the USB cable. Note that you need to use the XMOS USB-C port(close to 3.5mm jack port) to flash XMOS’s firmware.
2. Install DFU Util:

`dfu-util` is a command line tool for Device Firmware Upgrade via USB port.

### On Windows

* Download `dfu-util-0.11-binaries.tar.xz` and extract it to your local system, e.g., `D:\`
* Change directory to the dfu-util.exe, e.g., `D:\dfu-util-0.11-binaries\win64\`(if you are using win32, please change win64 to win32)
* Append the path of the dfu-util.exe to the system environment variable Path: "My Computer" > "Properties" > "Advanced" > "Environment Variables" > "Path". Please note that paths in the variable Path are separated by semicolon ;. This will allow dfu-util to be executed globally in command prompt.
* Open the start menu and type cmd. Press the enter key. In the terminal that comes up, check if dfu-util.exe path is set with dfu-util -V command:

```shell
C:\Users\yiping>dfu-util -V
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2021 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/
```

* Run `dfu-util -l` to check if ReSpeaker Lite is detected:

```shell
C:\Users\yiping>dfu-util -l
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2021 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/

Found DFU: [2886:0019] ver=0205, devnum=9, cfg=1, intf=0, path="1-1.4.1", alt=2, name="DFU DATAPARTITION", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=9, cfg=1, intf=0, path="1-1.4.1", alt=1, name="DFU UPGRADE", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=9, cfg=1, intf=0, path="1-1.4.1", alt=0, name="DFU FACTORY", serial="0000000001"
```

If you get a "Cannot open DFU device" error like this, please keep following this step. If not, please go to Step 3 to flash firmware.

```shell
C:\Users\yiping>dfu-util -l
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2021 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/

Cannot open DFU device 2886:0019 found on devnum 9 (LIBUSB_ERROR_NOT_SUPPORTED)
```

Install [Zadig](https://zadig.akeo.ie) and open it. Click "Options"->"List All Devices".

Find "ReSpeaker 2 Mics Array" or "ReSpeaker Lite" or "DFU FACTORY (Interface 3)" from the device list, install WINUSB v6.x.xxxx.xxxxx driver.

After installation is completed(that will take a few minutes), please do power-cycle and run `dfu-util -l` again, ReSpeaker Lite should be detected right now.

### macOS

* Install `dfu-util` with brew: `brew install dfu-util`

* Run `dfu-util -l` to check if ReSpeaker Lite is detected:

```bash
$ sudo dfu-util -l
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2021 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/

Found DFU: [2886:0019] ver=0205, devnum=1, cfg=1, intf=3, path="1-1", alt=2, name="DFU DATAPARTITION", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=1, cfg=1, intf=3, path="1-1", alt=1, name="DFU UPGRADE", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=1, cfg=1, intf=3, path="1-1", alt=0, name="DFU FACTORY", serial="0000000001"
```

### Linux

* Install `dfu-util` with apt: `sudo apt install dfu-util`
* Run sudo `sudo dfu-util -l` to check if ReSpeaker Lite is detected:

```bash
$ sudo dfu-util -l
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2016 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/

Found DFU: [2886:0019] ver=0205, devnum=5, cfg=1, intf=3, path="1-1.1", alt=2, name="DFU DATAPARTITION", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=5, cfg=1, intf=3, path="1-1.1", alt=1, name="DFU UPGRADE", serial="0000000001"
Found DFU: [2886:0019] ver=0205, devnum=5, cfg=1, intf=3, path="1-1.1", alt=0, name="DFU FACTORY", serial="0000000001"
```

### Flash Firmware

#### Windows

```shell
C:\Users\Tony>dfu-util -R -e -a 1 -D D:\Downloads\respeaker_lite_i2s_dfu_firmware_v1.0.7.bin

# Return
dfu-util 0.11

Copyright 2005-2009 Weston Schmidt, Harald Welte and OpenMoko Inc.
Copyright 2010-2021 Tormod Volden and Stefan Schmidt
This program is Free Software and has ABSOLUTELY NO WARRANTY
Please report bugs to http://sourceforge.net/p/dfu-util/tickets/

Warning: Invalid DFU suffix signature
A valid DFU suffix will be required in a future dfu-util release
Opening DFU capable USB device...
Device ID 2886:0019
Device DFU version 0101
Claiming USB DFU Interface...
Setting Alternate Interface #1 ...
Determining device status...
DFU state(2) = dfuIDLE, status(0) = No error condition is present
DFU mode device DFU version 0101
Device returned transfer size 4096
Copying data from PC to DFU device
Download        [=========================] 100%       270336 bytes
Download done.
DFU state(7) = dfuMANIFEST, status(0) = No error condition is present
DFU state(2) = dfuIDLE, status(0) = No error condition is present
Done!
Resetting USB to switch back to Run-Time mode
```
* On Linux please run `sudo dfu-util -R -e -a 1 -D /path/to/dfu_firmware.bin`

After flashing is completed, please restart the board.
Check the current firmware version on ReSpeaker Lite `dfu-util -l`:

### Troubleshooting

> Can't detect ReSpeaker Lite USB sound card on Windows after flashing USB firmware?

Open the start menu and type Device manager. Press the enter key. Find ReSpeaker Lite device, right click it and select Uninstall device. Select Delete the driver software for this device and click Uninstall. After that, restart the device and Windows will re-install the right sound card driver for it.