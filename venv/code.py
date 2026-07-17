import sys
import time
from datetime import datetime
from pathlib import Path
import pyvisa

# Import Qt essentials
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit,
    QPushButton, QComboBox, QGridLayout, QFrame, QSpinBox
)   

def _generate_1_2_5_series(units):
    """สร้างลิสต์ค่าตามลำดับ 1-2-5 จากรายการหน่วย [(unit_str, seconds_or_volts_per_unit, [multipliers]), ...]"""
    values = []
    for unit_str, multipliers in units:
        for m in multipliers:
            if m == int(m):
                values.append(f"{int(m)}.00{unit_str}")
            else:
                values.append(f"{m:.2f}{unit_str}")
    return values


# Time/div: 5 ns/div ... 500 s/div (ลำดับ 1-2-5)
TIME_DIV_VALUES = _generate_1_2_5_series([
    ("ns", [5, 10, 20, 50, 100, 200, 500]),
    ("µs", [1, 2, 5, 10, 20, 50, 100, 200, 500]),
    ("ms", [1, 2, 5, 10, 20, 50, 100, 200, 500]),
    ("s",  [1, 2, 5, 10, 20, 50, 100, 200, 500]),
])

# V/div: 500 µV/div ... 10 V/div (ลำดับ 1-2-5)
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
    """แปลงข้อความ เช่น '-100.00µs' ให้กลายเป็นตัวเลขทศนิยมหน่วยวินาทีหรือโวลต์จริง"""
    try:
        # รองรับทั้งสัญลักษณ์ µ และ μ
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
        
        # ติดตั้งระบบหลังบ้าน Controller และสถานะสตรีม
        self.controller = ScopeController()
        self.is_streaming = False
        
        self.create_widgets()
        
        # เริ่มต้นเชื่อมต่ออุปกรณ์และเปิดระบบภาพสด
        self.init_connection()
        
        self.showFullScreen()
        
    def create_widgets(self):
        layout = QGridLayout()
        # ------------------------------- หน้าจอ MONITOR REAL-TIME ----------------------------
        self.monitor_frame = QFrame()
        self.monitor_frame.setFrameShape(QFrame.Shape.Box)
        self.monitor_frame.setStyleSheet("background-color: black; border: 2px solid #333;")
        monitor_layout = QGridLayout()
        
        self.display_label = QLabel("กำลังเชื่อมต่ออุปกรณ์...")
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display_label.setStyleSheet("color: #00ff00; font-size: 18px; font-family: Consolas;")
        
        monitor_layout.addWidget(self.display_label, 0, 0)
        self.monitor_frame.setLayout(monitor_layout)
        #-------------------------------status----------------------------
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

        self.s_frame.addWidget(self.name_lable,0,0)
        self.s_frame.addWidget(self.status_label,1,0)
        self.s_frame.addWidget(self.R_button,2,0)
        self.s_frame.addWidget(self.S_button,2,1)

        self.Status.setLayout(self.s_frame)
        #-------------------------------horizotal----------------------------
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
        #-------------------------Trigger----------------------------------
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
        #-------------------------scpi----------------------------------
        self.scpi = QFrame()
        self.scpi.setFrameShape(QFrame.Shape.Box)
        self.scpi_frame = QGridLayout()

        self.scpi_label = QLabel("scpi")
        self.scpi_entry = QLineEdit()
        self.scpi_entry.setPlaceholderText("พิมพ์คำสั่ง SCPI...")
        self.scpi_entry.returnPressed.connect(self.submit)
        self.scpi_submit = QPushButton("Submit")
        self.scpi_submit.clicked.connect(self.submit)

        self.scpi_frame.addWidget(self.scpi_label,0,0)
        self.scpi_frame.addWidget(self.scpi_entry,1,0)
        self.scpi_frame.addWidget(self.scpi_submit,1,1)

        self.scpi.setLayout(self.scpi_frame)
        #-----------------------------------------------------------
        # จัดตารางแถวควบคุมไว้แถว 0 และ ดันจอ Monitor ไปไว้แถวล่าง 1
        layout.addWidget(self.Status, 0, 0)
        layout.addWidget(self.horizotal, 0, 1)
        layout.addWidget(self.trigger, 0, 2)
        layout.addWidget(self.scpi, 0, 3)
        layout.addWidget(self.monitor_frame, 1, 0, 1, 3)
        self.setLayout(layout)

    # =================================================================
    # ระบบควบคุมสัญญาณภาพสด (QTimer Loop)
    # =================================================================
    def init_connection(self):
        try:
            self.controller.connect()
            time.sleep(0.3)
            try:
                idn = self.controller.query("*IDN?")
                self.name_lable.setText(f"Connected:\n{idn[:25]}...")
            except Exception:
                self.name_lable.setText("Connected:\nOscilloscope")
            
            self.is_streaming = True
            
            # ตั้งตัวจับเวลารันลูปอัปเดตหน้าจอหลักทุก ๆ 700 มิลลิวินาที
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_loop)
            self.timer.start(700)
            
        except Exception as e:
            self.display_label.setText(f"การเชื่อมต่อล้มเหลว:\n{e}")
            self.display_label.setStyleSheet("color: red;")

    def update_loop(self):
        if self.is_streaming:
            try:
                img_path = self.controller.capture_live_image()
                pixmap = QPixmap(str(img_path))
                if not pixmap.isNull():
                    self.display_label.setPixmap(pixmap)
                    self.display_label.setScaledContents(True)
            except Exception as e:
                print(f"Stream Warning: {e} (กำลังรับสัญญาณใหม่...)")

    # =================================================================
    # ฟังก์ชัน Callback ประมวลผลคำสั่งส่งไปยังเครื่องออสซิลโลสโคป
    # =================================================================
    def time_offset(self, index_value):
        actual_text = H_OFFSET_VALUES[index_value]
        print(f"Horizontal Offset เปลี่ยนเป็น: {actual_text}")
        val_sec = parse_offset_value(actual_text)
        self.controller.write(f":TIMebase:MAIN:OFFSet {val_sec}")

    def level_offset(self, index_value):
        actual_text = CH_OFFSET_VALUES[index_value]
        print(f"Trigger Level เปลี่ยนเป็น: {actual_text}")
        val_volt = parse_offset_value(actual_text)
        self.controller.write(f":TRIGger:EDGE:LEVel {val_volt}")
    
    def time_div(self, value):
        print(f"Time/div เปลี่ยนเป็น: {value}")
        val_sec = parse_offset_value(value)
        self.controller.write(f":TIMebase:MAIN:SCALe {val_sec}")

    def source_select(self, value):
        print(f"Trigger Source เปลี่ยนเป็น: {value}")
        # แปลงข้อความจากคอมโบ เช่น CH1 -> CHANnel1
        ch_num = value[-1]
        self.controller.write(f":TRIGger:EDGe:SOURce CHANnel{ch_num}")

    def slope_select(self, value):
        print(f"Trigger Slope เปลี่ยนเป็น: {value}")
        scpi_slope = "POSitive" if value == "Rising" else "NEGative"
        self.controller.write(f":TRIGger:EDGE:SLOPe {scpi_slope}")

    def sweep_select(self, value):
        print(f"Trigger Sweep เปลี่ยนเป็น: {value}")
        scpi_sweep = {"Auto": "AUTO", "Normal": "NORMal", "Single": "SINGle"}.get(value, "AUTO")
        self.controller.write(f":TRIGger:SWEep {scpi_sweep}")

    def run(self):
        try:
            self.controller.run()
            self.status_label.setText("Status : Run")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            print("Run")
        except Exception as e:
            print(f"Error: {e}")

    def stop(self):
        try:
            self.controller.stop()
            self.status_label.setText("Status : Stop")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            print("Stop")
        except Exception as e:
            print(f"Error: {e}")

    def submit(self):
        command = self.scpi_entry.text().strip()
        if command:
            print(f"command : {command}")
            try:
                # ตรวจสอบว่าเป็นคำสั่งแบบถามข้อมูล (?) หรือไม่
                if "?" in command:
                    res = self.controller.query(command)
                    print(f"Response: {res}")
                else:
                    self.controller.write(command)
                self.scpi_entry.clear()
            except Exception as e:
                print(f"SCPI Transmission Error: {e}")

    # ดักสัญญาณการปิดหน้าจอ เพื่อ Clear พอร์ตสื่อสาร
    def closeEvent(self, event):
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