import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
import vnstock # Đảm bảo đã cài vnstock bản chuẩn

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
    div[data-testid="stChatMessage"] { background-color: #F8F9FA; border-radius: 12px; border: 1px solid var(--border-color); }
    
    /* Chat Input */
    .stChatInput { border: 2px solid var(--primary-orange) !important; border-radius: 8px !important; }
    
    /* Buttons */
    div.stButton > button {
        background-color: var(--primary-orange) !important;
        color: white !important; font-weight: 700 !important;
        border-radius: 6px !important; border: none !important;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("<div class='main-header'><h1>📈 FINCEPT TERMINAL</h1><p>Hệ thống AI Phân tích Định lượng & Cập nhật Tin tức</p></div>", unsafe_allow_html=True)

# Lấy Chìa khóa từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

# 1. HÀM TẢI DỮ LIỆU TĨNH (RS_DATA)
@st.cache_data(ttl=3600)
def load_data():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        worksheet = client.open("RS_DATA").worksheet("RS_DATA")
        return pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu Google Sheets: {e}")
        return pd.DataFrame()

# 2. HÀM LẤY GIÁ REAL-TIME
def get_live_price(ticker):
    try:
        # Sử dụng hàm ổn định của vnstock
        df = vnstock.stock_quick_view(symbol=ticker)
        if df is not None and not df.empty:
            return float(df['price'].iloc[0])
        return None
    except:
        return None

df = load_data()

# Khởi tạo tin nhắn
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Fincept AI đã sẵn sàng. Bạn cần phân tích cổ phiếu nào?"}
    ]

# Render lịch sử
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý chat
if prompt := st.chat_input("Nhập yêu cầu (VD: Phân tích cơ bản HPG, tin tức mới nhất về SSI...)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("AI đang quét dữ liệu thị trường và Internet..."):
            try:
                # Trích xuất mã CK từ câu hỏi (Giả định đơn giản, có thể nâng cấp NLP sau)
                # Đoạn này tìm kiếm nhanh mã CK trong prompt để lấy giá realtime
                import re
                found_tickers = re.findall(r'\b[A-Z]{3}\b', prompt.upper())
                ticker_to_search = found_tickers[0] if found_tickers else None
                
                live_price_info = ""
                static_data_str = "Không tìm thấy dữ liệu nội bộ."
                
                if ticker_to_search:
                    live_price = get_live_price(ticker_to_search)
                    live_price_info = f"\nGiá Real-time của {ticker_to_search}: {live_price if live_price else 'Đang cập nhật'}"
                    
                    if not df.empty:
                        essential_cols = ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']
                        available_cols = [c for c in essential_cols if c in df.columns]
                        static_info = df[df['Mã CK'] == ticker_to_search][available_cols]
                        if not static_info.empty:
                            static_data_str = static_info.to_string(index=False)
                
                client = genai.Client(api_key=API_KEY)
                
                # BƯỚC QUAN TRỌNG: Thiết lập System Prompt cho AI Agent
                sys_prompt = """
                Bạn là AI Analyst cấp cao tại LINANCE.
                NHIỆM VỤ CỦA BẠN:
                1. Dùng Dữ liệu Nội bộ (RS_DATA) và Giá Real-time được cung cấp bên dưới để phân tích định lượng.
                2. Dùng công cụ Google Search (đã được cấp quyền) để tra cứu Báo cáo phân tích mới nhất, tin tức vĩ mô, hoặc tình hình kinh doanh của doanh nghiệp nếu người dùng yêu cầu "phân tích cơ bản", "tin tức", hoặc "báo cáo".
                3. TUYỆT ĐỐI KHÔNG in lại bảng dữ liệu thô. Hãy lồng ghép các con số (RS_1M, P/E...) vào câu văn một cách tự nhiên.
                4. Giọng điệu chuyên nghiệp, khách quan, súc tích như một chuyên gia tài chính.
                """
                
                full_prompt = f"{sys_prompt}\n\n📊 DỮ LIỆU NỘI BỘ (RS_DATA):\n{static_data_str}\n\n⏱️ DỮ LIỆU REAL-TIME:{live_price_info}\n\n🗣️ YÊU CẦU CỦA KHÁCH: {prompt}"
                
                # BƯỚC QUYẾT ĐỊNH: Bật công cụ Google Search cho mô hình
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', # Dùng 3.1 Flash Lite cho tốc độ nhanh
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2, # Tăng nhẹ temperature để AI linh hoạt hơn khi đọc tin tức
                        tools=[{"google_search": {}}] # CẤP QUYỀN TRUY CẬP INTERNET
                    )
                )
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Lỗi hệ thống: {e}")
