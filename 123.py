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

MAX_LOG = 1000
HEARTBEAT_TIMEOUT = 20

# ==========================================
# 時區設定
# ==========================================
TAIWAN_TZ = "Asia/Taipei"


# ==========================================
# 通用 Firebase 讀取
# ==========================================
def fetch_json(url):
    try:
        res = requests.get(url, timeout=3)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# ==========================================
# 時間處理
# ==========================================
def timestamp_to_taiwan(ts):
    """
    Firebase timestamp 自動判斷：
    13 位數 = 毫秒
    10 位數 = 秒

    最後統一轉成台灣時間 UTC+8
    """
    try:
        if ts is None:
            return None

        ts = float(ts)

        # 13 位數：毫秒
        if ts > 1e11:
            dt = pd.to_datetime(ts, unit="ms", utc=True)

        # 10 位數：秒
        else:
            dt = pd.to_datetime(ts, unit="s", utc=True)

        return dt.tz_convert(TAIWAN_TZ)

    except Exception:
        return None


def fmt_ts(ts):
    """Firebase timestamp → 台灣時間文字"""
    dt = timestamp_to_taiwan(ts)

    if dt is None:
        return "時間未知"

    return dt.strftime("%Y/%m/%d %H:%M:%S")


# ==========================================
# 環境資料
# ==========================================
@st.cache_data(ttl=5, show_spinner=False)
def fetch_env_data():
    return fetch_json(ENV_DATA_URL)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_history():
    return fetch_json(ENV_HISTORY_URL)


# ==========================================
# 門禁資料
# ==========================================
@st.cache_data(ttl=2, show_spinner=False)
def get_door_info():
    return fetch_json(f"{DOOR_BASE_URL}/door.json")


def send_door_cmd(cmd_val):
    """
    control:
    1 = 開門
    2 = 關門
    ESP32 處理後自動重設為 0
    """
    try:
        res = requests.put(
            f"{DOOR_BASE_URL}/door/control.json",
            json=int(cmd_val),
            timeout=3
        )

        if res.status_code == 200:
            st.session_state["predicted_door_status"] = (
                1 if int(cmd_val) == 1 else 0
            )

            get_door_info.clear()
            return True

        return False

    except Exception:
        return False


@st.cache_data(ttl=5, show_spinner=False)
def fetch_door_log(limit=15):
    try:
        res = requests.get(
            f"{DOOR_BASE_URL}/door/log.json",
            params={
                "orderBy": '"$key"',
                "limitToLast": int(limit)
            },
            timeout=3
        )

        return res.json() if res.status_code == 200 else None

    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def trim_door_log():
    try:
        res = requests.get(
            f"{DOOR_BASE_URL}/door/log.json",
            params={"shallow": "true"},
            timeout=5
        )

        if res.status_code != 200:
            return 0

        data = res.json()

        if not isinstance(data, dict):
            return 0

        keys = sorted(data.keys())

        extra = len(keys) - MAX_LOG

        if extra <= 0:
            return 0

        body = {
            k: None
            for k in keys[:extra]
        }

        r = requests.patch(
            f"{DOOR_BASE_URL}/door/log.json",
            json=body,
            timeout=10
        )

        return extra if r.status_code == 200 else 0

    except Exception:
        return 0


# ==========================================
# 門禁事件名稱
# ==========================================
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


# ==========================================
# Session State
# ==========================================
if "predicted_door_status" not in st.session_state:
    st.session_state["predicted_door_status"] = None


# ==========================================
# 側邊欄：自動更新
# ==========================================
st.sidebar.header("⚙️ 網頁自動更新設定")

auto_refresh = st.sidebar.checkbox(
    "開啟狀態自動更新",
    value=True
)

refresh_interval = st.sidebar.slider(
    "更新頻率 (秒)",
    min_value=2,
    max_value=30,
    value=3,
    step=1
)

if auto_refresh:
    st.sidebar.caption(
        f"⏱️ 狀態每 **{refresh_interval} 秒** 自動更新一次"
    )

refresh_every = refresh_interval if auto_refresh else None

env_refresh_every = (
    max(refresh_interval, 10)
    if auto_refresh
    else None
)


# ==========================================
# 門禁即時狀態
# ==========================================
@st.fragment(run_every=refresh_every)
def door_status_panel():

    info = get_door_info()

    info = info if isinstance(info, dict) else {}

    heartbeat = info.get("heartbeat")

    real_status = parse_status(
        info.get("status")
    )

    # -----------------------------
    # 判斷 ESP32 是否在線
    # -----------------------------
    online = False
    age_sec = None

    if isinstance(heartbeat, (int, float)):

        heartbeat_dt = timestamp_to_taiwan(
            heartbeat
        )

        if heartbeat_dt is not None:

            age_sec = (
                time.time()
                - heartbeat_dt.timestamp()
            )

            online = age_sec < HEARTBEAT_TIMEOUT

    # -----------------------------
    # 門鎖狀態
    # -----------------------------
    col_d1, col_d2 = st.columns([2, 1])

    with col_d1:

        if online:

            if real_status is not None:
                st.session_state[
                    "predicted_door_status"
                ] = real_status

            door_status = (
                real_status
                if real_status is not None
                else st.session_state.get(
                    "predicted_door_status"
                )
            )

            if door_status == 1:

                st.success(
                    "🔓 目前狀態：門鎖已開啟 (Unlocked)"
                )

            elif door_status == 0:

                st.error(
                    "🔒 目前狀態：門鎖已關閉 (Locked)"
                )

            else:

                st.warning(
                    "⚠ 門禁狀態：讀取中"
                )

        else:

            st.session_state[
                "predicted_door_status"
            ] = None

            st.warning(
                "⚠ 門鎖狀態未知（設備已斷電 / 離線）"
            )

    with col_d2:

        st.button(
            "🔄 手動刷新",
            key="btn_refresh_door",
            use_container_width=True
        )

    # -----------------------------
    # 最近一次開門
    # -----------------------------
    last_open = info.get("last_open")

    if (
        isinstance(last_open, dict)
        and isinstance(last_open.get("t"), (int, float))
    ):

        by = EVENT_NAMES.get(
            last_open.get("by"),
            last_open.get("by", "")
        )

        st.info(
            f"🕒 **最近一次開門**："
            f"{fmt_ts(last_open['t'])}"
            f"（{by}）"
        )

    else:

        st.info(
            "🕒 **最近一次開門**：尚無紀錄"
        )

    # -----------------------------
    # 設備狀態
    # -----------------------------
    if online:

        st.caption(
            f"🟢 **設備狀態：運作中** | "
            f"最後心跳：{fmt_ts(heartbeat)}"
            f"（{int(age_sec)} 秒前）"
        )

    elif isinstance(heartbeat, (int, float)):

        st.caption(
            f"🔴 **設備狀態：已斷電 / 離線** | "
            f"最後運作時間：**{fmt_ts(heartbeat)}**"
        )

    elif info:

        st.caption(
            "🔴 **設備狀態：尚未收到過心跳**"
        )

    else:

        st.caption(
            "🔴 **設備狀態：無法連線到 Firebase**"
        )

    # -----------------------------
    # 清理舊事件
    # -----------------------------
    trim_door_log()

    # -----------------------------
    # 事件紀錄
    # -----------------------------
    with st.expander("📜 最近事件紀錄（最新在上）"):

        show_n = st.selectbox(
            "顯示筆數",
            [15, 50, 100, 200],
            index=0,
            key="log_show_n"
        )

        st.caption(
            f"資料庫最多保留最近 {MAX_LOG} 筆，"
            f"更舊的會自動刪除"
        )

        log = fetch_door_log(show_n)

        if isinstance(log, dict) and log:

            rows = []

            for k in sorted(
                log.keys(),
                reverse=True
            ):

                item = log[k]

                if (
                    isinstance(item, dict)
                    and isinstance(item.get("t"), (int, float))
                ):

                    rows.append({
                        "時間": fmt_ts(item["t"]),
                        "事件": EVENT_NAMES.get(
                            item.get("e"),
                            item.get("e", "")
                        )
                    })

            if rows:

                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    use_container_width=True
                )

            else:

                st.caption("尚無紀錄")

        else:

            st.caption("尚無紀錄")


# ==========================================
# 環境感測器即時資料
# ==========================================
@st.fragment(run_every=env_refresh_every)
def env_live_panel():

    data = fetch_env_data()

    col1, col2 = st.columns(2)

    is_online = False

    last_update_str = "未知"

    if data and isinstance(data, dict):

        ts = data.get("timestamp")

        # ==================================
        # Firebase timestamp
        # 統一轉成台灣時間
        # ==================================
        if ts is not None:

            dt = timestamp_to_taiwan(ts)

            if dt is not None:

                last_update_str = dt.strftime(
                    "%Y/%m/%d %H:%M:%S"
                )

                # 使用 timestamp 判斷是否在線
                ts_sec = dt.timestamp()

                if (
                    time.time() - ts_sec
                ) < 60:

                    is_online = True

        # ==================================
        # 顯示環境數