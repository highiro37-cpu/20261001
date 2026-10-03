import streamlit as st
import requests
import time

DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

st.set_page_config(page_title="門禁控制系統", page_icon="🚪", layout="centered")

def send_door_cmd(cmd_val):
    try:
        res = requests.put(f"{DOOR_BASE_URL}/door/control.json", json=cmd_val, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

def get_door_status():
    try:
        res = requests.get(f"{DOOR_BASE_URL}/door/status.json", timeout=3)
        return res.json()
    except Exception:
        return None

st.title("🚪 門禁遠端控制面板")

# 讀取當前狀態
status = get_door_status()

# 顯示狀態指示器
col1, col2 = st.columns(2)
with col1:
    if status == 1:
        st.success("🔓 目前狀態：開啟 (Unlocked)")
    elif status == 0:
        st.error("🔒 目前狀態：關閉 (Locked)")
    else:
        st.warning("⚠️ 狀態：連線中 / 未知")

with col2:
    if st.button("🔄 重新整理狀態"):
        st.rerun()

st.divider()

# 操作按鈕
st.subheader("發送控制指令")
col_open, col_close = st.columns(2)

with col_open:
    if st.button("🟢 遠端開門 (1)", use_container_width=True):
        if send_door_cmd(1):
            st.success("已發送【開門】指令")
            time.sleep(1)
            st.rerun()
        else:
            st.error("發送失敗，請檢查網路")

with col_close:
    if st.button("🔴 遠端關門 (0)", use_container_width=True):
        if send_door_cmd(0):
            st.success("已發送【關門】指令")
            time.sleep(1)
            st.rerun()
        else:
            st.error("發送失敗，請檢查網路")
