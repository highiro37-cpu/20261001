import streamlit as st
import pandas as pd
import requests
import altair as alt
import time

st.set_page_config(page_title="雙 Firebase 智慧管理系統", page_icon="🛡️", layout="centered")

# --- 1. 設定兩組獨立的 Firebase URL ---
# 門禁伺服器 (Door Server)
DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"
DOOR_URL = f"{DOOR_BASE_URL}/door.json"

# 環境伺服器 (Environment Server)
ENV_BASE_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app"
ENV_DATA_URL = f"{ENV_BASE_URL}/data.json"
ENV_HIST_URL = f"{ENV_BASE_URL}/history.json"

SENSORS = [
    ('temp', '🌡️ 溫度', '°C', '#FF4B4B'),
    ('hum', '💧 濕度', '%', '#1E88E5'), 
    ('pres', '🌪️ 氣壓', 'hPa', '#9C27B0'),
    ('light', '☀️ 光照', 'Lux', '#FFA000')
]

# --- API 存取工具函數 ---
def get_json(url):
    try:
        response = requests.get(url, timeout=3)
        return response.json() if response.status_code == 200 and response.json() else {}
    except Exception:
        return {}

def patch_json(url, data):
    try:
        requests.patch(url, json=data, timeout=3)
        return True
    except Exception:
        return False

# --- 頁面標題與側邊欄設定 ---
st.title("智慧環境與門禁控制中心")

with st.sidebar:
    st.header("⚙️ 系統設定")
    refresh_rate = st.slider("自動更新週期 (秒)", min_value=5, max_value=120, value=30, step=5)
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.rerun()

# --- 1. 門禁伺服器區域 ---
st.subheader("🚪 門禁狀態與遠端控制")

door_data = get_json(DOOR_URL)
door_status = door_data.get('status', '未知') if isinstance(door_data, dict) else '未知'

col1, col2 = st.columns(2)

with col1:
    if "開" in str(door_status) or door_status == "open":
        st.metric(label="目前門禁狀態", value="🟢 已開啟")
    else:
        st.metric(label="目前門禁狀態", value="🔴 已關閉 / 上鎖")
    st.caption(f"門禁 Server 同步狀態：{door_status}")

with col2:
    st.write("**🔐 遠端控制驗證**")
    pwd_input = st.text_input("輸入門禁密碼：", type="password", key="door_pwd")
    
    SECRET_PWD = st.secrets.get("DOOR_PASSWORD", "1234")
    
    if pwd_input == SECRET_PWD:
        st.success("✅ 驗證成功")
        action = st.radio("選擇控制指令：", ["開門", "關門"], horizontal=True)
        if st.button("🚀 發送控制指令", use_container_width=True):
            success = patch_json(DOOR_URL, {"control": action, "timestamp": int(time.time() * 1000)})
            if success:
                st.toast(f"已發送指令至門禁 Firebase！", icon="✅")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ 發送指令失敗，請檢查門禁 Server 連線。")
    elif pwd_input:
        st.error("❌ 密碼錯誤")
    else:
        st.info("💡 請輸入密碼解鎖控制權")

st.divider()

# --- 2. 環境伺服器區域 ---
st.subheader("🌍 環境感測器即時概覽")
d = get_json(ENV_DATA_URL)

ts = d.get('timestamp', 0) if isinstance(d, dict) else 0
ts_s = ts / 1000.0 if ts > 1e11 else ts
online = bool(ts and (time.time() - ts_s < 60))

last_t = pd.to_datetime(ts_s, unit='s', utc=True).tz_convert('Asia/Taipei').strftime('%m/%d %H:%M:%S') if ts else "未知"

cols = st.columns(2)
for i, (k, lbl, u, _) in enumerate(SENSORS):
    val = d.get(k, '--') if (online and isinstance(d, dict)) else '--'
    cols[i % 2].metric(lbl, f"{val} {u}")

if online:
    st.success(f"🟢 環境 ESP32 連線正常 (最後更新：{last_t})")
else:
    st.error(f"🔴 環境 ESP32 已離線 (最後更新：{last_t})")

st.divider()

# --- 3. 環境歷史趨勢圖 ---
st.subheader("📊 環境歷史趨勢")
h = get_json(ENV_HIST_URL)

if h and isinstance(h, dict):
    df = pd.DataFrame(list(h.values()))
    
    if 'timestamp' in df.columns:
        df['時間'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
    else:
        df['時間'] = df.index

    df = df.drop(columns=['timestamp'], errors='ignore').drop_duplicates('時間').sort_values('時間')
    
    max_len = len(df)
    limit = st.slider(f"顯示最近數據筆數（共 {max_len} 筆）：", min_value=5, max_value=max_len, value=min(30, max_len))
    sub = df.tail(limit)

    tabs = st.tabs([x[1] for x in SENSORS])
    for tab, (k, lbl, u, c) in zip(tabs, SENSORS):
        with tab:
            if k in sub.columns and not sub[k].empty:
                mi, ma = sub[k].min(), sub[k].max()
                p = (ma - mi) * 0.2 if ma > mi else 1
                
                base = alt.Chart(sub).encode(
                    x=alt.X('時間:T', axis=alt.Axis(format='%m/%d %H:%M', title='時間')),
                    y=alt.Y(f'{k}:Q', title=f'{lbl} ({u})', scale=alt.Scale(domain=[mi - p, ma + p])),
                    tooltip=[alt.Tooltip('時間:T', format='%Y-%m-%d %H:%M:%S'), f'{k}:Q']
                )
                chart = (
                    base.mark_area(color=c, opacity=0.15, interpolate='monotone') + 
                    base.mark_line(color=c, strokeWidth=3, interpolate='monotone') + 
                    base.mark_circle(color=c, size=40)
                ).properties(height=260)
                
                st.altair_chart(chart, use_container_width=True)
else:
    st.info("💡 尚未讀取到環境歷史資料。")

# --- 4. 定時無卡頓重新整理 ---
st.components.v1.html(
    f"""
    <script>
        setTimeout(function() {{
            window.parent.postMessage({{type: 'streamlit:rerun'}}, '*');
        }}, {refresh_rate * 1000});
    </script>
    """,
    height=0,
)
