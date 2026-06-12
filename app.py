import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
# ==========================================
# GIAO DIỆN: THẺ BÀI RPG (ĐÃ FIX LỖI PANDAS SERIES)
# ==========================================
def render_rpg_card(ticker: str, df_rs: pd.DataFrame, df_ta: pd.DataFrame = None):
    # 1. TÌM DỮ LIỆU
    stock_rs = df_rs[df_rs['Mã CK'] == ticker]
    if stock_rs.empty:
        st.warning(f"Chiến binh {ticker} chưa xuất hiện trong Database.")
        return
        
    # Chuyển dòng dữ liệu (Series) thành Dictionary để dùng được hàm .get() an toàn
    data = stock_rs.iloc[0].to_dict()
    
    # 2. CHỈ SỐ GAME
    # Sử dụng dict.get(key, default_value)
    atk_score = int(data.get('RS_1M', 50))
    mp_score = int(data.get('MFI_14', 50))
    tech_score = data.get('Tech_Score', 0)
    
    def_score = 50
    if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
        ta_data = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict() # Cũng chuyển sang Dict
        if "TRÊN Mây" in str(ta_data.get('Trạng Thái Mây', '')): def_score += 30
        elif "DƯỚI Mây" in str(ta_data.get('Trạng Thái Mây', '')): def_score -= 20
        
    if float(data.get('ROE (%)', 0)) > 15: def_score += 20
    def_score = min(max(def_score, 0), 100)

    # Hệ Phái & Tier
    if tech_score >= 6: tier, t_col = "S-TIER", "#FFD700"
    elif tech_score >= 3: tier, t_col = "A-TIER", "#00FF00"
    elif tech_score >= 0: tier, t_col = "B-TIER", "#0A84FF"
    else: tier, t_col = "C-TIER", "#FF3A3A"

    industry = str(data.get('Ngành', ''))
    if "Ngân hàng" in industry: rpg_class = "🛡️ TANKER"
    elif "Chứng khoán" in industry: rpg_class = "⚔️ ASSASSIN"
    elif "Công nghệ" in industry: rpg_class = "🧙‍♂️ MAGE"
    elif "Bất động sản" in industry: rpg_class = "🪓 BERSERKER"
    else: rpg_class = "🏹 RANGER"

    # 3. VẼ UI
    st.markdown(f"""
    <div style="background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: 18px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin:0; color:#FFF;">[{ticker}] - {rpg_class}</h3>
        <p style="color:{t_col}; font-weight:bold; font-size:18px;">♦ {tier}</p>
        <hr style="border-color: rgba(255,255,255,0.1); margin: 10px 0;">
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**⚔️ ATK (Sát thương):** {atk_score}")
        st.progress(atk_score / 100)
        st.markdown(f"**🛡️ DEF (Hỗ trợ/Giáp):** {def_score}")
        st.progress(def_score / 100)
    with col2:
        st.markdown(f"**💧 MP (Mana/Dòng tiền):** {mp_score}")
        st.progress(mp_score / 100)
        
        # Format giá an toàn phòng trường hợp giá trị bị lỗi chuỗi
        try:
            current_price = float(data.get('Giá', 0))
            price_display = f"{current_price:,.0f} ₫"
        except (ValueError, TypeError):
            price_display = "N/A"
            
        st.markdown(f"**❤️ HP (Giá hiện tại):** {price_display}")
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

    # === TÍNH NĂNG SOI THẺ BÀI RPG (Đã đưa vào trong Sidebar) ===
    st.markdown("---")
    st.markdown("### 🎮 SOI CHỈ SỐ CHIẾN BINH")
    rpg_ticker = st.text_input("Nhập Mã CK (VD: HPG):", "").upper()
    
    if rpg_ticker:
        # Kiểm tra xem dict_dfs đã được định nghĩa chưa (Hàm load_all_sheets của Ngài)
        if "dict_dfs" in locals() or "dict_dfs" in globals():
            df_rs = dict_dfs.get("RS_DATA", pd.DataFrame())
            df_ta = dict_dfs.get("TA_DATA", pd.DataFrame())
            
            if not df_rs.empty:
                render_rpg_card(rpg_ticker, df_rs, df_ta)
            else:
                st.warning("Dữ liệu RS_DATA đang trống. Vui lòng bấm Loading DATA.")
        else:
            st.error("Hệ thống chưa tải dữ liệu (dict_dfs). Vui lòng kiểm tra lại hàm load_all_sheets().")

# Khai báo API KEY ở bên ngoài (Sau khi đã vẽ xong Sidebar)
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
# 2.5. KỸ NĂNG: RADAR REAL-TIME (YAHOO FINANCE)
# ==========================================
def get_live_stock_data(ticker: str) -> str:
    """Công cụ BẮT BUỘC dùng để tra cứu GIÁ REAL-TIME ngay trong phiên của cổ phiếu Việt Nam."""
    import yfinance as yf
    try:
        ticker = ticker.strip().upper()
        yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
        stock = yf.Ticker(yf_ticker)
        
        # Lấy giá realtime qua hàm fast_info (Nhanh và ít bị lỗi hơn .info)
        current_price = stock.fast_info['lastPrice']
        
        # Nhân tỷ lệ nếu Yahoo trả về giá rút gọn
        if current_price < 1000:
            current_price *= 1000
            
        return f"[SYSTEM REAL-TIME UPDATE] Giá của {ticker} NGAY LÚC NÀY là: {current_price:,.0f} VNĐ."
    except Exception as e:
        return f"Hệ thống không thể lấy giá realtime cho {ticker} lúc này. Lỗi: {e}"
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
                    
                    # === ĐÂY LÀ ĐOẠN MỚI THÊM VÀO CHO ICHIMOKU ===
                    elif sheet_name == "TA_DATA" and not df_sheet.empty:
                        ta_cols = [c for c in ['Mã CK', 'Giá Hiện Tại', 'Tenkan_sen (9)', 'Kijun_sen (26)', 'Senkou_A (Mây)', 'Senkou_B (Mây)', 'Trạng Thái Mây', 'Tín Hiệu Kumo'] if c in df_sheet.columns]
                        if ta_cols:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet[ta_cols].head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"
                    # ===============================================

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
                1. DỮ LIỆU NỀN TẢNG: Bảng RS_DATA và TA_DATA cung cấp bên dưới là DỮ LIỆU CHỐT PHIÊN HÔM QUA (dùng để xem xu hướng, RS, Ichimoku, Tech Score).
                2. BẮT BUỘC KIỂM TRA GIÁ REAL-TIME: Khi người dùng hỏi về diễn biến hôm nay, điểm mua/bán hiện tại của một mã cổ phiếu cụ thể, bạn PHẢI gọi công cụ `get_live_stock_data` để lấy giá ngay lập tức, sau đó so sánh mức giá Real-time này với dữ liệu ngày hôm qua để phân tích sự đột biến.
                3. TÌM KIẾM TIN TỨC: Gọi `search_internet` nếu cần tìm tin nóng giải thích cho biến động giá.
                4. CẤM: Không in lại bảng dữ liệu CSV thô.
                5. MIỄN TRỪ TRÁCH NHIỆM: Ở CUỐI MỌI CÂU TRẢ LỜI, chèn chính xác: "*Miễn trừ trách nhiệm: Thông tin chỉ mang tính chất tham khảo dựa trên dữ liệu hiện có và không phải là lời khuyên đầu tư.*"
                """
                
                full_prompt = f"{sys_prompt}\n\n📊 KHO DỮ LIỆU NỘI BỘ:\n{data_context}\n\nTRUY VẤN: {prompt}"
                
                # 3.4. Gọi mô hình (Nạp thêm Tool mới vào đây)
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        tools=[search_internet, get_live_stock_data] # Đã nạp 2 thanh gươm!
                    )
                )
                
                # 3.5. Xử lý Function Calling Đa Nhiệm
                if response.function_calls:
                    # Tạo mảng lưu trữ cuộc hội thoại
                    messages_for_ai = [
                        types.Content(role="user", parts=[types.Part.from_text(full_prompt)]),
                        response.candidates[0].content
                    ]
                    
                    tool_response_parts = []
                    
                    # Quét xem AI muốn dùng vũ khí nào
                    for tool_call in response.function_calls:
                        result_text = ""
                        
                        if tool_call.name == "search_internet":
                            query = tool_call.args.get("query", prompt)
                            st.caption(f"🌐 Đang quét mạng Internet: '{query}'...")
                            result_text = search_internet(query)
                            
                        elif tool_call.name == "get_live_stock_data":
                            ticker = tool_call.args.get("ticker", "")
                            st.caption(f"⚡ Đang dò sóng Radar Real-time mã: {ticker}...")
                            result_text = get_live_stock_data(ticker)
                            
                        # Đóng gói kết quả của công cụ
                        tool_response_parts.append(
                            types.Part.from_function_response(
                                name=tool_call.name, 
                                response={"result": result_text}
                            )
                        )
                    
                    # Gửi kết quả từ các công cụ về cho AI phân tích tiếp
                    messages_for_ai.append(types.Content(role="user", parts=tool_response_parts))
                    
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
