import streamlit as st
import pandas as pd
import requests
import altair as alt
import time

# ==========================================
# 0. 系統設定與 Firebase 網址配置
# ==========================================
st.set_page_config(page_title="ESP32 智慧儀表板", page_icon="🌐", layout="centered")

# 環境監控 Firebase 網址
ENV_DATA_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/data.json"
ENV_HISTORY_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/history.json"

# 門禁系統 Firebase 網址
DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

# 預設開門密碼
SECRET_PASSWORD = "13579"

def fetch_json(url):
    try:
        res = requests.get(url, timeout=3)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

def send_door_cmd(cmd_val):
    try:
        res = requests.put(f"{DOOR_BASE_URL}/door/control.json", json=cmd_val, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

def get_door_status():
    try:
        res = requests.get(f"{DOOR_BASE_URL}/door/status.json", timeout=3)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None

# ==========================================
# 側邊欄：自動重新整理控制面板
# ==========================================
st.sidebar.header("⚙️ 網頁自動更新設定")
auto_refresh = st.sidebar.checkbox("開啟狀態自動更新", value=True)
refresh_interval = st.sidebar.slider("更新頻率 (秒)", min_value=2, max_value=30, value=3, step=1)

if auto_refresh:
    st.sidebar.caption(f"⏱️ 網頁每 **{refresh_interval} 秒** 背景自動刷新一次")

# ==========================================
# 頁面主導覽 (Tabs 分頁)
# ==========================================
st.title("🌐 ESP32 智慧管理系統")
page_tab1, page_tab2 = st.tabs(["🔑 遠端門禁控制", "📊 環境數據監控"])

# ==========================================
# 分頁 1：遠端門禁控制
# ==========================================
with page_tab1:
    st.header("🔑 門禁遠端控制")
    
    door_status = get_door_status()
    col_d1, col_d2 = st.columns([2, 1])
    
    with col_d1:
        if door_status == 1:
            st.success("🔓 目前狀態：門鎖已開啟 (Unlocked)")
        elif door_status == 0:
            st.error("🔒 目前狀態：門鎖已關閉 (Locked)")
        else:
            st.warning("⚠️️ 門禁狀態：連線中 / 無法讀取")
            
    with col_d2:
        if st.button("🔄 手動刷新", key="btn_refresh_door", use_container_width=True):
            st.rerun()

    # --- 門禁設備連線狀態標示 ---
    if door_status in [0, 1]:
        st.caption(f"🟢 **設備狀態**：ESP32 門禁控制器連線正常 | 最後擷取：{time.strftime('%H:%M:%S')}")
    else:
        st.caption("🔴 **設備狀態**：ESP32 門禁控制器離線或網路異常")

    st.divider()

    # --- 方式 1：一鍵遠端開門 ---
    st.subheader("⚡ 一鍵遠端開鎖")
    if st.button("🔓 立即遠端開門 (1)", type="primary", use_container_width=True, key="btn_direct_open"):
        if send_door_cmd(1):
            st.success("✅ 開門指令已發送！")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("❌ 開門指令發送失敗")

    st.divider()

    # --- 方式 2：密碼驗證開門 ---
    st.subheader("🔐 網頁密碼解鎖")
    input_pass = st.text_input("請輸入開門密碼：", type="password", placeholder="請輸入密碼", key="pwd_input")

    if st.button("🚀 驗證密碼並開門", use_container_width=True, key="btn_pass_open"):
        if not input_pass:
            st.warning("請先輸入密碼！")
        elif input_pass == SECRET_PASSWORD:
            if send_door_cmd(1):
                st.success("✅ 密碼正確！已發送【開門】指令！")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ 指令發送失敗")
        else:
            st.error("❌ 密碼錯誤，拒絕開門！")

    st.divider()

    # --- 關門功能 ---
    st.subheader("🔒 一鍵關門")
    if st.button("🔴 遠端關門 (0)", use_container_width=True, key="btn_close_door"):
        if send_door_cmd(0):
            st.success("✅ 已發送【關門】指令！")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("❌ 關門指令發送失敗")

# ==========================================
# 分頁 2：即時與歷史環境監控
# ==========================================
with page_tab2:
    st.header("🌍 即時環境數據概覽")

    data = fetch_json(ENV_DATA_URL)
    col1, col2 = st.columns(2)

    is_online = False
    last_update_str = "未知"

    if data and isinstance(data, dict):
        ts = data.get('timestamp', None)

        if ts:
            ts_sec = ts / 1000.0 if ts > 1e11 else ts
            last_update_str = pd.to_datetime(ts_sec, unit='s', utc=True).tz_convert('Asia/Taipei').strftime('%Y/%m/%d %H:%M:%S')

            now_sec = time.time()
            if (now_sec - ts_sec) < 60:
                is_online = True

        if is_online:
            temp_val = f"{data.get('temp', '--')} °C"
            pres_val = f"{data.get('pres', '--')} hPa"
            hum_val = f"{data.get('hum', '--')} %"
            light_val = f"{data.get('light', '--')} Lux"
        else:
            temp_val = "-- °C"
            pres_val = "-- hPa"
            hum_val = "-- %"
            light_val = "-- Lux"

        with col1:
            st.metric(label="🌡️ 溫度", value=temp_val)
            st.metric(label="🌪️ 氣壓", value=pres_val)
        with col2:
            st.metric(label="💧 濕度", value=hum_val)
            st.metric(label="☀️ 光照", value=light_val)

        if is_online:
            st.success(f"🟢 環境感測器連線正常 (最後更新：{last_update_str})")
        else:
            st.error(f"🔴 環境感測器已離線 / 斷線 (最後更新：{last_update_str})")
    else:
        with col1:
            st.metric(label="🌡️ 溫度", value="-- °C")
            st.metric(label="🌪️ 氣壓", value="-- hPa")
        with col2:
            st.metric(label="💧 濕度", value="-- %")
            st.metric(label="☀️ 光照", value="-- Lux")
        st.error("🔴 無法讀取 Firebase 數據或設備離線")

    st.divider()

    # --- 歷史趨勢圖 ---
    st.subheader("📊 歷史趨勢圖")

    history_data = fetch_json(ENV_HISTORY_URL)

    if history_data and isinstance(history_data, dict):
        records = list(history_data.values())
        df = pd.DataFrame(records)

        if 'timestamp' in df.columns:
            df['時間'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop(columns=['timestamp'])
        else:
            df['時間'] = df.index

        df = df.drop_duplicates(subset=['時間']).sort_values('時間')

        total_records = len(df)
        default_value = min(30, total_records)

        limit = st.slider(
            f"顯示最近數據筆數（當前共 {total_records} 筆歷史紀錄）：", 
            min_value=min(5, total_records), 
            max_value=total_records, 
            value=default_value, 
            step=1,
            key="history_slider"
        )

        df_sub = df.tail(limit).copy()

        def make_perfect_chart(dataframe, y_col, label_name, unit, color):
            y_min = dataframe[y_col].min()
            y_max = dataframe[y_col].max()
            padding = (y_max - y_min) * 0.2 if (y_max - y_min) > 0 else 1
            
            domain_min = y_min - padding
            domain_max = y_max + padding

            base = alt.Chart(dataframe).encode(
                x=alt.X('時間:T', title='時間', axis=alt.Axis(format='%m/%d %H:%M')),
                y=alt.Y(
                    f'{y_col}:Q', 
                    title=f'{label_name} ({unit})', 
                    scale=alt.Scale(domain=[domain_min, domain_max])
                ),
                tooltip=[alt.Tooltip('時間:T', title='時間', format='%Y-%m-%d %H:%M:%S'), alt.Tooltip(f'{y_col}:Q', title=label_name)]
            )
            
            line = base.mark_line(color=color, strokeWidth=3, interpolate='monotone')
            points = base.mark_circle(color=color, size=40)
            area = base.mark_area(color=color, opacity=0.15, interpolate='monotone')

            return (area + line + points).properties(height=260)

        t1, t2, t3, t4 = st.tabs(["🌡️ 溫度", "💧 濕度", "🌪 氣壓", "☀️ 光照"])

        with t1:
            if 'temp' in df_sub.columns and not df_sub['temp'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'temp', '溫度', '°C', '#FF4B4B'), use_container_width=True)

        with t2:
            if 'hum' in df_sub.columns and not df_sub['hum'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'hum', '濕度', '%', '#1E88E5'), use_container_width=True)

        with t3:
            if 'pres' in df_sub.columns and not df_sub['pres'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'pres', '氣壓', 'hPa', '#9C27B0'), use_container_width=True)

        with t4:
            if 'light' in df_sub.columns and not df_sub['light'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'light', '光照', 'ADC', '#FFA000'), use_container_width=True)

    else:
        st.info("💡 尚未讀取到歷史資料。")

# ==========================================
# 原生 JS 自動定時重新整理 (完全免安裝額外套件)
# ==========================================
# ==========================================
# 原生 JS 自動定時重新整理 (修正 f-string 大括號轉義)
# ==========================================
if auto_refresh:
    st.components.v1.html(
        f"""
        <script>
            setTimeout(function(){{
                window.parent.postMessage({{{{type: 'streamlit:render'}}}}, '*');
                window.parent.location.reload();
            }}, {refresh_interval * 1000});
        </script>
        """,
        height=0,
    )
