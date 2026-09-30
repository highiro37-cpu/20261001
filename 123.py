import streamlit as st
import pandas as pd
import numpy as np

# 1. 網頁標題與圖示
st.set_page_config(page_title="我的第一個 Streamlit 網頁", page_icon="🚀", layout="centered")

st.title("🚀 歡迎來到我的測試網頁！")
st.write("這是一個用 Python + Streamlit 秒速架設的動態儀表板範例。")

st.divider()

# 2. 即時數據展示卡片
st.subheader("📌 數據卡片範例")
col1, col2 = st.columns(2)
with col1:
    st.metric(label="🌡️ 當前溫度", value="26.5 °C", delta="0.5 °C")
with col2:
    st.metric(label="💧 當前濕度", value="65 %", delta="-2 %")

st.divider()

# 3. 圖表範例
st.subheader("📊 模擬數據折線圖")
chart_data = pd.DataFrame(
    np.random.randn(20, 2),
    columns=['溫度', '濕度']
)
st.line_chart(chart_data)

# 4. 互動按鈕
if st.button("🎉 點我觸發效果"):
    st.balloons()
    st.success("成功執行 Python 邏輯！")
