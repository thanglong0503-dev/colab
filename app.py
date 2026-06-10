import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# ==========================================
# CẤU HÌNH GIAO DIỆN CHUYÊN NGHIỆP
# ==========================================
st.set_page_config(page_title="LINANCE AI Desk", page_icon="📈", layout="centered")

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
st.markdown("<div class='main-header'><h1>📈 LINANCE TERMINAL</h1><p>Hệ thống AI Phân tích Định lượng & Cập nhật Tin tức Tự động</p></div>", unsafe_allow_html=True)

# Lấy Chìa khóa từ Két sắt
API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 1. HÀM TẢI DỮ LIỆU TỰ ĐỘNG QUÉT TOÀN BỘ CÁC SHEET
# ==========================================
@st.cache_data(ttl=3600)
def load_all_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Mở file Google Sheets chứa toàn bộ dữ liệu (RS_DATA, INDUSTRY_DATA...)
        spreadsheet = client.open("RS_DATA") 
        
        all_data = {}
        # Vòng lặp quét tất cả các tab (worksheet) đang có trong file
        for ws in spreadsheet.worksheets():
            records = ws.get_all_records()
            if records:
                all_data[ws.title] = pd.DataFrame(records)
        return all_data
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu Google Sheets: {e}")
        return {}

# Tải bộ dữ liệu đa tầng
dict_dfs = load_all_sheets()

# ==========================================
# 2. CÔNG CỤ TÌM KIẾM INTERNET ĐỘC LẬP (DUCKDUCKGO)
# ==========================================
def search_internet(query: str) -> str:
    """Công cụ dùng để tra cứu tin tức, sự kiện, báo cáo trên mạng khi dữ liệu nội bộ không có."""
    from duckduckgo_search import DDGS
    try:
        results = DDGS().text(query, max_results=3, region='vn-tz')
        if not results:
            return "Không tìm thấy thông tin trên mạng."
        
        # Đóng gói dữ liệu mạng kèm NGUỒN (Link) cho AI đọc
        formatted_results = []
        for r in results:
            formatted_results.append(f"- Tiêu đề: {r['title']}\n  Nội dung: {r['body']}\n  Nguồn: {r['href']}")
        return "\n".join(formatted_results)
    except Exception as e:
        return f"Lỗi truy cập mạng: {e}"

# ==========================================
# 3. TRUNG TÂM XỬ LÝ CHATBOT AI AGENT
# ==========================================
# Khởi tạo tin nhắn
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "LINANCE AI đã sẵn sàng. Bạn cần phân tích cổ phiếu hay ngành nào?"}
    ]

# Render lịch sử
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý chat
if prompt := st.chat_input("Nhập mã chứng khoán hoặc câu hỏi (VD: HPG, Vĩ mô hôm nay, Ngành thép...)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("AI đang quét kho dữ liệu nội bộ và tra cứu thông tin..."):
            try:
                # 3.1. Gom và định dạng toàn bộ các Sheet thành Text để AI đọc
                data_context = ""
                for sheet_name, df_sheet in dict_dfs.items():
                    # Lấy dữ liệu và giới hạn số dòng để tránh lỗi quá tải token (AI có thể đọc tốt vài trăm dòng)
                    # Nếu là RS_DATA, ta có thể ưu tiên giữ các cột cốt lõi
                    if sheet_name == "RS_DATA" and not df_sheet.empty:
                        essential_cols = [c for c in ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14'] if c in df_sheet.columns]
                        if essential_cols:
                            data_context += f"--- BẢNG {sheet_name} ---\n{df_sheet[essential_cols].head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- BẢNG {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"
                    else:
                        data_context += f"--- BẢNG {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"

                # 3.2. Khởi tạo Client Gemini
                client = genai.Client(api_key=API_KEY)
                
                # 3.3. THIẾT LẬP KỶ LUẬT THÉP VÀ QUY TRÌNH HÀNH ĐỘNG CHO AI
                sys_prompt = """
                Bạn là AI Analyst cấp cao tại LINANCE.
                NGUYÊN TẮC HOẠT ĐỘNG TỐI THƯỢNG:
                1. ƯU TIÊN SỐ 1: Bám sát DỮ LIỆU NỘI BỘ (RS_DATA, INDUSTRY_DATA, và các bảng khác) được cung cấp bên dưới để phân tích định lượng. Dữ liệu giá trong RS_DATA là độ chuẩn xác cao nhất cần được ưu tiên.
                2. SỰ LINH HOẠT: NẾU dữ liệu nội bộ không đủ trả lời (ví dụ khách hỏi tin tức, báo cáo phân tích công ty chứng khoán, vĩ mô, hay diễn biến thị trường mới nhất), HÃY TỰ ĐỘNG GỌI CÔNG CỤ `search_internet` để lấy thông tin.
                3. GHI RÕ NGUỒN: Khi sử dụng thông tin từ mạng Internet, BẮT BUỘC phải trích dẫn link nguồn rõ ràng và đầy đủ.
                4. CẤM: Không in lại bảng dữ liệu CSV thô. Hãy diễn giải số liệu một cách mạch lạc, lồng ghép vào câu phân tích chuyên nghiệp.
                5. MIỄN TRỪ TRÁCH NHIỆM: Ở CUỐI MỌI CÂU TRẢ LỜI, bắt buộc phải chèn chính xác dòng chữ in nghiêng sau đây: "*Miễn trừ trách nhiệm: Thông tin chỉ mang tính chất tham khảo dựa trên dữ liệu hiện có và không phải là lời khuyên đầu tư.*"
                """
                
                full_prompt = f"{sys_prompt}\n\n📊 KHO DỮ LIỆU NỘI BỘ (TOÀN BỘ SHEETS):\n{data_context}\n\nLỆNH CỦA KHÁCH HÀNG: {prompt}"
                
                # 3.4. Gọi mô hình và trang bị Tool (Vũ khí) tìm kiếm
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        tools=[search_internet] # Nạp vũ khí tìm kiếm độc lập cho AI
                    )
                )
                
                # 3.5. Xử lý Vòng lặp Function Calling (Khi AI quyết định phải lên mạng tìm kiếm)
                if response.function_calls:
                    for tool_call in response.function_calls:
                        if tool_call.name == "search_internet":
                            # Lấy từ khóa mà AI muốn tìm
                            query = tool_call.args.get("query", prompt)
                            st.caption(f"🌍 Hệ thống đang tự động tìm kiếm trên mạng: '{query}'...")
                            
                            # Thực thi lệnh cào dữ liệu Internet
                            internet_result = search_internet(query)
                            
                            # Đóng gói kết quả mạng trả ngược lại cho AI đọc
                            messages_for_ai = [
                                types.Content(role="user", parts=[types.Part.from_text(full_prompt)]),
                                response.candidates[0].content,
                                types.Content(role="user", parts=[
                                    types.Part.from_function_response(
                                        name=tool_call.name, 
                                        response={"result": internet_result}
                                    )
                                ])
                            ]
                            
                            # AI tổng hợp lại câu trả lời cuối cùng
                            response = client.models.generate_content(
                                model='gemini-3.1-flash-lite',
                                contents=messages_for_ai,
                                config=types.GenerateContentConfig(temperature=0.2)
                            )
                
                # 3.6. Hiển thị kết quả ra màn hình
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                
            except Exception as e:
                st.error(f"Lỗi truy xuất hệ thống: {e}")
