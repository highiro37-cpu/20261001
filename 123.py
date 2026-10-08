import streamlit as st
import pandas as pd
import requests
import altair as alt
import numpy as np
import json
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


def make_perfect_chart(dataframe, y_col, label_name, unit, color, gap_pos, break_lines=False):
    """X 軸依「第幾筆」均分排列（n 筆就是 n 個等距的點），時間當標籤；資料中斷處斷線並畫虛線"""
    n = len(dataframe)
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

    # 標題放圖表上方，Y 軸不放標題，省出左側空間
    st.caption(f"{label_name} ({unit})")

    # X 軸刻度：6 筆以內每個點都標時間，更多則最多 4 個
    labels = dataframe['標籤'].tolist()
    if n > 1:
        tick_idx = sorted(set(int(round(v)) for v in np.linspace(0, n - 1, n if n <= 6 else 4)))
    else:
        tick_idx = [0]
    label_expr = json.dumps(labels, ensure_ascii=False) + "[datum.value]"

    x_enc = alt.X(
        '序:Q', title=None,
        scale=alt.Scale(domain=[-0.5, n - 0.5], nice=False),
        axis=alt.Axis(values=tick_idx, labelExpr=label_expr, labelAngle=0, grid=False,
                      labelOverlap='greedy', labelFlush=False),
    )

    y_enc = alt.Y(
        f'{y_col}:Q', title=None,
        scale=alt.Scale(domain=[domain_lo, domain_hi], nice=True),
        axis=alt.Axis(format=y_fmt, tickCount=5, labelOverlap=True, labelLimit=200),
    )
    tooltip = [
        alt.Tooltip('完整時間:N', title='時間'),
        alt.Tooltip(f'{y_col}:Q', title=label_name),
    ]
    cols = ['序', y_col, '標籤', '完整時間']

    # 每一段資料各自畫線與底色：中斷處自然斷開 (不依賴空值處理，各版本 Vega-Lite 都一致)
    # break_lines=False（預設）：跨日期 / 中斷的資料也連成一條線；True：中斷處斷開並畫虛線
    bounds = [0] + list(gap_pos) + [n] if break_lines else [0, n]
    layers = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        seg = dataframe.iloc[lo:hi][cols]
        if len(seg) < 2:
            continue  # 單點不成線，只畫圓點
        seg_base = alt.Chart(seg).encode(x=x_enc, y=y_enc, tooltip=tooltip)
        # y2 設在 Y 軸下緣以下並裁切，底色剛好填到圖表底部，不會蓋住時間標籤
        layers.append(seg_base.mark_area(color=color, opacity=0.15, interpolate='monotone', clip=True).encode(y2=alt.datum(domain_lo - (domain_hi - domain_lo))))
        layers.append(seg_base.mark_line(color=color, strokeWidth=3, interpolate='monotone'))

    points = alt.Chart(dataframe[cols]).encode(x=x_enc, y=y_enc, tooltip=tooltip).mark_circle(color=color, size=40)
    layers.append(points)

    if break_lines and gap_pos:
        rules = alt.Chart(pd.DataFrame({'序': [g - 0.5 for g in gap_pos]})).mark_rule(
            color='#9E9E9E', strokeDash=[4, 4], strokeWidth=1.5
        ).encode(x=x_enc)
        layers.append(rules)

    return alt.layer(*layers).properties(
        height=260,
        padding={"left": 10, "right": 20, "top": 10, "bottom": 10},
    )


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
        break_lines = st.checkbox("資料中斷處斷開連線（預設會連成一條線）", value=False, key="break_gaps")

        df_sub = df.tail(limit).copy()

        # 點太多手機會卡，超過 400 筆就等距抽樣
        step = 1
        if len(df_sub) > 400:
            step = -(-len(df_sub) // 400)
            df_sub = df_sub.iloc[::step].copy()

        df_sub = df_sub.reset_index(drop=True)
        df_sub['序'] = range(len(df_sub))

        # 時間標籤：資料跨日就加上日期，否則只顯示時:分
        label_fmt = '%m/%d %H:%M' if df_sub['時間'].dt.date.nunique() > 1 else '%H:%M'
        df_sub['標籤'] = df_sub['時間'].dt.strftime(label_fmt)
        df_sub['完整時間'] = df_sub['時間'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # 偵測資料中斷（感測器離線期間）：超過 3 倍正常間隔就視為斷點
        normal_gap = df['時間'].diff().median()
        if pd.isna(normal_gap):
            normal_gap = pd.Timedelta(minutes=1)
        gap_limit = max(normal_gap * 3 * step, pd.Timedelta(minutes=3))
        time_diff = df_sub['時間'].diff()
        gap_pos = [int(i) for i in df_sub.index[time_diff > gap_limit]]

        if gap_pos:
            shown = []
            for i in gap_pos[-3:]:
                end_t = df_sub.loc[i, '時間']
                start_t = df_sub.loc[i - 1, '時間']
                shown.append(f"{start_t.strftime('%m/%d %H:%M')} → {end_t.strftime('%m/%d %H:%M')}")
            st.caption("⚠️ 此範圍內有資料中斷（感測器離線期間沒有資料）：" + "；".join(shown))

        t1, t2, t3, t4 = st.tabs(["🌡️ 溫度", "💧 濕度", "🌪 氣壓", "☀️ 光照"])

        with t1:
            if 'temp' in df_sub.columns and not df_sub['temp'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'temp', '溫度', '°C', '#FF4B4B', gap_pos, break_lines), use_container_width=True)

        with t2:
            if 'hum' in df_sub.columns and not df_sub['hum'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'hum', '濕度', '%', '#1E88E5', gap_pos, break_lines), use_container_width=True)

        with t3:
            if 'pres' in df_sub.columns and not df_sub['pres'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'pres', '氣壓', 'hPa', '#9C27B0', gap_pos, break_lines), use_container_width=True)

        with t4:
            if 'light' in df_sub.columns and not df_sub['light'].empty:
                st.altair_chart(make_perfect_chart(df_sub, 'light', '光照', 'ADC', '#FFA000', gap_pos, break_lines), use_container_width=True)

    else:
        st.info("💡 尚未讀取到歷史資料。")
