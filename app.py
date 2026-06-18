import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

# ==========================================
# CẤU HÌNH GIAO DIỆN CHÍNH
# ==========================================
st.set_page_config(page_title="LINANCE TERMINAL", page_icon="CORE", layout="centered")

# ==========================================
# 1. KHAI BÁO CÁC HÀM TIỆN ÍCH & AI SKILLS
# ==========================================
@st.cache_data(ttl=600)
def load_all_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open("RS_DATA") 
        all_data = {}
        for ws in spreadsheet.worksheets():
            # Lệnh UNFORMATTED_VALUE ép Google trả về đúng số thực (VD: 138.32), ngăn chặn việc xóa dấu phẩy
            records = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
            if records:
                all_data[ws.title] = pd.DataFrame(records)
        return all_data
    except Exception as e:
        st.error(f"SYSTEM ERROR (DATA_LOAD): {e}")
        return {}

# ==========================================
# 2. HÀM GIAO DIỆN HỒ SƠ SỨC KHỎE ĐÃ ĐỒNG BỘ ĐỊNH DẠNG
# ==========================================
def render_rpg_card(ticker: str, df_rs: pd.DataFrame, df_ta: pd.DataFrame = None):
    stock_rs = df_rs[df_rs['Mã CK'] == ticker]
    if stock_rs.empty:
        st.warning(f"Mã cổ phiếu {ticker} chưa có dữ liệu trong hệ thống.")
        return
        
    data = stock_rs.iloc[0].to_dict()
    
    # Hàm xử lý chuẩn: Nhận số thực (138.32) và hiển thị định dạng Việt Nam (138,32)
    def format_vn(val):
        try:
            if pd.isna(val): return "N/A"
            v = float(val)
            if v.is_integer(): return str(int(v))
            return f"{v:.2f}".replace('.', ',')
        except:
            return str(val)

    # Định dạng các chỉ số hiển thị UI
    display_pe = format_vn(data.get('P/E', 'N/A'))
    display_pb = format_vn(data.get('P/B', 'N/A'))
    display_roe = format_vn(data.get('ROE (%)', 'N/A'))
    
    try:
        current_price = float(data.get('Giá', 0))
        display_price = f"{current_price:,.0f} VNĐ".replace(',', '.')
    except:
        display_price = "N/A"
    
    # Dữ liệu tính toán thanh tiến độ vẫn an toàn do giữ nguyên dạng float gốc
    atk_score = int(data.get('RS_1M', 50))
    mp_score = int(data.get('MFI_14', 50))
    tech_score = data.get('Tech_Score', 0)
    
    def_score = 50
    if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
        ta_data = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
        if "TRÊN Mây" in str(ta_data.get('Trạng Thái Mây', '')): def_score += 30
        elif "DƯỚI Mây" in str(ta_data.get('Trạng Thái Mây', '')): def_score -= 20
        
    try:
        if float(data.get('ROE (%)', 0)) > 15: def_score += 20
    except: pass

    int_score = 50
    try:
        pe_f = float(data.get('P/E', 0))
        if 0 < pe_f < 15: int_score += 20
        elif pe_f > 25 or pe_f < 0: int_score -= 20
        
        pb_f = float(data.get('P/B', 0))
        if 0 < pb_f < 1.5: int_score += 20
        elif pb_f > 3.0: int_score -= 20
        
        debt_f = float(data.get('Nợ/Vốn Chủ', 0))
        if 0 <= debt_f < 1.0: int_score += 10
        elif debt_f > 2.0: int_score -= 10
    except: pass

    atk_score = min(max(atk_score, 0), 100)
    mp_score = min(max(mp_score, 0), 100)
    def_score = min(max(def_score, 0), 100)
    int_score = min(max(int_score, 0), 100)

    if tech_score >= 6: tier, t_col = "S-TIER", "#FFD700"
    elif tech_score >= 3: tier, t_col = "A-TIER", "#00FF00"
    elif tech_score >= 0: tier, t_col = "B-TIER", "#0A84FF"
    else: tier, t_col = "C-TIER", "#FF3A3A"

    industry = str(data.get('Ngành', ''))
    if "Ngân hàng" in industry: rpg_class = "TANKER (Phòng thủ)"
    elif "Chứng khoán" in industry: rpg_class = "ASSASSIN (Đột phá)"
    elif "Công nghệ" in industry: rpg_class = "MAGE (Công nghệ)"
    elif "Bất động sản" in industry: rpg_class = "BERSERKER (Chu kỳ)"
    else: rpg_class = "RANGER (Linh hoạt)"

    st.markdown(f"""
    <div style="background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: 18px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin:0; color:#FFF;">[{ticker}] - {rpg_class}</h3>
        <p style="color:{t_col}; font-weight:bold; font-size:18px;">XẾP HẠNG: {tier}</p>
        <hr style="border-color: rgba(255,255,255,0.1); margin: 10px 0;">
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**ATK (Tấn công - Sức mạnh giá):** {atk_score}")
        st.progress(atk_score / 100)
        
        st.markdown(f"**MP (Mana - Dòng tiền):** {mp_score}")
        st.progress(mp_score / 100)
        
        st.markdown(f"**GIÁ HIỆN TẠI:** {display_price}")

    with col2:
        st.markdown(f"**DEF (Phòng thủ - Xu hướng):** {def_score}")
        st.progress(def_score / 100)
        
        st.markdown(f"**INT (Trí tuệ - Định giá):** {int_score}")
        st.progress(int_score / 100)
        
        st.markdown(f"**THÔNG SỐ:** P/E: {display_pe} | P/B: {display_pb} | ROE: {display_roe}%")
        
    st.markdown("</div>", unsafe_allow_html=True)

def search_internet(query: str) -> str:
    from duckduckgo_search import DDGS
    try:
        results = DDGS().text(query, max_results=3, region='vn-tz')
        if not results: return "Hệ thống không tìm thấy thông tin phù hợp trên Internet."
        formatted_results = [f"- Tiêu đề: {r['title']}\n  Nội dung: {r['body']}\n  Nguồn: {r['href']}" for r in results]
        return "\n".join(formatted_results)
    except Exception as e:
        return f"SYSTEM ERROR (NETWORK): {e}"

def get_live_stock_data(ticker: str) -> str:
    import yfinance as yf
    try:
        ticker = ticker.strip().upper()
        yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
        stock = yf.Ticker(yf_ticker)
        current_price = stock.fast_info['lastPrice']
        if current_price < 1000: current_price *= 1000
        return f"[SYSTEM REAL-TIME UPDATE] Mức giá hiện tại của {ticker} là: {current_price:,.0f} VNĐ."
    except Exception as e:
        return f"Hệ thống không thể truy xuất dữ liệu realtime cho {ticker}. Lỗi: {e}"

def draw_technical_chart(ticker: str) -> str:
    """Công cụ bắt buộc sử dụng khi người dùng yêu cầu xem đồ thị, biểu đồ kỹ thuật hoặc lịch sử xu hướng giá của một mã cổ phiếu cụ thể."""
    return f"[SYSTEM CHART COMMAND] Kích hoạt cấu trúc lệnh dựng đồ thị tương tác nội bộ cho mã: {ticker}."

# ==========================================
# 2. KHỞI TẠO BỘ NHỚ TRUNG TÂM
# ==========================================
dict_dfs = load_all_sheets()
API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 3. GIAO DIỆN CHÍNH & CSS
# ==========================================
st.markdown("""
<style>
    :root {
        --ios-radius: 18px;
        --ai-accent: #0A84FF; 
        --ai-glow: rgba(10, 132, 255, 0.3);
        --glass-bg: rgba(128, 128, 128, 0.08); 
        --glass-border: rgba(128, 128, 128, 0.2);
    }
    .main-header { padding: 30px 20px; margin-bottom: 20px; text-align: center; border-bottom: 1px solid var(--glass-border); background: transparent; }
    .main-header h1 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-weight: 800 !important; letter-spacing: 2px; margin-bottom: 8px; font-size: 32px !important; }
    .main-header p { font-family: "Courier New", Courier, monospace; font-weight: 600; letter-spacing: 3px; text-transform: uppercase; font-size: 12px; color: var(--ai-accent); }
    div[data-testid="stChatMessage"] { background-color: var(--glass-bg); border-radius: var(--ios-radius); border: 1px solid var(--glass-border); padding: 15px; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); margin-bottom: 15px; }
    .stChatInput { border-radius: var(--ios-radius) !important; border: 1.5px solid var(--ai-accent) !important; box-shadow: 0 0 15px var(--ai-glow) !important; transition: all 0.3s ease; }
    div.stButton > button { background-color: var(--ai-accent) !important; color: #FFFFFF !important; font-weight: 700 !important; letter-spacing: 1px; border-radius: 12px !important; border: none !important; transition: all 0.3s ease; }
    div.stButton > button:hover { box-shadow: 0 0 20px var(--ai-glow) !important; transform: translateY(-2px); }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'><h1>LINANCE TERMINAL</h1><p>SYS.CORE // AI QUANTITATIVE ANALYSIS</p></div>", unsafe_allow_html=True)

# ==========================================
# 4. BẢNG ĐIỀU KHIỂN HỆ THỐNG (SIDEBAR)
# ==========================================
with st.sidebar:
    st.markdown("### HỆ THỐNG ĐIỀU KHIỂN")
    st.caption("TRẠNG THÁI: KẾT NỐI API ỔN ĐỊNH")
    if st.button("CẬP NHẬT DỮ LIỆU"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### HỒ SƠ SỨC KHỎE CỔ PHIẾU")
    rpg_ticker = st.text_input("Nhập Mã CK (VD: HPG):", "").upper()
    
    if rpg_ticker:
        if dict_dfs:
            df_rs = dict_dfs.get("RS_DATA", pd.DataFrame())
            df_ta = dict_dfs.get("TA_DATA", pd.DataFrame())
            if not df_rs.empty:
                render_rpg_card(rpg_ticker, df_rs, df_ta)
            else:
                st.warning("Hệ thống cảnh báo: Dữ liệu RS_DATA đang trống.")
        else:
            st.error("Lỗi truy xuất: Chưa tải được dữ liệu hệ thống.")

# ==========================================
# 5. TRUNG TÂM XỬ LÝ CHATBOT AI AGENT
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "LINANCE CORE ONLINE. Hệ thống phân tích đã sẵn sàng tiếp nhận truy vấn."}]

# HIỂN THỊ LẠI LỊCH SỬ CHAT VÀ ĐỒ THỊ ĐÃ LƯU
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "chart" in message and message["chart"] is not None:
            st.line_chart(message["chart"])

if prompt := st.chat_input("Nhập mã chứng khoán hoặc truy vấn phân tích..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        chart_data_to_save = None # Biến bảo chứng đồ thị
        
        with st.spinner("ĐANG XỬ LÝ TRUY VẤN..."):
            try:
                data_context = ""
                for sheet_name, df_sheet in dict_dfs.items():
                    if not df_sheet.empty:
                        if sheet_name == "RS_DATA":
                            essential_cols = [c for c in ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'Tech_Score', 'Trạng Thái', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ'] if c in df_sheet.columns]
                            if essential_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet[essential_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"
                                
                        elif sheet_name == "TA_DATA":
                            ta_cols = [c for c in ['Mã CK', 'Giá Hiện Tại', 'Tenkan_sen (9)', 'Kijun_sen (26)', 'Senkou_A (Mây)', 'Senkou_B (Mây)', 'Trạng Thái Mây', 'Tín Hiệu Kumo'] if c in df_sheet.columns]
                            if ta_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet[ta_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_sheet.head(200).to_csv(index=False)}\n\n"

                st.caption(f"Dữ liệu hệ thống đã nạp: {', '.join(dict_dfs.keys())}")

                client = genai.Client(api_key=API_KEY)
                
                sys_prompt = """
                Bạn là Bậc thầy Phân tích Định lượng và Cố vấn Giao dịch cấp tổ chức tại LINANCE Terminal.
                MỤC TIÊU CỐT LÕI: Loại bỏ hoàn toàn các nhận định chung chung, nước đôi. Mọi tư vấn phải sắc bén, mang tính quyết đoán và có thể giao dịch ngay (Actionable Trading Plan).

                NGUYÊN TẮC HOẠT ĐỘNG:
                1. QUÉT BÙNG NỔ KHỐI LƯỢNG & TỔNG QUAN: Khi được hỏi về toàn cảnh thị trường hoặc tìm kiếm cơ hội, hãy tự động rà quét tập dữ liệu để tìm ra các mã có tín hiệu "Bùng nổ dòng tiền": RS_1M cao vượt trội (Sức mạnh giá) kết hợp với MFI_14 lớn (Dòng tiền thông minh nhập cuộc). Nhóm các mã này theo ngành để chỉ ra sóng ngành hiện tại.
                
                2. KẾ HOẠCH GIAO DỊCH CHUYÊN SÂU: Khi phân tích một hoặc nhiều mã cổ phiếu cụ thể, BẮT BUỘC trình bày theo cấu trúc chuẩn mực sau:
                   - LUẬN ĐIỂM ĐẦU TƯ: Đánh giá nhanh sự hội tụ giữa Phân tích Kỹ thuật (RS, Trạng Thái Mây Ichimoku) và Phân tích Cơ bản (P/E, P/B, ROE). Cổ phiếu này đang có câu chuyện gì?
                   - VÙNG MUA (ENTRY RANGE): Xác định vùng giá gom hàng an toàn dựa trên giá Real-time và hỗ trợ gần nhất (Tenkan/Kijun hoặc Mây Kumo).
                   - ĐIỂM CẮT LỖ (STOP-LOSS): Đưa ra mức giá cắt lỗ cứng (Hard stop) và giải thích lý do (Ví dụ: Thủng Kijun-sen, rơi khỏi mây Senkou_A).
                   - ĐIỂM CHỐT LỜI (TAKE-PROFIT): Đưa ra vùng giá mục tiêu kỳ vọng.
                   - TỶ LỆ R:R (RISK/REWARD): Bắt buộc tính toán và trình bày tỷ lệ R:R (Ví dụ: 1:2.5, 1:3). Đưa ra lời khuyên rõ ràng: "Đủ hấp dẫn để giải ngân" hoặc "Tỷ lệ R:R rủi ro, nên quan sát thêm".

                3. TÍCH HỢP BÁO CÁO TỔ CHỨC: Tự động kích hoạt công cụ `search_internet` với từ khóa "Báo cáo phân tích + Mã cổ phiếu + Khuyến nghị" để lấy thêm góc nhìn định giá từ các tổ chức tài chính lớn làm luận điểm bảo vệ cho kế hoạch giao dịch.

                4. KIỂM CHỨNG REAL-TIME: Bắt buộc dùng `get_live_stock_data` để cập nhật giá hiện tại trước khi đưa ra bất kỳ con số nào cho Điểm Mua. Không bao giờ dùng giá chốt phiên hôm qua để làm giá Entry cho hôm nay.

                5. TRIỆU HỒI ĐỒ THỊ: Khi người dùng yêu cầu xem đồ thị, biểu đồ kỹ thuật hoặc lịch sử xu hướng giá, BẮT BUỘC phải sử dụng công cụ `draw_technical_chart` để hệ thống tự động vẽ biểu đồ trực quan.

                6. VĂN PHONG VÀ TRÌNH BÀY:
                   - Sử dụng ngôn ngữ tài chính chuyên nghiệp, lạnh lùng và dứt khoát.
                   - Tuyệt đối KHÔNG sử dụng biểu tượng cảm xúc (emoji).
                   - Trình bày rõ ràng bằng các gạch đầu dòng (bullet points) và bôi đậm các mức giá quan trọng.

                7. MIỄN TRỪ TRÁCH NHIỆM: Ở cuối mọi câu trả lời, luôn chèn chính xác văn bản: "*Miễn trừ trách nhiệm: Kế hoạch giao dịch trên được tổng hợp từ thuật toán định lượng và dữ liệu thị trường hiện hành, nhà đầu tư tự quản trị rủi ro đối với quyết định giải ngân.*"
                """
                
                full_prompt = f"{sys_prompt}\n\nKHO DỮ LIỆU NỘI BỘ:\n{data_context}\n\nTRUY VẤN: {prompt}"
                
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        tools=[search_internet, get_live_stock_data, draw_technical_chart] 
                    )
                )
                
                if response.function_calls:
                    messages_for_ai = [
                        types.Content(role="user", parts=[types.Part.from_text(full_prompt)]),
                        response.candidates[0].content
                    ]
                    
                    tool_response_parts = []
                    for tool_call in response.function_calls:
                        result_text = ""
                        if tool_call.name == "search_internet":
                            query = tool_call.args.get("query", prompt)
                            st.caption(f"Hệ thống đang truy xuất dữ liệu Internet: '{query}'...")
                            result_text = search_internet(query)
                            
                        elif tool_call.name == "get_live_stock_data":
                            ticker = tool_call.args.get("ticker", "")
                            st.caption(f"Hệ thống đang cập nhật dữ liệu Real-time mã: {ticker}...")
                            result_text = get_live_stock_data(ticker)
                            
                        elif tool_call.name == "draw_technical_chart":
                            ticker = tool_call.args.get("ticker", "").strip().upper()
                            st.caption(f"Hệ thống đang kết nối API để dựng đồ thị mã: {ticker}...")
                            
                            try:
                                import yfinance as yf
                                yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
                                stock = yf.Ticker(yf_ticker)
                                hist_data = stock.history(period="6mo")
                                if not hist_data.empty:
                                    # Lấy dữ liệu lưu trữ
                                    chart_df = hist_data[['Close']].copy()
                                    chart_df.rename(columns={'Close': f'Giá {ticker}'}, inplace=True)
                                    chart_data_to_save = chart_df
                                    result_text = f"[SYSTEM] Đồ thị xu hướng giá 6 tháng của {ticker} ĐÃ ĐƯỢC VẼ THÀNH CÔNG trên màn hình người dùng. Hãy phân tích xu hướng dựa trên nó."
                                else:
                                    err_msg = f"Không tìm thấy dữ liệu giá lịch sử của mã {ticker} trên máy chủ chứng khoán."
                                    st.error(f"LỖI HỆ THỐNG: {err_msg}")
                                    result_text = f"[SYSTEM CẢNH BÁO] {err_msg}"
                            except ImportError:
                                err_msg = "Chưa cài đặt thư viện yfinance. Vui lòng chạy lệnh: !pip install yfinance"
                                st.error(f"LỖI HỆ THỐNG: {err_msg}")
                                result_text = f"[SYSTEM FAULT] {err_msg}"
                            except Exception as chart_err:
                                st.error(f"LỖI HỆ THỐNG VẼ ĐỒ THỊ: {chart_err}")
                                result_text = f"[SYSTEM FAULT] Lỗi kéo dữ liệu đồ thị: {chart_err}"
                                
                        tool_response_parts.append(
                            types.Part.from_function_response(
                                name=tool_call.name, 
                                response={"result": result_text}
                            )
                        )
                    
                    messages_for_ai.append(types.Content(role="user", parts=tool_response_parts))
                    response = client.models.generate_content(
                        model='gemini-3.1-flash-lite',
                        contents=messages_for_ai,
                        config=types.GenerateContentConfig(temperature=0.2)
                    )
            except Exception as e:
                st.error(f"SYSTEM FAULT: {e}")
                response = None

        # BƯỚC QUYẾT ĐỊNH: VẼ ĐỒ THỊ VÀ VĂN BẢN NẰM NGOÀI VÒNG LẶP SPINNER
        if response:
            st.markdown(response.text)
            
            # Xuất đồ thị thực tế ra giao diện
            if chart_data_to_save is not None:
                st.line_chart(chart_data_to_save)
                
            # Lưu đồng bộ vào bộ nhớ tạm để không bị mất khi chat câu mới
            new_msg = {"role": "assistant", "content": response.text}
            if chart_data_to_save is not None:
                new_msg["chart"] = chart_data_to_save
            st.session_state.messages.append(new_msg)
