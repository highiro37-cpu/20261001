import streamlit as st
import requests
import time

# Firebase 資料庫 URL
DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

# 設定網頁標題與圖示
st.set_page_config(page_title="門禁控制系統", page_icon="🔑", layout="centered")

# 設定預設開門密碼 (可自訂)
SECRET_PASSWORD = "13579"

# 1. 寫入控制指令至 Firebase
def send_door_cmd(cmd_val):
    try:
        res = requests.put(f"{DOOR_BASE_URL}/door/control.json", json=cmd_val, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

# 2. 讀取 Firebase 當前 status 狀態
def get_door_status():
    try:
        res = requests.get(f"{DOOR_BASE_URL}/door/status.json", timeout=3)
        return res.json()
    except Exception:
        return None

# UI 頁面頭部
st.title("🔑 門禁遠端控制與密碼解鎖")

# 顯示當前狀態
status = get_door_status()
col1, col2 = st.columns([2, 1])
with col1:
    if status == 1:
        st.success("🔓 目前狀態：開啟 (Unlocked)")
    elif status == 0:
        st.error("🔒 目前狀態：關閉 (Locked)")
    else:
        st.warning("⚠️ 狀態：讀取中 / 網路連線異常")

with col2:
    if st.button("🔄 刷新狀態", use_container_width=True):
        st.rerun()

st.divider()

# ==========================================
# 功能 A：網頁輸入密碼解鎖 (開門)
# ==========================================
st.subheader("🔓 網頁密碼解鎖")
input_pass = st.text_input("請輸入開門密碼：", type="password", placeholder="請輸入 5 位數密碼")

if st.button("🚀 驗證密碼並開門", type="primary", use_container_width=True):
    if not input_pass:
        st.warning("請先輸入密碼！")
    elif input_pass == SECRET_PASSWORD:
        if send_door_cmd(1):
            st.success("✅ 密碼正確！已發送【開門】指令至 Firebase！")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ 指令發送失敗，請檢查網路連線。")
    else:
        st.error("❌ 密碼錯誤，拒絕開門！")

st.divider()

# ==========================================
# 功能 B：一鍵關門 (通常關門不需要驗證密碼)
# ==========================================
st.subheader("🔒 一鍵關門")
if st.button("🔴 遠端關門", use_container_width=True):
    if send_door_cmd(0):
        st.success("✅ 已發送【關門】指令至 Firebase！")
        time.sleep(1)
        st.rerun()
    else:
        st.error("❌ 指令發送失敗，請檢查網路連線。")
