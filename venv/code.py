import sys
import time
from datetime import datetime
from pathlib import Path
import pyvisa

# Import Qt essentials
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit,
    QPushButton, QComboBox, QGridLayout, QFrame, QSpinBox,
    QHBoxLayout, QVBoxLayout, QCheckBox
)   

def _generate_1_2_5_series(units):
    """Generate a list of values in 1-2-5 sequence from unit definitions."""
    values = []
    for unit_str, multipliers in units:
        for m in multipliers:
            if m == int(m):
                values.append(f"{int(m)}.00{unit_str}")
            else:
                values.append(f"{m:.2f}{unit_str}")
    return values


# Time/div settings: 5 ns/div to 500 s/div (1-2-5 sequence)
TIME_DIV_VALUES = _generate_1_2_5_series([
    ("ns", [5, 10, 20, 50, 100, 200, 500]),
    ("µs", [1, 2, 5, 10, 20, 50, 100, 200, 500]),
    ("ms", [1, 2, 5, 10, 20, 50, 100, 200, 500]),
    ("s",  [1, 2, 5, 10, 20, 50, 100, 200, 500]),
])

# V/div settings: 500 µV/div to 10 V/div (1-2-5 sequence)
VOLT_DIV_VALUES = _generate_1_2_5_series([
    ("µV", [500]),
    ("mV", [1, 2, 5, 10, 20, 50, 100, 200, 500]),
    ("V",  [1, 2, 5, 10]),
])
H_OFFSET_VALUES = [
    "-500.00ms", "-100.00ms", "-10.00ms", "-1.00ms",
    "-100.00µs", "-10.00µs", "-1.00µs", "0.00s",
    "1.00µs", "10.00µs", "100.00µs",
    "1.00ms", "10.00ms", "100.00ms", "500.00ms",
]
CH_OFFSET_VALUES = [
    "-5.00V", "-2.00V", "-1.00V", "-500.00mV", "-200.00mV", "-100.00mV", "-50.00mV", "-10.00mV",
    "0.00V",
    "10.00mV", "50.00mV", "100.00mV", "200.00mV", "500.00mV", "1.00V", "2.00V", "5.00V",
]

def parse_offset_value(text_value):
    """Convert text values (like '-100.00µs') to real float numbers in seconds or volts."""
    try:
        # Support both micro symbols (µ and μ)
        clean_text = text_value.replace("µs", "").replace("μs", "").replace("ms", "").replace("ns", "").replace("mV", "").replace("µV", "").replace("μV", "").replace("s", "").replace("V", "")
        num = float(clean_text)
        
        if "ns" in text_value: return num * 1e-9
        elif "µs" in text_value or "μs" in text_value or "µV" in text_value or "μV" in text_value: return num * 1e-6
        elif "ms" in text_value or "mV" in text_value: return num * 1e-3
        else: return num
    except ValueError:
        return 0.0

# =================================================================
# Instrument Controller Backend
# =================================================================
class ScopeController:
    def __init__(self, backend="@py", timeout=5000):
        self.backend = backend
        self.timeout = timeout
        self.rm = None
        self.scope = None
        self.output_file = Path(__file__).parent / "live_display.png"
        self.simulation_mode = False
        self.mock_file = Path(__file__).parent / "mock_scope.png"

    def connect(self):
        try:
            self.rm = pyvisa.ResourceManager(self.backend)
            resources = self.rm.list_resources()
            for resource in resources:
                if resource.startswith("USB"):
                    self.scope = self.rm.open_resource(resource)
                    self.scope.timeout = self.timeout
                    self.simulation_mode = False
                    time.sleep(0.2)
                    print(f"Connected to real instrument: {resource}")
                    return
            raise RuntimeError("No USB instrument found in list.")
        except Exception as e:
            print(f"\n[Hardware Not Found]: {e}")
            print("-> Switching to SIMULATION MODE for GUI Designing...\n")
            self.simulation_mode = True
            if not self.mock_file.exists():
                self._create_dummy_image()

    def _create_dummy_image(self):
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (800, 480), color='#1a1a1a')
            d = ImageDraw.Draw(img)
            d.text((250, 230), "[ SIMULATION MODE ]\nScope Screen Placeholder", fill="#00ff00")
            img.save(self.mock_file)
        except ImportError:
            pass

    def disconnect(self):
        if self.simulation_mode: return
        if self.scope is not None: self.scope.close(); self.scope = None
        if self.rm is not None: self.rm.close(); self.rm = None

    def write(self, command):
        if self.simulation_mode:
            print(f"[Simulated Write]: {command}")
            return
        self.scope.write(command)

    def query(self, command):
        if self.simulation_mode:
            if "*IDN?" in command: return "RIGOL_MOCK_DEVICE_DHO814"
            return "0"
        return self.scope.query(command).strip()

    def run(self): self.write(":RUN")
    def stop(self): self.write(":STOP")

    def _read_ieee_block(self):
        header = self.scope.read_bytes(2)
        if header[0:1] != b"#":
            try: self.scope.read_bytes(2048)
            except Exception: pass
            raise RuntimeError(f"Unexpected IEEE header format: {header}")
        digits = int(header[1:2])
        length = int(self.scope.read_bytes(digits).decode())
        return self.scope.read_bytes(length)

    def capture_live_image(self):
        if self.simulation_mode:
            if self.mock_file.exists():
                self.output_file.write_bytes(self.mock_file.read_bytes())
                return self.output_file
            raise FileNotFoundError("Please place a 'mock_scope.png' in the script folder.")
        try:
            self.write(":DISPlay:SNAP?")
            png_data = self._read_ieee_block()
            if png_data.startswith(b"\x89PNG"):
                self.output_file.write_bytes(png_data)
                return self.output_file
            raise RuntimeError("Returned data is not a valid PNG image.")
        except Exception as e:
            try: self.scope.read_bytes(1024)
            except Exception: pass
            raise e

class ListSpinBox(QSpinBox):
    def __init__(self, value_list, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value_list = value_list
        self.setRange(0, len(self.value_list) - 1)

    def textFromValue(self, value):
        try:
            val_int = int(value)
            if 0 <= val_int < len(self.value_list):
                return self.value_list[val_int]
        except (ValueError, TypeError):
            pass
        return str(value)

# =================================================================
# Main Application Window
# =================================================================
class AppLiveScope(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oscilloscope Control Center")
        
        self.controller = ScopeController()
        self.is_streaming = False
        self.channel_widgets = {} # Stores control widgets for each channel
        
        self.create_widgets()
        self.init_connection()
        self.showFullScreen()
        
    def create_widgets(self):
        layout = QGridLayout()
        # ------------------------------- REAL-TIME MONITOR SCREEN ----------------------------
        self.monitor_frame = QFrame()
        self.monitor_frame.setFrameShape(QFrame.Shape.Box)
        self.monitor_frame.setStyleSheet("background-color: black; border: 2px solid #333;")
        monitor_layout = QGridLayout()
        
        self.display_label = QLabel("Connecting to device...")
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display_label.setStyleSheet("color: #00ff00; font-size: 18px; font-family: Consolas;")
        
        monitor_layout.addWidget(self.display_label, 0, 0)
        self.monitor_frame.setLayout(monitor_layout)
        
        #------------------------------- Status Block ----------------------------
        self.Status = QFrame()
        self.Status.setFrameShape(QFrame.Shape.Box)
        self.s_frame = QGridLayout()
        self.name_lable = QLabel("Connected:")
        self.status_label = QLabel("Status : Run")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self.R_button = QPushButton("Run")
        self.R_button.clicked.connect(self.run)
        self.S_button = QPushButton("Stop")
        self.S_button.clicked.connect(self.stop)

        self.s_frame.addWidget(self.name_lable, 0, 0, 1, 2)
        self.s_frame.addWidget(self.status_label, 1, 0, 1, 2)
        self.s_frame.addWidget(self.R_button, 2, 0)
        self.s_frame.addWidget(self.S_button, 2, 1)

        self.Status.setLayout(self.s_frame)
        
        #------------------------------- Horizontal Settings ----------------------------
        self.horizotal = QFrame()
        self.horizotal.setFrameShape(QFrame.Shape.Box)
        self.h_frame = QGridLayout()
        self.time_label = QLabel("time/div")
        self.offset_label = QLabel("offset")
        self.combo = QComboBox()

        self.spin = ListSpinBox(H_OFFSET_VALUES) 
        self.spin.setValue(7)
        self.spin.valueChanged.connect(self.time_offset)

        self.combo.addItems(TIME_DIV_VALUES)
        self.combo.currentTextChanged.connect(self.time_div)

        self.h_frame.addWidget(self.time_label,0,0)
        self.h_frame.addWidget(self.combo,1,0)
        self.h_frame.addWidget(self.offset_label,2,0)
        self.h_frame.addWidget(self.spin, 3, 0)

        self.horizotal.setLayout(self.h_frame)
        
        #------------------------- Trigger Settings ----------------------------------
        self.trigger = QFrame()
        self.trigger.setFrameShape(QFrame.Shape.Box)
        self.t_frame = QGridLayout()
        self.trigger_label = QLabel("Trigger")

        self.source = QLabel("source")
        self.s_combo = QComboBox()
        self.s_combo.addItems(["CH1","CH2","CH3","CH4"])
        self.s_combo.currentTextChanged.connect(self.source_select)

        self.level_label = QLabel("level")
        self.l_spin = ListSpinBox(CH_OFFSET_VALUES)
        self.l_spin.setValue(8)
        self.l_spin.valueChanged.connect(self.level_offset)

        self.slope_label = QLabel("slope")
        self.slope_combo = QComboBox()
        self.slope_combo.addItems(["Rising","Falling"])
        self.slope_combo.currentTextChanged.connect(self.slope_select)

        self.sweep_label = QLabel("sweep")
        self.sweep_combo = QComboBox()
        self.sweep_combo.addItems(["Auto","Normal","Single"])
        self.sweep_combo.currentTextChanged.connect(self.sweep_select)

        self.t_frame.addWidget(self.trigger_label,0,0)
        self.t_frame.addWidget(self.source,1,0)
        self.t_frame.addWidget(self.s_combo,1,1)
        self.t_frame.addWidget(self.level_label,1,2)
        self.t_frame.addWidget(self.l_spin,1,3)
        self.t_frame.addWidget(self.slope_label,2,0)
        self.t_frame.addWidget(self.slope_combo,2,1)
        self.t_frame.addWidget(self.sweep_label,2,2)
        self.t_frame.addWidget(self.sweep_combo,2,3)
        
        self.trigger.setLayout(self.t_frame)
        
        #------------------------- SCPI Command Console ----------------------------------
        self.scpi = QFrame()
        self.scpi.setFrameShape(QFrame.Shape.Box)
        self.scpi_frame = QGridLayout()

        self.scpi_label = QLabel("scpi")
        self.scpi_entry = QLineEdit()
        self.scpi_entry.setPlaceholderText("Enter SCPI command...")
        self.scpi_entry.returnPressed.connect(self.submit)
        self.scpi_submit = QPushButton("Submit")
        self.scpi_submit.clicked.connect(self.submit)

        self.scpi_frame.addWidget(self.scpi_label,0,0)
        self.scpi_frame.addWidget(self.scpi_entry,1,0)
        self.scpi_frame.addWidget(self.scpi_submit,1,1)

        self.scpi.setLayout(self.scpi_frame)
        
        #------------------------- Channel Control Boxes (CH1 - CH4) -----------------
        self.channel_colors = {
            1: "#ffd700",  # CH1: Yellow
            2: "#00bfff",  # CH2: Light Blue
            3: "#ff1493",  # CH3: Pink
            4: "#32cd32",  # CH4: Lime Green
        }

        self.ch_frames = []
        for ch_num in range(1, 5):
            ch_frame = self.create_channel_box(
                parent=self, 
                ch=ch_num, 
                border_color=self.channel_colors[ch_num]
            )
            self.ch_frames.append(ch_frame)

        #-------------------------Capture-Button-------------------
        self.c_button = QPushButton("Capture Screen")
        self.c_button.clicked.connect(self.capture_and_save) 
        self.s_frame.addWidget(self.c_button, 3, 0, 1, 2)

        #-------------------------SCPI-Log------------------------------
        self.log_frame = QFrame()
        self.log_frame.setFrameShape(QFrame.Shape.Box)
        log_layout = QVBoxLayout(self.log_frame)
        log_layout.setContentsMargins(5, 5, 5, 5)
        
        log_title = QLabel("SCPI Communication Log")
        log_title.setStyleSheet("font-weight: bold; font-size: 11px; color: #555;")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #f9f9f9; font-family: Consolas; font-size: 11px; border: 1px solid #ddd;")
        
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log_text)
        
        #-------------------------Close-Button----------------------------
        self.close_button = QPushButton("Close Screen")
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #ff4d4d; 
                color: white; 
                font-weight: bold; 
                font-size: 14px;
                border-radius: 6px;
                border: 1px solid #cc0000;
            }
            QPushButton:hover {
                background-color: #ff3333;
            }
            QPushButton:pressed {
                background-color: #cc0000;
            }
        """)
        self.close_button.clicked.connect(self.close) 

        self.right_panel = QFrame()
        self.right_panel.setStyleSheet("border: none; background: transparent;")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10) 
        
        for ch_frame in self.ch_frames:
            right_layout.addWidget(ch_frame)
            
        right_layout.addStretch(1) 

        #-----------------------------------------------------------
        # Main Window Grid Layout Setup
        layout.addWidget(self.Status, 0, 0)
        layout.addWidget(self.horizotal, 0, 1)
        layout.addWidget(self.trigger, 0, 2)
        layout.addWidget(self.scpi, 0, 3)
        
        layout.addWidget(self.monitor_frame, 1, 0, 4, 4)
        layout.addWidget(self.right_panel, 1, 4, 5, 1) # ครอบคลุมแถว 0 ถึง 4 ฝั่งขวาสุดทั้งหมด
        
        layout.addWidget(self.log_frame, 5, 0, 1, 4)
        layout.addWidget(self.close_button, 5, 4)
        
        layout.setRowStretch(1, 1) 
        layout.setRowStretch(5, 0) 
        
        self.setLayout(layout)

    # =================================================================
    # PyQt Widget Helper Functions
    # =================================================================
    def create_channel_box(self, parent, ch, border_color, fg_text=None):
        text_color = fg_text if fg_text else border_color
        
        # Create a container frame with color styling for each channel
        frame = QFrame(parent)
        frame.setObjectName(f"ChannelBox_{ch}")
        frame.setStyleSheet(f"""
            QFrame#{frame.objectName()} {{
                border: 2px solid {border_color};
                border-radius: 8px;
                background-color: #f5f5f5;
            }}
            QLabel {{
                border: none;
                font-weight: bold;
            }}
            QCheckBox {{
                border: none;
            }}
        """)
        
        # Vertical arrangement of controls inside the channel frame
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 1. Channel Title
        lbl_title = QLabel(f"CH {ch}", frame)
        lbl_title.setStyleSheet(f"color: {text_color}; font-size: 13px;")
        layout.addWidget(lbl_title)
        
        # 2. Toggle Visibility Checkbox
        chk = QCheckBox("display", frame)
        chk.setChecked(True)
        chk.toggled.connect(lambda checked, ch=ch: self.on_channel_display_toggle(ch, checked))
        layout.addWidget(chk)
        
        # 3. Volts per division selector (V/div)
        row_vdiv, cb_vdiv = self.create_channel_control_row(
            frame, "V/div", VOLT_DIV_VALUES,
            on_select=lambda text, ch=ch: self.on_channel_vdiv_change(ch, text)
        )
        layout.addWidget(row_vdiv)
        
        # 4. Vertical Offset selector
        row_offset, sb_offset = self.create_channel_offset_spinbox_row(
            frame, "offset", CH_OFFSET_VALUES, ch=ch,
            initial_value="0.00V"
        )
        layout.addWidget(row_offset)
        
        # 5. Input Coupling selector (DC / AC / GND)
        row_coupling, cb_coupling = self.create_channel_control_row(
            frame, "coupling", ["DC", "AC", "GND"],
            on_select=lambda text, ch=ch: self.on_channel_coupling_change(ch, text)
        )
        layout.addWidget(row_coupling)
        
        # Save widgets in a dictionary for easy updates later
        self.channel_widgets[ch] = {
            "frame": frame,
            "display_checkbox": chk,
            "vdiv": cb_vdiv,      
            "offset": sb_offset,  
            "coupling": cb_coupling,
        }
        
        return frame
    
    def create_channel_control_row(self, parent_frame, label_text, items, on_select):
        """Helper to create a horizontal row with a QLabel and QComboBox."""
        row_widget = QWidget(parent_frame)
        row_widget.setStyleSheet("background: transparent; border: none;")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        
        label = QLabel(label_text, row_widget)
        label.setFixedWidth(55)
        
        combo = QComboBox(row_widget)
        combo.addItems(items)
        combo.currentTextChanged.connect(on_select)
        
        row_layout.addWidget(label)
        row_layout.addWidget(combo)
        row_widget.setLayout(row_layout)
        
        return row_widget, combo 
    
    def create_channel_offset_spinbox_row(self, parent_frame, label_text, value_list, ch, initial_value):
        """Helper to create a horizontal row with a QLabel and ListSpinBox for offsets."""
        row_widget = QWidget(parent_frame)
        row_widget.setStyleSheet("background: transparent; border: none;")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        
        label = QLabel(label_text, row_widget)
        label.setFixedWidth(55)
        
        spin = ListSpinBox(value_list, row_widget)
        
        # Find and select the initial value (e.g., "0.00V")
        if initial_value in value_list:
            spin.setValue(value_list.index(initial_value))
            
        spin.valueChanged.connect(lambda index, ch=ch: self.on_channel_offset_change(ch, index))
        
        row_layout.addWidget(label)
        row_layout.addWidget(spin)
        row_widget.setLayout(row_layout)
        
        return row_widget, spin

    # Helper function to append text into SCPI log box
    def log_message(self, direction, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {direction} {text}")
        # Scroll to the bottom of the log automatically
        self.log_text.ensureCursorVisible()

    # =================================================================
    # Callback Functions for Channel Settings (Sends commands to device)
    # =================================================================
    def on_channel_display_toggle(self, ch, checked):
        state = "ON" if checked else "OFF"
        cmd = f":OUTPut{ch}:STATe {state}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def on_channel_vdiv_change(self, ch, value):
        val_volt = parse_offset_value(value)
        cmd = f":CHANnel{ch}:SCALe {val_volt}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def on_channel_offset_change(self, ch, index_value):
        actual_text = CH_OFFSET_VALUES[index_value]
        val_volt = parse_offset_value(actual_text)
        cmd = f":CHANnel{ch}:OFFSet {val_volt}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def on_channel_coupling_change(self, ch, value):
        cmd = f":CHANnel{ch}:COUPling {value}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    # =================================================================
    # Live Screen Streaming System (QTimer Loop)
    # =================================================================
    def init_connection(self):
        try:
            self.controller.connect()
            time.sleep(0.3)
            try:
                self.log_message("TX ->", "*IDN?")
                idn = self.controller.query("*IDN?")
                self.log_message("RX <-", idn)
                self.name_lable.setText(f"Connected:\n{idn[:25]}...")
            except Exception:
                self.name_lable.setText("Connected:\nOscilloscope")
            
            self.is_streaming = True
            
            # Update live screen image every 700 ms
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_loop)
            self.timer.start(700)
            
        except Exception as e:
            self.display_label.setText(f"Connection Failed:\n{e}")
            self.display_label.setStyleSheet("color: red;")
            self.log_message("[ERR]", f"Connection failed: {e}")

    def update_loop(self):
        if self.is_streaming:
            try:
                img_path = self.controller.capture_live_image()
                pixmap = QPixmap(str(img_path))
                if not pixmap.isNull():
                    self.display_label.setPixmap(pixmap)
                    self.display_label.setScaledContents(True)
            except Exception as e:
                print(f"Stream Warning: {e} (retrying...)")

    def capture_and_save(self):
        """Action for capture screen button."""
        self.log_message("TX ->", ":DISPlay:SNAP? (Trigger Manual Capture)")
        try:
            self.update_loop()
            self.log_message("[OK]", "Screen captured successfully!")
        except Exception as e:
            self.log_message("[ERR]", f"Capture failed: {e}")

    # =================================================================
    # Callback Functions for Oscilloscope Parameters (Timebase & Trigger)
    # =================================================================
    def time_offset(self, index_value):
        actual_text = H_OFFSET_VALUES[index_value]
        val_sec = parse_offset_value(actual_text)
        cmd = f":TIMebase:MAIN:OFFSet {val_sec}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def level_offset(self, index_value):
        actual_text = CH_OFFSET_VALUES[index_value]
        val_volt = parse_offset_value(actual_text)
        cmd = f":TRIGger:EDGE:LEVel {val_volt}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)
    
    def time_div(self, value):
        val_sec = parse_offset_value(value)
        cmd = f":TIMebase:MAIN:SCALe {val_sec}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def source_select(self, value):
        ch_num = value[-1]
        cmd = f":TRIGger:EDGe:SOURce CHANnel{ch_num}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def slope_select(self, value):
        scpi_slope = "POSitive" if value == "Rising" else "NEGative"
        cmd = f":TRIGger:EDGE:SLOPe {scpi_slope}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def sweep_select(self, value):
        scpi_sweep = {"Auto": "AUTO", "Normal": "NORMal", "Single": "SINGle"}.get(value, "AUTO")
        cmd = f":TRIGger:SWEep {scpi_sweep}"
        self.log_message("TX ->", cmd)
        self.controller.write(cmd)

    def run(self):
        try:
            self.log_message("TX ->", ":RUN")
            self.controller.run()
            self.status_label.setText("Status : Run")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        except Exception as e:
            self.log_message("[ERR]", f"Run Error: {e}")

    def stop(self):
        try:
            self.log_message("TX ->", ":STOP")
            self.controller.stop()
            self.status_label.setText("Status : Stop")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        except Exception as e:
            self.log_message("[ERR]", f"Stop Error: {e}")

    def submit(self):
        command = self.scpi_entry.text().strip()
        if command:
            self.log_message("TX ->", command)
            try:
                if "?" in command:
                    res = self.controller.query(command)
                    self.log_message("RX <-", res)
                else:
                    self.controller.write(command)
                self.scpi_entry.clear()
            except Exception as e:
                self.log_message("[ERR]", f"SCPI Transmission Error: {e}")

    # Handle window close event to safely clean up communication ports
    def closeEvent(self, event):
        self.log_message("[SYSTEM]", "Closing Connection and exiting application...")
        self.is_streaming = False
        if hasattr(self, 'timer'):
            self.timer.stop()
        self.controller.disconnect()
        event.accept()

# Main program
def main():
    app = QApplication(sys.argv)
    window = AppLiveScope()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()