from machine import Pin, SPI, I2C
import time
import network
import urequests
import usocket as socket
import gc
import _thread
import sh1106
from mfrc522 import MFRC522

# =====================
# 1. Wi-Fi & 雲端設定
# =====================
WIFI_SSID = "Lee"
WIFI_PASS = "hotz6764"

FIREBASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"
BLYNK_TOKEN = "esqzQP0ndzjO8m6E1OGgqRsKL109JZRt"
BLYNK_HOST = "sgp1.blynk.cloud"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)


def connect_wifi():
    if not wlan.isconnected():
        print("Connecting WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        retry = 0
        while not wlan.isconnected() and retry < 20:
            time.sleep(0.5)
            retry += 1
        if wlan.isconnected():
            print("WiFi OK! IP:", wlan.ifconfig()[0])


connect_wifi()

# LED 開門指示 (GPIO 16)
led = Pin(16, Pin.OUT)
led.value(0)

# 共享變數與鎖定機制 (跨核心通訊)
thread_lock = _thread.allocate_lock()
sync_cloud_flag = -1  # -1: 無需更新, 0: 要求關門, 1: 要求開門
sync_source = ""      # 本次事件來源 (RFID_OPEN / PASSWORD_OPEN / ...)，空字串代表不記錄
ui_cmd = None         # 更新 UI 觸發器
last_action_time = time.time()


# =====================
# 原生 Socket 極速 HTTP 工具
# =====================
def fast_blynk_get(path):
    """使用原生 usocket 發送 HTTP 請求，速度遠快於 urequests"""
    try:
        addr = socket.getaddrinfo(BLYNK_HOST, 80)[0][-1]
        s = socket.socket()
        s.settimeout(0.8)
        s.connect(addr)
        req = f"GET {path} HTTP/1.1\r\nHost: {BLYNK_HOST}\r\nConnection: close\r\n\r\n"
        s.sendall(req.encode('utf-8'))

        resp = s.recv(256)
        s.close()
        return resp
    except Exception:
        return None


def send_heartbeat():
    """用 Firebase 伺服器時間當心跳，不需要 ESP32 有 RTC / NTP"""
    try:
        r = urequests.put(f"{FIREBASE_URL}/door/heartbeat.json", json={".sv": "timestamp"}, timeout=1)
        r.close()
    except Exception:
        pass


def log_event(event):
    """記錄事件到 Firebase：door/log 追加一筆；開門事件另外更新 door/last_open"""
    stamp = {".sv": "timestamp"}
    try:
        r = urequests.post(f"{FIREBASE_URL}/door/log.json", json={"t": stamp, "e": event}, timeout=1)
        r.close()
    except Exception:
        pass
    if event.endswith("_OPEN"):
        try:
            r = urequests.put(f"{FIREBASE_URL}/door/last_open.json", json={"t": stamp, "by": event}, timeout=1)
            r.close()
        except Exception:
            pass


def firebase_reset_control():
    """消費指令：處理完後把 control 重設為 0"""
    try:
        r = urequests.put(f"{FIREBASE_URL}/door/control.json", json=0, timeout=1)
        r.close()
    except Exception:
        pass


# =====================
# 強制開機初始化 (V10 OFF / V11 沒顏色)
# =====================
def init_cloud_status():
    """開機後清空舊指令，防止開機自動開門"""
    print("Resetting Cloud Status (V10=OFF, V11=NO COLOR, Control=0)...")
    try:
        path = f"/external/api/batch/update?token={BLYNK_TOKEN}&V10=0&V11=0&pin=V11&property=color&value=%23000000"
        fast_blynk_get(path)

        res_fb1 = urequests.put(f"{FIREBASE_URL}/door/status.json", json=0, timeout=2)
        res_fb1.close()
        res_fb2 = urequests.put(f"{FIREBASE_URL}/door/control.json", json=0, timeout=2)
        res_fb2.close()

        print("Cloud Reset OK!")
    except Exception as e:
        print("Cloud Reset Error:", e)


init_cloud_status()

# =====================
# 2. OLED SH1106 設定
# =====================
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
oled = sh1106.SH1106_I2C(128, 64, i2c, addr=0x3C, rotate=180)
oled.sleep(False)


def show_ui(line1, line2="", line3="", line4=""):
    oled.fill(0)
    oled.text(line1, 0, 0)
    oled.text(line2, 0, 18)
    oled.text(line3, 0, 36)
    oled.text(line4, 0, 52)
    oled.show()


def show_home():
    ip_str = wlan.ifconfig()[0][:13] if wlan.isconnected() else "No WiFi"
    show_ui(" DOOR LOCK SYSTEM ", f"IP:{ip_str}", " [Card or Key] ", " Scan or Press ")


# =====================
# 3. 雙核心：背景網路線程 (Core 1)
# =====================
def push_state_to_cloud(val, sync_firebase=True, sync_blynk=True):
    """推送到雲端：val=1 時 V10=1, V11=255 (亮綠燈)；val=0 時 V10=0, V11=0 (沒顏色)"""
    if sync_firebase:
        try:
            res = urequests.put(f"{FIREBASE_URL}/door/status.json", json=val, timeout=1)
            res.close()
        except Exception:
            pass

    if sync_blynk:
        v10_val = 1 if val == 1 else 0
        v11_val = 255 if val == 1 else 0
        color = "%2300FF00" if val == 1 else "%23000000"

        path = f"/external/api/batch/update?token={BLYNK_TOKEN}&V10={v10_val}&V11={v11_val}&pin=V11&property=color&value={color}"
        fast_blynk_get(path)

    gc.collect()


def network_thread():
    global sync_cloud_flag, sync_source, ui_cmd, last_action_time
    last_v10_raw = 0  # 上升沿觸發判斷
    poll_target = 0
    last_hb = time.ticks_add(time.ticks_ms(), -10000)  # 開機後立刻送第一次心跳

    while True:
        try:
            if not wlan.isconnected():
                connect_wifi()
                time.sleep(1)
                continue

            # (A) 優先處理實體觸發 (刷卡/密碼/8秒自動關門)
            target_val = -1
            src = ""
            with thread_lock:
                if sync_cloud_flag != -1:
                    target_val = sync_cloud_flag
                    src = sync_source
                    sync_cloud_flag = -1
                    sync_source = ""

            if target_val != -1:
                push_state_to_cloud(target_val)
                if src:
                    log_event(src)
                if target_val == 0:
                    last_v10_raw = 0

            # (A2) 每 5 秒送一次心跳
            if time.ticks_diff(time.ticks_ms(), last_hb) >= 5000:
                last_hb = time.ticks_ms()
                send_heartbeat()

            # (B) 輪流查詢 Firebase / Blynk
            if poll_target == 0:
                # Firebase control: 1 = 開門, 2 = 關門, 0 = 無指令
                cmd = None
                try:
                    res = urequests.get(f"{FIREBASE_URL}/door/control.json", timeout=1)
                    if res.status_code == 200:
                        cmd = res.json()
                    res.close()
                except Exception:
                    cmd = None

                if cmd == 1:
                    with thread_lock:
                        led.value(1)
                        ui_cmd = ("FIREBASE CMD", "REMOTE OPEN", "Door Unlocked!", "Welcome")
                        last_action_time = time.time()
                    push_state_to_cloud(1)       # 同步 Firebase status=1 與 Blynk
                    log_event("WEB_OPEN")
                    firebase_reset_control()
                elif cmd == 2:
                    with thread_lock:
                        led.value(0)
                        ui_cmd = "HOME"
                    push_state_to_cloud(0)       # 同步 Firebase status=0 與 Blynk
                    log_event("WEB_CLOSE")
                    firebase_reset_control()
                poll_target = 1

            elif poll_target == 1:
                # 讀取 Blynk V10 狀態
                path = f"/external/api/get?token={BLYNK_TOKEN}&V10"
                resp = fast_blynk_get(path)
                if resp:
                    try:
                        resp_str = resp.decode('utf-8')
                        if "200 OK" in resp_str:
                            body = resp_str.split("\r\n\r\n")[-1]
                            body_clean = body.strip().strip('[]"').lower()
                            v10_cmd = 1 if body_clean in ["1", "true"] else 0

                            if v10_cmd == 1 and last_v10_raw == 0 and led.value() == 0:
                                last_v10_raw = 1
                                with thread_lock:
                                    led.value(1)
                                    ui_cmd = ("BLYNK APP", "REMOTE OPEN", "Door Unlocked!", "Welcome")
                                    last_action_time = time.time()
                                push_state_to_cloud(1)  # 同步 Firebase status 與 Blynk
                                log_event("BLYNK_OPEN")
                                fast_blynk_get(f"/external/api/update?token={BLYNK_TOKEN}&V10=0")
                            elif v10_cmd == 0:
                                last_v10_raw = 0
                    except Exception:
                        pass
                poll_target = 0

            gc.collect()
            time.sleep_ms(20)

        except Exception as e:
            time.sleep(1)


_thread.start_new_thread(network_thread, ())

# =====================
# 4. RFID & Keypad 設定
# =====================
spi = SPI(2, baudrate=1000000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(23), miso=Pin(19))
rfid = MFRC522(spi, 17, 5)
CARD_UID = [202, 123, 247, 6, 64]

rows = [Pin(12, Pin.OUT), Pin(14, Pin.OUT), Pin(27, Pin.OUT), Pin(26, Pin.OUT)]
cols = [Pin(25, Pin.IN, Pin.PULL_DOWN), Pin(33, Pin.IN, Pin.PULL_DOWN), Pin(32, Pin.IN, Pin.PULL_DOWN), Pin(4, Pin.IN, Pin.PULL_DOWN)]
keys = [['1', '2', '3', 'A'], ['4', '5', '6', 'B'], ['7', '8', '9', 'C'], ['*', '0', '#', 'D']]

for r in rows:
    r.value(0)
last_key = None


def scan_key():
    global last_key
    pressed_key = None
    for r in range(4):
        rows[r].value(1)
        for c in range(4):
            if cols[c].value() == 1:
                pressed_key = keys[r][c]
                break
        rows[r].value(0)
        if pressed_key:
            break

    if pressed_key != last_key:
        last_key = pressed_key
        if pressed_key:
            time.sleep_ms(15)
            return pressed_key
    return None


# =====================
# 5. 主程式 Loop (Core 0 專心處理實體感應)
# =====================
show_home()
PASSWORD = "13579"
input_password = ""
TIMEOUT_SEC = 8

try:
    while True:
        # (A) 處理背景 UI 命令
        current_ui = None
        with thread_lock:
            if ui_cmd:
                current_ui = ui_cmd
                ui_cmd = None

        if current_ui:
            if current_ui == "HOME":
                show_home()
            elif isinstance(current_ui, tuple):
                show_ui(*current_ui)

        # (B) 實體鍵盤
        key = scan_key()
        if key:
            last_action_time = time.time()
            if key.isdigit():
                input_password += key
                show_ui("PASSWORD [#]OK", f"Pass: {'*'*len(input_password)}", "----------------", "A:Del B:Clr D:Home")
            elif key == "A":
                input_password = input_password[:-1]
                show_home() if not input_password else show_ui("PASSWORD [#]OK", f"Pass: {'*'*len(input_password)}", "----------------", "A:Del B:Clr D:Home")
            elif key == "B":
                input_password = ""
                show_ui("PASSWORD [#]OK", "Pass: ", "----------------", "A:Del B:Clr D:Home")
            elif key == "#":
                if input_password == PASSWORD:
                    led.value(1)
                    show_ui("== PASSWORD OK ==", "ACCESS GRANTED", "Door Unlocked!", "Welcome")
                    with thread_lock:
                        sync_cloud_flag = 1
                        sync_source = "PASSWORD_OPEN"
                else:
                    led.value(0)
                    show_ui("= PASSWORD FAIL =", "WRONG PASSWORD!", "Access Denied", "Try Again")
                    with thread_lock:
                        sync_cloud_flag = 0
                        sync_source = "PASSWORD_FAIL"
                input_password = ""
            elif key == "D":
                input_password = ""
                show_home()

        # (C) RFID 刷卡感應
        stat, bits = rfid.request(rfid.REQIDL)
        if stat == rfid.OK:
            stat, uid = rfid.anticoll()
            if stat == rfid.OK:
                last_action_time = time.time()
                if uid == CARD_UID:
                    led.value(1)
                    show_ui("=== RFID OK ===", "ACCESS GRANTED", "Door Unlocked!", "Welcome Back")
                    with thread_lock:
                        sync_cloud_flag = 1
                        sync_source = "RFID_OPEN"
                else:
                    led.value(0)
                    show_ui("== RFID DENIED ==", "ACCESS DENIED!", "Unknown Card", "Try Again")
                    with thread_lock:
                        sync_cloud_flag = 0
                        sync_source = "RFID_DENIED"
                input_password = ""

        # (D) 8 秒超時自動關門與熄燈
        if (time.time() - last_action_time > TIMEOUT_SEC) and (led.value() == 1 or input_password != ""):
            was_open = led.value() == 1
            led.value(0)
            input_password = ""
            last_action_time = time.time()
            show_home()
            with thread_lock:
                sync_cloud_flag = 0
                sync_source = "AUTO_CLOSE" if was_open else ""

        time.sleep_ms(5)

except KeyboardInterrupt:
    print("\n程式中斷")
    led.value(0)
