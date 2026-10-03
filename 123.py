```python
import streamlit as st
import pandas as pd
import requests
import altair as alt
import time

# ==========================================
# 0. 系統設定與 Firebase 網址配置
# ==========================================
st.set_page_config(
    page_title="ESP32 智慧儀表板",
    page_icon="🌐",
    layout="centered"
)

ENV_DATA_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/data.json"
ENV_HISTORY_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/history.json"

DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

SECRET_PASSWORD = "13579"


# ==========================================
# Firebase 基本讀取
# ==========================================
def fetch_json(url):
    try:
        res = requests.get(url, timeout=3)

        if res.status_code == 200:
            return res.json()

        return None

    except Exception:
        return None


# ==========================================
# 發送門禁控制指令
# ==========================================
def send_door_cmd(cmd_val):
    try:
        cmd_val = int(cmd_val)

        res = requests.put(
            f"{DOOR_BASE_URL}/door/control.json",
            json=cmd_val,
            timeout=3
        )

        return res.status_code == 200

    except Exception:
        return False


# ==========================================
# 讀取 ESP32 實際門禁狀態
#
```
