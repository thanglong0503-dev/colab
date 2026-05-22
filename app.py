import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
from vnstock3 import Vnstock 

# Cấu hình giao diện
st.set_page_config(page_title="Fincept AI Desk", page_icon="📈", layout="centered")

# --- UI/UX BINANCE STYLE ---
st.markdown("""
<style>
    :root { --primary-orange: #F3BA2F; }
    .stApp { background-color: #FFFFFF; }
    .main-header { padding: 20px; border-bottom: 2px solid var(--primary-orange); text-align: center; margin-bottom: 30px; }
    h1 { color: #1E2329 !important; font-weight: 800 !important; }
    div[data-testid="stChatMessage"] { background-color: #F8F9FA; border-radius: 12px; border: 1px solid #EAECEF; }
    .stChatInput { border: 2px solid var(--primary-orange) !important; border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'><h1>📈 FINCEPT TERMINAL</h1><p>Phân tích Định lượng AI Real-time</p></div>", unsafe_allow_html=True)

# Lấy Chìa khóa từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_data(ttl=3600)
def load_rs_data():
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]))
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    return pd.DataFrame(worksheet.get_all_records())

# Hàm lấy giá Real-time với vnstock3
def get_live_price(ticker):
    try:
        # Khởi tạo Vnstock chuẩn
        stock = Vnstock().stock(symbol=ticker, source='VCI')
        df_price = stock.quote.intraday(symbol=ticker)
        if df_price is not None and not df_price.empty:
            return float(df_price['close'].iloc[-1])
        return None
    except Exception as e:
        return None

df_static = load_rs_data()

# Khởi tạo tin nhắn
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Fincept AI đã sẵn sàng. Ngài cần phân tích định lượng mã cổ phiếu nào?"}]

# Render lịch sử
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý chat
if prompt := st.chat_input("Nhập mã chứng khoán (VD: HPG...):"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Đang kết nối thị trường & Phân tích..."):
            try:
                ticker = prompt.upper().strip()
                live_price = get_live_price(ticker)
                
                # Trích xuất dữ liệu tĩnh liên quan
                static_info = df_static[df_static['Mã CK'] == ticker]
                static_data_str = static_info.to_string(index=False) if not static_info.empty else "Không tìm thấy trong DB nội bộ."
                
                client = genai.Client(api_key=API_KEY)
                
                sys_prompt = f"""
                Bạn là chuyên gia phân tích định lượng tại Mirae Asset.
                DỮ LIỆU TĨNH: {static_data_str}
                GIÁ REAL-TIME: {live_price if live_price else 'Không lấy được giá live'}
                
                Yêu cầu:
                - Phân tích dựa trên sự kết hợp giữa dữ liệu RS_DATA và giá Real-time.
                - KHÔNG ĐƯỢC show bảng dữ liệu thô.
                - Trả lời phong cách chuyên gia, sắc bén, tập trung vào xu hướng.
                """
                
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=full_prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Lỗi: {e}")
