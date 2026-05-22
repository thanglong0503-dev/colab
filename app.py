import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
from vnstock3 import Vnstock # Thư viện lấy giá real-time

# Cấu hình UI
st.set_page_config(page_title="Fincept AI Desk", page_icon="📈", layout="centered")

st.markdown("""
<style>
    :root { --primary-orange: #F3BA2F; }
    .stApp { background-color: #FFFFFF; }
    .main-header { padding: 15px; border-bottom: 2px solid var(--primary-orange); text-align: center; }
    h1 { color: #1E2329 !important; font-size: 24px !important; }
    div[data-testid="stChatMessage"] { background-color: #F8F9FA; border-radius: 8px; }
    div.stButton > button { background-color: var(--primary-orange) !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'><h1>📈 FINCEPT TERMINAL : REAL-TIME AI</h1></div>", unsafe_allow_html=True)

# 1. Load Dữ liệu tĩnh từ RS_DATA
@st.cache_data(ttl=3600)
def load_rs_data():
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    return pd.DataFrame(worksheet.get_all_records())

# 2. Lấy giá Real-time từ Vnstock
def get_live_price(ticker):
    try:
        stock = Vnstock().stock(symbol=ticker, source='VCI')
        df_price = stock.quote.intraday(symbol=ticker)
        return df_price['close'].iloc[-1] # Lấy giá mới nhất
    except:
        return None

# Khởi tạo
df_static = load_rs_data()

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Dữ liệu đã sẵn sàng. Ngài cần phân tích mã nào hôm nay?"}]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Nhập mã chứng khoán (VD: HPG...):"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Đang kết nối Real-time & Phân tích..."):
            # Lấy giá thực tế
            live_price = get_live_price(prompt.upper())
            
            # Cập nhật thông tin cho AI
            info_text = f"Mã: {prompt.upper()}, Giá hiện tại (Real-time): {live_price}" if live_price else "Dữ liệu real-time đang cập nhật."
            
            client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
            
            # Chỉ gửi tóm tắt, không gửi toàn bộ data thô
            summary_data = df_static[df_static['Mã CK'] == prompt.upper()].to_string()
            
            full_prompt = f"""
            Bạn là chuyên gia phân tích tài chính.
            DỮ LIỆU TĨNH: {summary_data}
            DỮ LIỆU REAL-TIME: {info_text}
            
            Yêu cầu: Chỉ trả lời phân tích sắc bén. TUYỆT ĐỐI KHÔNG SHOW DỮ LIỆU THÔ. 
            Kết hợp giá real-time với các chỉ số kỹ thuật để đưa ra khuyến nghị.
            """
            
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=full_prompt
            )
            
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
