import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
import vnstock # Chúng ta dùng bản vnstock chuẩn để đảm bảo tính ổn định

# Cấu hình UI
st.set_page_config(page_title="Fincept AI Desk", page_icon="📈", layout="centered")

st.markdown("""
<style>
    :root { --primary-orange: #F3BA2F; }
    .stApp { background-color: #FFFFFF; }
    .main-header { padding: 15px; border-bottom: 2px solid var(--primary-orange); text-align: center; }
    h1 { color: #1E2329 !important; font-size: 24px !important; }
    div[data-testid="stChatMessage"] { background-color: #F8F9FA; border-radius: 8px; }
    .stChatInput { border: 2px solid var(--primary-orange) !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'><h1>📈 FINCEPT TERMINAL</h1></div>", unsafe_allow_html=True)

# 1. Load dữ liệu từ Google Sheets
@st.cache_data(ttl=3600)
def load_rs_data():
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    return pd.DataFrame(worksheet.get_all_records())

# 2. Lấy giá Real-time từ vnstock (Cách gọi ổn định nhất)
def get_live_price(ticker):
    try:
        # Sử dụng hàm stock_quick_view của vnstock cũ - cực kỳ ổn định
        df = vnstock.stock_quick_view(symbol=ticker)
        if df is not None and not df.empty:
            return float(df['price'].iloc[0])
        return None
    except:
        return None

df_static = load_rs_data()

# Khởi tạo chat
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Fincept AI đã sẵn sàng. Ngài cần phân tích mã nào hôm nay?"}]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Nhập mã chứng khoán..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Đang kết nối Real-time..."):
            ticker = prompt.upper().strip()
            live_price = get_live_price(ticker)
            
            # Chỉ lấy dữ liệu mã đó
            static_info = df_static[df_static['Mã CK'] == ticker]
            data_context = static_info.to_string(index=False) if not static_info.empty else "Không có dữ liệu tĩnh."
            
            # Gọi AI
            client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
            
            prompt_content = f"""
            Bạn là chuyên gia phân tích tài chính.
            Dữ liệu định lượng: {data_context}
            Giá Real-time của {ticker} là: {live_price}
            
            Yêu cầu: Phân tích ngắn gọn, chuyên sâu. KHÔNG hiển thị lại bảng dữ liệu thô.
            """
            
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt_content
            )
            
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
