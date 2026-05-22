import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# ==========================================
# CẤU HÌNH GIAO DIỆN (UI/UX CHUYÊN NGHIỆP)
# ==========================================
st.set_page_config(page_title="Fincept AI Desk", page_icon="🤖", layout="centered")

# CSS: Tinh chỉnh để giao diện trông giống một Terminal tài chính thực thụ
st.markdown("""
<style>
    .main { background-color: #0d1117; color: #c9d1d9; }
    .stApp { background-color: #0d1117; }
    h1 { color: #58a6ff !important; font-size: 24px !important; margin-bottom: 20px !important; }
    .stChatInput { border-radius: 8px !important; }
    div[data-testid="stChatMessage"] { background-color: #161b22; border: 1px solid #30363d; border-radius: 12px; }
    .stMarkdown { font-family: 'SF Mono', Consolas, monospace; }
</style>
""", unsafe_allow_html=True)

# Lấy Chìa khóa từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_data(ttl=3600)
def load_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

# Thực thi nạp dữ liệu ngầm
df = load_data()

# ==========================================
# GIAO DIỆN CHATBOT TẬP TRUNG
# ==========================================
st.title("🤖 FINCEPT ANALYST : AI DESK")
st.markdown("Hệ thống phân tích dữ liệu định lượng thời gian thực.")

# Khởi tạo bộ nhớ chat
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Dữ liệu đã sẵn sàng. Ngài cần phân tích định lượng mã cổ phiếu nào?"}
    ]

# Hiển thị lịch sử chat
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý nhập liệu
if prompt := st.chat_input("Nhập mã cổ phiếu hoặc yêu cầu phân tích..."):
    # 1. Hiển thị tin nhắn người dùng
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Xử lý logic AI
    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý dữ liệu RS_DATA..."):
            try:
                client = genai.Client(api_key=API_KEY)
                essential_cols = ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']
                data_csv = df[essential_cols].to_csv(index=False) 
                
                sys_prompt = """
                Bạn là chuyên gia phân tích định lượng tại quỹ Mirae Asset.
                Sử dụng DỮ LIỆU BẢNG (CSV) dưới đây để phân tích.
                - Trả lời bằng ngôn ngữ chuyên môn, sắc bén.
                - LUÔN LUÔN trích dẫn con số từ dữ liệu để chứng minh quan điểm.
                - KHÔNG trả lời lan man hoặc thông tin ngoài luồng.
                """
                
                full_prompt = f"{sys_prompt}\n\n📊 DỮ LIỆU:\n{data_csv}\n\nLỆNH: {prompt}"
                
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=full_prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                
            except Exception as e:
                st.error(f"Hệ thống báo lỗi: {e}")
