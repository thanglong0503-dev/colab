import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# Cấu hình giao diện
st.set_page_config(page_title="Fincept AI Desk", page_icon="📈", layout="centered")

# --- UI/UX CUSTOM CSS (BINANCE STYLE) ---
st.markdown("""
<style>
    :root {
        --primary-orange: #F3BA2F;
        --bg-white: #FFFFFF;
        --text-dark: #1E2329;
        --border-color: #EAECEF;
    }
    .stApp { background-color: var(--bg-white); color: var(--text-dark); }
    
    /* Header chuyên nghiệp */
    .main-header { 
        padding: 20px; border-bottom: 2px solid var(--primary-orange); 
        margin-bottom: 30px; text-align: center;
    }
    h1 { color: var(--text-dark) !important; font-weight: 800 !important; }
    
    /* Chat bubbles */
    div[data-testid="stChatMessage"] { background-color: #F8F9FA; border-radius: 12px; }
    
    /* Chat Input */
    .stChatInput { border: 2px solid var(--primary-orange) !important; }
    
    /* Buttons */
    div.stButton > button {
        background-color: var(--primary-orange) !important;
        color: white !important; font-weight: 700 !important;
        border-radius: 6px !important; border: none !important;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("<div class='main-header'><h1>📈 FINCEPT TERMINAL</h1><p>Hệ thống hỗ trợ phân tích định lượng AI</p></div>", unsafe_allow_html=True)

# Lấy Chìa khóa từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_data(ttl=3600)
def load_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    return pd.DataFrame(worksheet.get_all_records())

df = load_data()

# Khởi tạo tin nhắn
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Fincept AI đã sẵn sàng.Bạn cần phân tích cổ phiếu nào ?"}
    ]

# Render lịch sử
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý chat
if prompt := st.chat_input("Nhập mã chứng khoán (Ví dụ: HPG, SSI...)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Đang quét dữ liệu..."):
            try:
                client = genai.Client(api_key=API_KEY)
                essential_cols = ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']
                data_csv = df[essential_cols].to_csv(index=False) 
                
                sys_prompt = "Bạn là AI Analyst tại LINANCE. Trả lời bằng dữ liệu CSV,dữ liệu bên ngoài,Báo cáo phân tích các công ty,tra cứu gooogle về thị trường chứng khoán và dữ liệu real time, giọng điệu chuyên nghiệp."
                full_prompt = f"{sys_prompt}\n\n📊 DỮ LIỆU:\n{data_csv}\n\nLỆNH: {prompt}"
                
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=full_prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Lỗi: {e}")
