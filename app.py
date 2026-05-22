import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials # Dùng thư viện chuẩn của Google
from google import genai
from google.genai import types

st.set_page_config(page_title="Fincept Terminal", page_icon="📊", layout="wide")

# ==========================================
# 1. GỌI API KEY TỪ "KÉT SẮT" STREAMLIT
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 2. GỌI DỮ LIỆU TỪ GOOGLE SHEETS BẰNG "KÉT SẮT"
# ==========================================
@st.cache_data(ttl=3600)
def load_data():
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Kéo toàn bộ nội dung file credentials.json từ Két sắt ra
    creds_dict = st.secrets["gcp_service_account"]
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    return pd.DataFrame(worksheet.get_all_records())

df = load_data()

# ==========================================
# GIAO DIỆN WEB VÀ BOT AI (Giữ nguyên như cũ)
# ==========================================
st.markdown("<h1 style='text-align: center; color: #58a6ff;'>📊 FINCEPT TERMINAL : AI DESK</h1>", unsafe_allow_html=True)
st.markdown("---")

col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("🛠️ Bộ Lọc Định Lượng")
    min_rs = st.slider("Momentum (RS 1M) Tối thiểu", 0, 99, 80)
    tech_filter = st.selectbox("Trạng thái Kỹ thuật", ["Tất cả", "KHẢ QUAN", "TRUNG TÍNH", "TIÊU CỰC"])
    max_pe = st.number_input("P/E Tối đa (Định giá)", value=20)
    
    filtered_df = df[(df['RS_1M'] >= min_rs) & (df['P/E'] <= max_pe) & (df['P/E'] > 0)]
    if tech_filter != "Tất cả":
        filtered_df = filtered_df[filtered_df['Trạng Thái'] == tech_filter]
        
    st.success(f"🔍 Đã lọc ra {len(filtered_df)} mã đạt chuẩn.")

with col2:
    st.subheader("📋 Bảng Radar Thị Trường")
    st.dataframe(filtered_df[['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']], use_container_width=True)

st.markdown("---")
st.subheader("🤖 Giám đốc AI Tư vấn Chiến lược")

user_question = st.text_input("Ngài muốn hỏi gì về danh mục trên?")

if st.button("Hỏi AI"):
    if user_question:
        with st.spinner("AI đang tính toán..."):
            try:
                client = genai.Client(api_key=API_KEY)
                data_context = filtered_df.to_dict('records')
                sys_prompt = f"Bạn là Giám đốc Quỹ. Dữ liệu thời gian thực: {data_context}. Trả lời câu hỏi người dùng dựa trên SỐ LIỆU NÀY."
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=user_question,
                    config=types.GenerateContentConfig(system_instruction=sys_prompt, temperature=0.3)
                )
                st.info(response.text)
            except Exception as e:
                st.error(f"Lỗi AI: {e}")
