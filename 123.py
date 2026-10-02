import streamlit as st, pandas as pd, requests, altair as alt, time

st.set_page_config(page_title="ESP32 環境與門禁管理", page_icon="🛡️", layout="centered")

BASE_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app"
DATA_URL = f"{BASE_URL}/data.json"
HIST_URL = f"{BASE_URL}/history.json"
DOOR_URL = f"{BASE_URL}/door.json"  # 門禁資料節點

SENSORS = [('temp', '🌡️ 溫度', '°C', '#FF4B4B'), ('hum', '💧 濕度', '%', '#1E88E5'), 
           ('pres', '🌪️ 氣壓', 'hPa', '#9C27B0'), ('light', '☀️ 光照', 'Lux', '#FFA000')]

def get_json(url):
    try: return requests.get(url, timeout=3).json() or {}
    except: return {}

def patch_json(url, data):
    try: requests.patch(url, json=data, timeout=3)
    except: pass

st.title("智慧環境與門禁控制中心")
if st.button("🔄 立即重新整理"): st.rerun()

# --- 1. 智慧門禁狀態與線上控制 ---
st.subheader("🚪 門禁狀態與遠端控制")

door_data = get_json(DOOR_URL)
door_status = door_data.get('status', '未知') if isinstance(door_data, dict) else '未知'

col1, col2 = st.columns(2)

with col1:
    if "開" in str(door_status):
        st.metric(label="目前門禁狀態", value="🟢 已開啟")
    else:
        st.metric(label="目前門禁狀態", value="🔴 已關閉 / 上鎖")
    st.caption(f"最後同步狀態：{door_status}")

with col2:
    st.write("**🔐 遠端控制驗證**")
    pwd_input = st.text_input("輸入門禁密碼：", type="password", key="door_pwd")
    
    # 預設設定密碼為 1234 (可自行修改)
    if pwd_input == "1234":
        st.success("✅ 密碼驗證成功")
        action = st.radio("選擇控制指令：", ["開門", "關門"], horizontal=True)
        if st.button("🚀 發送控制指令"):
            patch_json(DOOR_URL, {"control": action, "timestamp": int(time.time() * 1000)})
            st.toast(f"已送出「{action}」指令給 ESP32！")
            time.sleep(1)
            st.rerun()
    else:
        if pwd_input:
            st.error("❌ 密碼錯誤，無法控制")
        else:
            st.info("💡 請輸入密碼解鎖遠端控制權")

st.divider()

# --- 2. 環境數據即時概覽 ---
st.subheader("🌍 環境感測器即時概覽")
d = get_json(DATA_URL)
ts = d.get('timestamp', 0) if isinstance(d, dict) else 0
ts_s = ts / 1000.0 if ts > 1e11 else ts
online = bool(ts and (time.time() - ts_s < 60))
last_t = pd.to_datetime(ts_s, unit='s', utc=True).tz_convert('Asia/Taipei').strftime('%m/%d %H:%M:%S') if ts else "未知"

cols = st.columns(2)
for i, (k, lbl, u, _) in enumerate(SENSORS):
    cols[i%2].metric(lbl, f"{d.get(k,'--')} {u}" if (online and isinstance(d, dict)) else f"-- {u}")

if online:
    st.success(f"🟢 設備連線正常 (最後更新：{last_t})")
else:
    st.error(f"🔴 設備已離線 (最後更新：{last_t})")

st.divider()

# --- 3. 歷史趨勢圖 ---
st.subheader("📊 環境歷史趨勢")
h = get_json(HIST_URL)
if h and isinstance(h, dict):
    df = pd.DataFrame(list(h.values()))
    df['時間'] = pd.to_datetime(df['timestamp'], unit='ms') if 'timestamp' in df else df.index
    df = df.drop(columns=['timestamp'], errors='ignore').drop_duplicates('時間').sort_values('時間')
    
    limit = st.slider(f"顯示最近數據筆數（共 {len(df)} 筆）：", 5, len(df), min(30, len(df)))
    sub = df.tail(limit)

    tabs = st.tabs([x[1] for x in SENSORS])
    for tab, (k, lbl, u, c) in zip(tabs, SENSORS):
        with tab:
            if k in sub.columns and not sub[k].empty:
                mi, ma = sub[k].min(), sub[k].max()
                p = (ma - mi) * 0.2 if ma > mi else 1
                base = alt.Chart(sub).encode(
                    x=alt.X('時間:T', axis=alt.Axis(format='%m/%d %H:%M')),
                    y=alt.Y(f'{k}:Q', title=f'{lbl} ({u})', scale=alt.Scale(domain=[mi-p, ma+p])),
                    tooltip=['時間:T', f'{k}:Q']
                )
                chart = (base.mark_area(color=c, opacity=0.15, interpolate='monotone') + 
                         base.mark_line(color=c, strokeWidth=3, interpolate='monotone') + 
                         base.mark_circle(color=c, size=40)).properties(height=240)
                st.altair_chart(chart, use_container_width=True)
else:
    st.info("💡 尚未讀取到歷史資料。")

time.sleep(60)
st.rerun()
