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
"-100.00µs", "-10.00µs", "-1.00µs",
"0.00s",
"1.00µs", "10.00µs", "100.00µs",
"1.00ms", "10.00ms", "100.00ms", "500.00ms",
]
CH_OFFSET_VALUES = [
    "-5.00V", "-2.00V", "-1.00V", "-500.00mV", "-200.00mV", "-100.00mV", "-50.00mV", "-10.00mV",
    "0.00V",
    "10.00mV", "50.00mV", "100.00mV", "200.00mV", "500.00mV", "1.00V", "2.00V", "5.00V",
]
def parse_offset_value(text_value):
    """แปลงข้อความ เช่น '-100.00µs' ให้กลายเป็นตัวเลขทศนิยมหน่วยวินาทีจริง"""
    try:
        if "µs" in text_value:
            # ลบหน่วยออก แล้วแปลงเป็น float จากนั้นคูณด้วย 10^-6
            num = float(text_value.replace("µs", ""))
            return num * 1e-6
        elif "ms" in text_value:
            # ลบหน่วยออก แล้วแปลงเป็น float จากนั้นคูณด้วย 10^-3
            num = float(text_value.replace("ms", ""))
            return num * 1e-3
        elif "s" in text_value:
            # ลบหน่วยออก แล้วแปลงเป็น float ได้เลย
            return float(text_value.replace("s", ""))
    except ValueError:
        return 0.0
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
            d.text((300, 230), "[ SIMULATION MODE ]\n(Ready for PyQt GUI)", fill="#00ff00")
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
            if "*IDN?" in command: return "RIGOL_MOCK_DEVICE_DS1000Z"
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
# class spinbox เวอร์ชันปรับปรุง ป้องกันการแครช
class ListSpinBox(QSpinBox):
    def __init__(self, value_list, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value_list = value_list
        # ตั้งค่าให้วิ่งตั้งแต่ 0 ถึงตำแหน่งสุดท้ายของลิสต์อัตโนมัติ
        self.setRange(0, len(self.value_list) - 1)

    # เขียนทับฟังก์ชันแสดงผล ป้องกันดัชนีเอ๋อหรือหลุดช่วง
    def textFromValue(self, value):
        try:
            val_int = int(value)
            if 0 <= val_int < len(self.value_list):
                return self.value_list[val_int]
        except (ValueError, TypeError):
            pass
        return str(value)
# Main application window
class AppLiveScope(QWidget):
    # Constructor
    def __init__(self):
        # Call the constructor of QWidget
        super().__init__()
        # Set the window title
        self.setWindowTitle("Oscilloscope Control Center")
        # Create and arrange the widgets
        self.create_widgets()
        #set fullsceen
        self.showFullScreen()
        
    # Create all widgets and arrange them using a layout
    def create_widgets(self):
        layout = QGridLayout()
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

        self.spin = ListSpinBox(H_OFFSET_VALUES) # ส่งลิสต์ย่านเวลาเข้าไปเลย
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
        self.scpi_submit = QPushButton("Submit")
        self.scpi_submit.clicked.connect(self.submit)

        self.scpi_frame.addWidget(self.scpi_label,0,0)
        self.scpi_frame.addWidget(self.scpi_entry,1,0)
        self.scpi_frame.addWidget(self.scpi_submit,1,1)

        self.scpi.setLayout(self.scpi_frame)
        #-----------------------------------------------------------
        layout.addWidget(self.Status, 0, 0)
        layout.addWidget(self.horizotal, 0, 1)
        layout.addWidget(self.trigger, 0, 2)
        layout.addWidget(self.scpi,0,3)
        self.setLayout(layout)

    # Read the integer value from the input field
    def get_value(self):
        try:
            # Convert the text to an integer
            return int(self.entry.text())
        except ValueError:
            # If conversion fails, return 0
            return 0

    # Display a value in the input field
    def set_value(self, value):
        self.entry.setText(str(value))

    # Increase the current value by one
    def increment(self):
        self.set_value(self.get_value() + 1)

    def time_offset(self,index_value):
        actual_text = H_OFFSET_VALUES[index_value]
        print(f"ค่าถูกเปลี่ยนเป็น: {actual_text}")

    def level_offset(self,index_value):
        actual_text = CH_OFFSET_VALUES[index_value]
        print(f"ค่าถูกเปลี่ยนเป็น: {actual_text}")
    
    def time_div(self,value):
        print(f"ค่าถูกเปลี่ยนเป็น: {value}")

    def source_select(self,value):
        print(f"ค่าถูกเปลี่ยนเป็น: {value}")

    def slope_select(self,value):
        print(f"ค่าถูกเปลี่ยนเป็น: {value}")

    def sweep_select(self,value):
        print(f"ค่าถูกเปลี่ยนเป็น: {value}")

    def run(self):
        self.status_label.setText("Status : Run")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        print("Run")

    def stop(self):
        self.status_label.setText("Status : Stop")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        print("Stop")

    def submit(self):
        command = self.scpi_entry.text()
        print(f"command : {command}")
    # Reset the value to zero
    def clear(self):
        self.set_value(0)

# Main program
def main():
    # Create the Qt application object
    app = QApplication(sys.argv)
    # Create the main window
    window = AppLiveScope()
    # Start the Qt event loop
    app.exec()

# Execute the program only when this file is run directly
if __name__ == "__main__":
    main()
#------------------------------------------------------------
