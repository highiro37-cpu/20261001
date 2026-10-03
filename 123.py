import streamlit as st
import requests
import time

DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

# 1. 讀取與發送控制指令的函式
def send_door_cmd(cmd_val):
    try:
        # 直接用 PUT 寫入純數字 1 或 0 到 /door/control.json
        res = requests.put(f"{DOOR_BASE_URL}/door/control.json", json=cmd_val, timeout=3)
        return res.status_code == 200
    except:
        return False

def get_door_status():
    try:
        # 讀取 /door/status.json
        res = requests.get(f"{DOOR_BASE_URL}/door/status.json", timeout=3)
        return res.json()
    except:
        return None

# 2. UI 介面觸發
st.subheader("🚪 門禁控制面板")
status = get_door_status()
st.write(f"目前 Firebase /door/status 狀態：`{status}`")

action = st.radio("選擇控制指令：", ["開門", "關門"], horizontal=True)
if st.button("🚀 發送控制指令"):
    cmd = 1 if action == "開門" else 0
    if send_door_cmd(cmd):
        st.success(f"已成功發送數字 {cmd} 至 Firebase！")
        time.sleep(0.5)
        st.rerun()
    else:
        st.error("發送失敗")
