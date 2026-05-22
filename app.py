import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# ==========================================
# CẤU HÌNH TRANG WEB TRỰC QUAN
# ==========================================
st.set_page_config(page_title="Fincept Terminal", page_icon="📊", layout="wide")

# Triệu hồi Chìa khóa Gemini API từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# HÀM NẠP DỮ LIỆU TỪ KHO RS_DATA CỤC BỘ
# ==========================================
@st.cache_data(ttl=3600) # Lưu cache 1 tiếng để tối ưu tốc độ tải trang
def load_data():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Rút chứng chỉ Google Cloud đã được xử lý chuẩn hóa từ Két sắt
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    # Khởi tạo quyền truy cập và mở bảng tính
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    worksheet = client.open("RS_DATA").worksheet("RS_DATA")
    
    # Chuyển đổi dữ liệu bảng tính thành DataFrame
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

# Thực thi nạp kho đạn dữ liệu
df = load_data()

# ==========================================
# THIẾT KẾ GIAO DIỆN TERMINAL CHUYÊN NGHIỆP
# ==========================================
st.markdown("<h1 style='text-align: center; color: #58a6ff;'>📊 FINCEPT TERMINAL : AI DESK</h1>", unsafe_allow_html=True)
st.markdown("---")

# Chia bố cục trang thành 2 cột: Cột Bộ lọc và Cột Bảng số liệu
col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("🛠️ Bộ Lọc Định Lượng")
    min_rs = st.slider("Momentum (RS 1M) Tối thiểu", 0, 99, 80)
    tech_filter = st.selectbox("Trạng thái Kỹ thuật", ["Tất cả", "KHẢ QUAN", "TRUNG TÍNH", "TIÊU CỰC"])
    max_pe = st.number_input("P/E Tối đa (Định giá)", value=20)
    
    # Xử lý lọc dữ liệu bằng Pandas dựa trên thanh trượt
    filtered_df = df[(df['RS_1M'] >= min_rs) & (df['P/E'] <= max_pe) & (df['P/E'] > 0)]
    if tech_filter != "Tất cả":
        filtered_df = filtered_df[filtered_df['Trạng Thái'] == tech_filter]
        
    st.success(f"🔍 Đã lọc ra {len(filtered_df)} mã đạt chuẩn.")

with col2:
    st.subheader("📋 Bảng Radar Thị Trường")
    # Hiển thị các trường thông tin tinh hoa nhất lên giao diện bảng
    st.dataframe(
        filtered_df[['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']], 
        use_container_width=True
    )

# ==========================================
# TRUNG TÂM PHÂN TÍCH CHIẾN LƯỢC AI AGENT
# ==========================================
st.markdown("---")
st.subheader("🤖 Giám đốc AI Tư vấn Chiến lược")

# Khung nhập câu hỏi chiến lược của Ngài
user_question = st.text_input("Ngài muốn hỏi gì về danh mục trên? (VD: Đánh giá giúp mã HPG hoặc Tìm mã có RSI đẹp)")

if st.button("Hỏi AI"):
    if user_question:
        with st.spinner("AI đang truy xuất kho dữ liệu RS_DATA nội bộ..."):
            try:
                # Khởi tạo Client kết nối với hệ thống trí tuệ nhân tạo của Google
                client = genai.Client(api_key=API_KEY)
                
                # Trích xuất toàn bộ dữ liệu thô (không bị giới hạn bộ lọc) để AI có cái nhìn toàn cảnh
                essential_cols = ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14']
                data_csv = df[essential_cols].to_csv(index=False) 
                
                # Chỉ thị hệ thống thiết lập kỷ luật thép buộc AI dựa hoàn toàn vào dữ liệu nội bộ
                sys_prompt = """
                Bạn là Giám đốc Phân tích Định lượng của Quỹ. 
                SỰ THẬT TỐI THƯỢNG: Bạn CHỈ ĐƯỢC PHÉP trả lời dựa trên bảng dữ liệu CSV nội bộ được cung cấp bên dưới. 
                Tuyệt đối không sử dụng dữ liệu, giá cả hay tin tức từ Internet.
                Khi phân tích một mã cổ phiếu, BẮT BUỘC phải trích dẫn các con số thực tế từ bảng (như RS_1M, Tech_Score, P/E, RSI...) để làm bằng chứng định lượng.
                """
                
                # Ghép toàn bộ ngữ cảnh dữ liệu và câu hỏi thành một khối lệnh thống nhất
                full_prompt = f"{sys_prompt}\n\n📊 BẢNG DỮ LIỆU RS_DATA:\n{data_csv}\n\n🗣️ LỆNH TỪ KHÁCH HÀNG: {user_question}"
                
                # Triệu hồi mô hình xử lý thế hệ mới với độ trễ cực thấp
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1 # Đưa tính sáng tạo về mức tối thiểu để đảm bảo tính chính xác của số liệu
                    )
                )
                
                # Hiển thị câu trả lời sắc bén của AI lên màn hình Web
                st.info(response.text)
                
            except Exception as e:
                st.error(f"Lỗi AI: {e}")
