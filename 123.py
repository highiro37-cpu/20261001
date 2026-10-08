import streamlit as st
import pandas as pd
import requests
import altair as alt
import time

# ==========================================
# 0. 系統設定與 Firebase 網址配置
# ==========================================
st.set_page_config(page_title="ESP32 智慧儀表板", page_icon="🌐", layout="centered")

ENV_DATA_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/data.json"
ENV_HISTORY_URL = "https://project-6542053176802607257-default-rtdb.asia-southeast1.firebasedatabase.app/history.json"
DOOR_BASE_URL = "https://project-4996744582843641951-default-rtdb.asia-southeast1.firebasedatabase.app"

SECRET_PASSWORD = "13579"


HISTORY_SLIDER_MAX = 1000  # 歷史圖滑桿上限 (固定值，避免滑桿被重設)
MAX_LOG = 1000  # 資料庫最多保留幾筆事件，超過會自動刪除最舊的
HEARTBEAT_TIMEOUT = 20  # 超過幾秒沒收到心跳就視為斷電/離線


def fetch_json(url):
    try:
        res = requests.get(url, timeout=3)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=5, show_spinner=False)
def fetch_env_data():
    return fetch_json(ENV_DATA_URL)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_history():
    return fetch_json(ENV_HISTORY_URL)


@st.cache_data(ttl=2, show_spinner=False)
def get_door_info():
    """一次讀取 door 節點 (status / heartbeat)，2 秒內共用快取，多人開網頁也只打一次 Firebase"""
    return fetch_json(f"{DOOR_BASE_URL}/door.json")


def send_door_cmd(cmd_val):
    """control: 1 = 開門, 2 = 關門 (ESP32 處理完會自動重設為 0)"""
    try:
        res = requests.put(f"{DOOR_BASE_URL}/door/control.json", json=int(cmd_val), timeout=3)
        if res.status_code == 200:
            st.session_state['predicted_door_status'] = 1 if int(cmd_val) == 1 else 0
            get_door_info.clear()
            return True
        return False
    except Exception:
        return False


@st.cache_data(ttl=5, show_spinner=False)
def fetch_door_log(limit=15):
    """只取最近 limit 筆事件"""
    try:
        res = requests.get(
            f"{DOOR_BASE_URL}/door/log.json",
            params={"orderBy": '"$key"', "limitToLast": int(limit)},
            timeout=3,
        )
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def trim_door_log():
    """最多每 10 分鐘檢查一次：只下載 key 清單，超過 MAX_LOG 就刪除最舊的"""
    try:
        res = requests.get(f"{DOOR_BASE_URL}/door/log.json", params={"shallow": "true"}, timeout=5)
        if res.status_code != 200 or not isinstance(res.json(), dict):
            return 0
        keys = sorted(res.json().keys())  # push key 依時間排序，越前面越舊
        extra = len(keys) - MAX_LOG
        if extra <= 0:
            return 0
        body = {k: None for k in keys[:extra]}  # null = 刪除
        r = requests.patch(f"{DOOR_BASE_URL}/door/log.json", json=body, timeout=10)
        return extra if r.status_code == 200 else 0
    except Exception:
        return 0


EVENT_NAMES = {
    "RFID_OPEN": "💳 刷卡開門",
    "RFID_DENIED": "🚫 刷卡失敗（未知卡片）",
    "PASSWORD_OPEN": "⌨️ 密碼開門",
    "PASSWORD_FAIL": "🚫 密碼錯誤",
    "WEB_OPEN": "🌐 網頁遠端開門",
    "WEB_CLOSE": "🌐 網頁遠端關門",
    "BLYNK_OPEN": "📱 Blynk 遠端開門",
    "AUTO_CLOSE": "⏱️ 逾時自動關門",
}


def parse_status(val):
    if val is None:
        return None
    val_str = str(val).strip().lower()
    if val_str in ["1", "true"]:
        return 1
    if val_str in ["0", "false"]:
        return 0
    return None


def fmt_ts(ts_ms):
    return pd.to_datetime(ts_ms, unit='ms', utc=True).tz_convert('Asia/Taipei').strftime('%Y/%m/%d %H:%M:%S')


if 'predicted_door_status' not in st.session_state:
    st.session_state['predicted_door_status'] = None

# ==========================================
# 側邊欄：自動重新整理控制面板
# ==========================================
st.sidebar.header("⚙️ 網頁自動更新設定")
auto_refresh = st.sidebar.checkbox("開啟狀態自動更新", value=True)
refresh_interval = st.sidebar.slider("更新頻率 (秒)", min_value=2, max_value=30, value=3, step=1)

if auto_refresh:
    st.sidebar.caption(f"⏱️ 狀態每 **{refresh_interval} 秒** 自動更新一次")

# None 代表不自動更新
refresh_every = refresh_interval if auto_refresh else None
# 環境數據不需要太頻繁，最少 10 秒
env_refresh_every = max(refresh_interval, 10) if auto_refresh else None


# ==========================================
# 自動更新區塊 (fragment：只局部刷新，不會重置分頁/滑桿)
# ==========================================
@st.fragment(run_every=refresh_every)
def door_status_panel():
    info = get_door_info()
    info = info if isinstance(info, dict) else {}

    heartbeat = info.get('heartbeat')
    real_status = parse_status(info.get('status'))

    # 判斷 ESP32 是否還在運作 (用心跳時間判斷)
    online = False
    age_sec = None
    if isinstance(heartbeat, (int, float)):
        age_sec = time.time() - heartbeat / 1000.0
        online = age_sec < HEARTBEAT_TIMEOUT

    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        if online:
            if real_status is not None:
                st.session_state['predicted_door_status'] = real_status
            door_status = real_status if real_status is not None else st.session_state.get('predicted_door_status')
            if door_status == 1:
                st.success("🔓 目前狀態：門鎖已開啟 (Unlocked)")
            elif door_status == 0:
                st.error("🔒 目前狀態：門鎖已關閉 (Locked)")
            else:
                st.warning("⚠ 門禁狀態：讀取中")
        else:
            st.session_state['predicted_door_status'] = None
            st.warning("⚠ 門鎖狀態未知（設備已斷電 / 離線）")

    with col_d2:
        st.button("🔄 手動刷新", key="btn_refresh_door", use_container_width=True)

    last_open = info.get('last_open')
    if isinstance(last_open, dict) and isinstance(last_open.get('t'), (int, float)):
        by = EVENT_NAMES.get(last_open.get('by'), last_open.get('by', ''))
        st.info(f"🕒 **最近一次開門**：{fmt_ts(last_open['t'])}（{by}）")
    else:
        st.info("🕒 **最近一次開門**：尚無紀錄")

    if online:
        st.caption(f"🟢 **設備狀態：運作中** | 最後心跳：{fmt_ts(heartbeat)}（{int(age_sec)} 秒前）")
    elif isinstance(heartbeat, (int, float)):
        st.caption(f"🔴 **設備狀態：已斷電 / 離線** | 最後運作時間：**{fmt_ts(heartbeat)}**")
    elif info:
        st.caption("🔴 **設備狀態：尚未收到過心跳**（請確認 ESP32 已更新程式）")
    else:
        st.caption("🔴 **設備狀態：無法連線到 Firebase**")


    trim_door_log()  # 有快取，實際最多每 10 分鐘才會執行一次

    with st.expander("📜 最近事件紀錄（最新在上）"):
        show_n = st.selectbox("顯示筆數", [15, 50, 100, 200], index=0, key="log_show_n")
        st.caption(f"資料庫最多保留最近 {MAX_LOG} 筆，更舊的會自動刪除")
        log = fetch_door_log(show_n)
        if isinstance(log, dict) and log:
            rows = []
            for k in sorted(log.keys(), reverse=True):
                item = log[k]
                if isinstance(item, dict) and isinstance(item.get('t'), (int, float)):
                    rows.append({"時間": fmt_ts(item['t']), "事件": EVENT_NAMES.get(item.get('e'), item.get('e', ''))})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            else:
                st.caption("尚無紀錄")
        else:
            st.caption("尚無紀錄")


@st.fragment(run_every=env_refresh_every)
def env_live_panel():
    data = fetch_env_data()
    col1, col2 = st.columns(2)

    is_online = False
    last_update_str = "未知"

    if data and isinstance(data, dict):
        ts = data.get('timestamp', None)

        if ts:
            ts_sec = ts / 1000.0 if ts > 1e11 else ts
            last_update_str = pd.to_datetime(ts_sec, unit='s', utc=True).tz_convert('Asia/Taipei').strftime('%Y/%m/%d %H:%M:%S')
            if (time.time() - ts_sec) < 60:
                is_online = True

        if is_online:
            temp_val = f"{data.get('temp', '--')} °C"
            pres_val = f"{data.get('pres', '--')} hPa"
            hum_val = f"{data.get('hum', '--')} %"
            light_val = f"{data.get('light', '--')} Lux"
        else:
            temp_val, pres_val, hum_val, light_val = "-- °C", "-- hPa", "-- %", "-- Lux"

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

    door_status_panel()

    st.divider()

    st.subheader("⚡ 一鍵遠端開鎖")
    if st.button("🔓 立即遠端開門", type="primary", use_container_width=True, key="btn_direct_open"):
        if send_door_cmd(1):
            st.success("✅ 開門指令已發送！")
        else:
            st.error("❌ 開門指令發送失敗")

    st.divider()

    st.subheader("🔐 網頁密碼解鎖")
    input_pass = st.text_input("請輸入開門密碼：", type="password", placeholder="請輸入密碼", key="pwd_input")

    if st.button("🚀 驗證密碼並開門", use_container_width=True, key="btn_pass_open"):
        if not input_pass:
            st.warning("請先輸入密碼！")
        elif input_pass == SECRET_PASSWORD:
            if send_door_cmd(1):
                st.success("✅ 密碼正確！已發送【開門】指令！")
            else:
                st.error("❌ 指令發送失敗")
        else:
            st.error("❌ 密碼錯誤，拒絕開門！")

    st.divider()

    st.subheader("🔒 一鍵關門")
    if st.button("🔴 遠端關門", use_container_width=True, key="btn_close_door"):
        if send_door_cmd(2):
            st.success("✅ 已發送【關門】指令！")
        else:
            st.error("❌ 關門指令發送失敗")

# ==========================================
# 分頁 2：即時與歷史環境監控
# ==========================================
with page_tab2:
    st.header("🌍 即時環境數據概覽")

    env_live_panel()

    st.divider()

    st.subheader("📊 歷史趨勢圖")

    history_data = fetch_history()

    if history_data and isinstance(history_data, dict):
        records = list(history_data.values())
        df = pd.DataFrame(records)

        if 'timestamp' in df.columns:
            # 同時相容秒 / 毫秒，並轉成台北時間（原本沒轉換，顯示的是 UTC，差 8 小時）
            ts = pd.to_numeric(df['timestamp'], errors='coerce')
            ts_ms = ts.where(ts > 1e11, ts * 1000)
            df['時間'] = pd.to_datetime(ts_ms, unit='ms', utc=True).dt.tz_convert('Asia/Taipei').dt.tz_localize(None)
            df = df.dropna(subset=['時間'])
            df = df.drop(columns=['timestamp'])
        else:
            df['時間'] = df.index

        df = df.drop_duplicates(subset=['時間']).sort_values('時間')

        total_records = len(df)

        # 滑桿的標籤、最小/最大值都固定不變，資料筆數增加時不會被重設 (原本會「跑掉」就是因為這些會變)
        slider_n = st.slider(
            "顯示最近幾筆資料",
            min_value=5,
            max_value=HISTORY_SLIDER_MAX,
            value=30,
            step=5,
            key="history_limit",
        )
        limit = min(slider_n, total_records)
        st.caption(f"目前共 {total_records} 筆歷史紀錄，圖表顯示最近 {limit} 筆")

        df_sub = df.tail(limit).copy()

        # 點太多手機會卡，超過 400 筆就等距抽樣
        if len(df_sub) > 400:
            step = -(-len(df_sub) // 400)
            df_sub = df_sub.iloc[::step].copy()

        def make_perfect_chart(dataframe, y_col, label_name, unit, color):
            y_min = float(dataframe[y_col].min())
            y_max = float(dataframe[y_col].max())

            # Y 軸最小範圍：變化很小時不要放大，避免 25.3→25.2 看起來像斷崖式下降
            min_span = {'temp': 4.0, 'hum': 10.0, 'pres': 4.0, 'light': 200.0}.get(y_col, 1.0)
            if (y_max - y_min) < min_span:
                mid = (y_max + y_min) / 2
                domain_lo, domain_hi = mid - min_span / 2, mid + min_span / 2
            else:
                padding = (y_max - y_min) * 0.1
                domain_lo, domain_hi = y_min - padding, y_max + padding
            y_fmt = '.0f' if y_col == 'light' else '.1f'

            span = dataframe['時間'].max() - dataframe['時間'].min()
            x_format = '%m/%d %H:%M' if span > pd.Timedelta(days=1) else '%H:%M'

            # 標題改放圖表上方，Y 軸不放標題，省出左側空間避免數字被截掉
            st.caption(f"{label_name} ({unit})")

            base = alt.Chart(dataframe).encode(
                x=alt.X(
                    '時間:T', title=None,
                    axis=alt.Axis(format=x_format, tickCount=4, labelAngle=0, labelOverlap='greedy', labelFlush=False),
                ),
                y=alt.Y(
                    f'{y_col}:Q', title=None,
                    scale=alt.Scale(domain=[domain_lo, domain_hi], nice=True),
                    axis=alt.Axis(format=y_fmt, tickCount=5, labelOverlap=True, labelLimit=200),
                ),
                tooltip=[
                    alt.Tooltip('時間:T', title='時間', format='%Y-%m-%d %H:%M:%S'),
                    alt.Tooltip(f'{y_col}:Q', title=label_name),
                ],
            )

            line = base.mark_line(color=color, strokeWidth=3, interpolate='monotone')
            points = base.mark_circle(color=color, size=40)
            area = base.mark_area(color=color, opacity=0.15, interpolate='monotone')

            return (area + line + points).properties(
                height=260,
                padding={"left": 10, "right": 20, "top": 10, "bottom": 10},
            )

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
