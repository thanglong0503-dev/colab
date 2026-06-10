import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# ==========================================
# CẤU HÌNH GIAO DIỆN (AI CYBER & iOS STYLE)
# ==========================================
st.set_page_config(page_title="LINANCE TERMINAL", page_icon="CORE", layout="centered")

# --- UI/UX CUSTOM CSS ---
st.markdown("""
<style>
    /* Sử dụng biến hệ thống của Streamlit để thích ứng Light/Dark Mode tự động */
    :root {
        --ios-radius: 18px;
        --ai-accent: #0A84FF; /* Xanh điện tử chuẩn iOS/AI */
        --ai-glow: rgba(10, 132, 255, 0.3);
        --glass-bg: rgba(128, 128, 128, 0.08); /* Nền kính trong suốt */
        --glass-border: rgba(128, 128, 128, 0.2);
    }
    
    /* Header Chuyên Nghiệp - Tối Giản */
    .main-header { 
        padding: 30px 20px; 
        margin-bottom: 20px; 
        text-align: center;
        border-bottom: 1px solid var(--glass-border);
        background: transparent;
    }
    .main-header h1 { 
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-weight: 800 !important; 
        letter-spacing: 2px;
        margin-bottom: 8px;
        font-size: 32px !important;
    }
    .main-header p {
        font-family: "Courier New", Courier, monospace; 
        font-weight: 600;
        letter-spacing: 3px;
        text-transform: uppercase;
        font-size: 12px;
        color: var(--ai-accent);
    }
    
    /* Chat Bubbles (Hiệu ứng kính mờ iOS) */
    div[data-testid="stChatMessage"] { 
        background-color: var(--glass-bg); 
        border-radius: var(--ios-radius); 
        border: 1px solid var(--glass-border);
        padding: 15px;
        backdrop-filter: blur(12px); 
        -webkit-backdrop-filter: blur(12px);
        margin-bottom: 15px;
    }
    
    /* Chat Input (Hiệu ứng phát sáng Cyber) */
    .stChatInput { 
        border-radius: var(--ios-radius) !important; 
        border: 1.5px solid var(--ai-accent) !important; 
        box-shadow: 0 0 15px var(--ai-glow) !important;
        transition: all 0.3s ease;
    }
    
    /* Buttons */
    div.stButton > button {
        background-color: var(--ai-accent) !important;
        color: #FFFFFF !important; 
        font-weight: 700 !important;
        letter-spacing: 1px;
        border-radius: 12px !important; 
        border: none !important;
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        box-shadow: 0 0 20px var(--ai-glow) !important;
        transform: translateY(-2px);
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("<div class='main-header'><h1>LINANCE TERMINAL</h1><p>SYS.CORE // AI QUANTITATIVE ANALYSIS</p></div>", unsafe_allow_html=True)

# ==========================================
# SIDEBAR CONTROL PANEL (BẢNG ĐIỀU KHIỂN BÊN HÔNG)
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ HỆ THỐNG")
    st.caption("Trạng thái: KẾT NỐI API BÌNH THƯỜNG")
    # Nút bấm quyền lực giúp Ngài ép hệ thống cập nhật Sheet mới ngay lập tức
    if st.button("🔄 Loading DATA"):
        st.cache_data.clear() # Xóa sạch trí nhớ cũ
        st.rerun() # Tải lại ứng dụng

API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 1. HÀM TẢI DỮ LIỆU TỰ ĐỘNG QUÉT TOÀN BỘ CÁC SHEET
# ==========================================
@st.cache_data(ttl=600) # Đã giảm xuống 10 phút để cập nhật nhanh hơn
def load_all_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Mở file Google Sheets chứa toàn bộ dữ liệu
        spreadsheet = client.open("RS_DATA") 
        
        all_data = {}
        # Vòng lặp quét tất cả các tab
        for ws in spreadsheet.worksheets():
            records = ws.get_all_records()
            # CẢNH BÁO CHO NGÀI: Nếu Sheet trống (chưa có dòng tiêu đề), hàm này sẽ bỏ qua.
            if records:
                all_data[ws.title] = pd.DataFrame(records)
        return all_data
    except Exception as e:
        st.error(f"SYSTEM ERROR (DATA_LOAD): {e}")
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
        
        formatted_results = []
        for r in results:
            formatted_results.append(f"- Tiêu đề: {r['title']}\n  Nội dung: {r['body']}\n  Nguồn: {r['href']}")
        return "\n".join(formatted_results)
    except Exception as e:
        return f"SYSTEM ERROR (NETWORK): {e}"

# ==========================================
# 3. TRUNG TÂM XỬ LÝ CHATBOT AI AGENT
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "LINANCE CORE ONLINE. Hệ thống phân tích đã sẵn sàng tiếp nhận truy vấn."}
    ]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Nhập mã chứng khoán hoặc truy vấn phân tích..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("PROCESSING QUERY..."):
            try:
                # 3.1. Gom và định dạng toàn bộ các Sheet thành Text
                data_context = ""
                for sheet_name, df_sheet in dict_dfs.items():
                    if sheet_name == "RS_DATA" and not df_sheet.empty:
                        essential_cols = [c for c in ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'ROE (%)', 'RSI_14'] if c in df_sheet.columns]
                        if essential_cols:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet[essential_cols].head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"
                    else:
                        data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"

                # Hiển thị cho sếp biết AI đang đọc những sheet nào
                st.caption(f"🧠 Dữ liệu nội bộ đã nạp: {', '.join(dict_dfs.keys())}")

                # 3.2. Khởi tạo Client
                client = genai.Client(api_key=API_KEY)
                
                # 3.3. THIẾT LẬP KỶ LUẬT THÉP
                sys_prompt = """
                Bạn là AI Analyst cấp cao tại LINANCE.
                NGUYÊN TẮC HOẠT ĐỘNG:
                1. ƯU TIÊN SỐ 1: Bám sát DỮ LIỆU NỘI BỘ (RS_DATA, INDUSTRY_DATA, REPORTS_DB...) được cung cấp bên dưới để phân tích định lượng.
                2. TÌM KIẾM MỞ RỘNG: NẾU dữ liệu nội bộ không đủ trả lời, HÃY TỰ ĐỘNG GỌI CÔNG CỤ `search_internet`.
                3. NGUỒN: Khi sử dụng thông tin từ Internet, BẮT BUỘC trích dẫn link nguồn.
                4. CẤM: Không in lại bảng dữ liệu CSV thô.
                5. MIỄN TRỪ TRÁCH NHIỆM: Ở CUỐI MỌI CÂU TRẢ LỜI, chèn chính xác dòng chữ in nghiêng sau: "*Miễn trừ trách nhiệm: Thông tin chỉ mang tính chất tham khảo dựa trên dữ liệu hiện có và không phải là lời khuyên đầu tư.*"
                """
                
                full_prompt = f"{sys_prompt}\n\n📊 KHO DỮ LIỆU NỘI BỘ:\n{data_context}\n\nTRUY VẤN: {prompt}"
                
                # 3.4. Gọi mô hình
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        tools=[search_internet]
                    )
                )
                
                # 3.5. Xử lý Function Calling
                if response.function_calls:
                    for tool_call in response.function_calls:
                        if tool_call.name == "search_internet":
                            query = tool_call.args.get("query", prompt)
                            st.caption(f"SYSTEM OVERRIDE: Executing web search for '{query}'...")
                            
                            internet_result = search_internet(query)
                            
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
                            
                            response = client.models.generate_content(
                                model='gemini-3.1-flash-lite',
                                contents=messages_for_ai,
                                config=types.GenerateContentConfig(temperature=0.2)
                            )
                
                # 3.6. Hiển thị kết quả
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                
            except Exception as e:
                st.error(f"SYSTEM FAULT: {e}")
