# Oscilloscope Control Center

A Python-based GUI application designed to remotely control hardware oscilloscopes and stream their display screens in real-time. Built using PyQt6 for a clean, responsive user interface and PyVISA for executing standard SCPI commands via USB.

The project features a built-in Simulation Mode that automatically activates if no physical instrument is detected. This allows developers to fully test and iterate on the GUI layout design without needing live hardware attached.

---

## Features

*   **Real-time Screen Streaming**: Captures and streams the oscilloscope screen directly to the GUI every 700 ms (via standard `:DISPlay:SNAP?` queries), with a manual **Capture Screen** button for on-demand snapshots.
*   **Run / Stop Control**: Instantly toggle the instrument's acquisition state directly from your computer.
*   **Horizontal Controls**: Dynamically adjust Time/div (pre-configured to traditional 1-2-5 series sequencing) and Horizontal Position Offset.
*   **Trigger Configurations**: Full trigger block diagnostics including Source selection (CH1-CH4), Level adjustment, Slope configuration (Rising/Falling), and Sweep modes (Auto/Normal/Single).
*   **Per-Channel Control Panels (CH1-CH4)**: Independent, color-coded control boxes for each channel, including:
    *   Display On/Off toggle
    *   Volts/div (V/div) selector
    *   Vertical Offset adjustment
    *   Input Coupling selector (DC / AC / GND)
*   **Direct SCPI Command Terminal**: A built-in terminal box to write raw SCPI commands or query instrument data with auto-detection for response blocks.
*   **SCPI Communication Log**: A live, timestamped log panel that records every command sent (TX) and every response received (RX), useful for debugging and traceability.
*   **Auto-Fallback Simulation**: Seamlessly transitions to simulation mode if the physical instrument is unplugged or missing, auto-generating a green grid placeholder screen to keep the UI active.

---

## Dependencies

Install the required Python packages using your terminal or command prompt:

```bash
pip install PyQt6 pyvisa pyvisa-py Pillow
```
