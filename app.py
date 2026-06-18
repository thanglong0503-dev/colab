import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
import re

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
    
    def format_vn(val):
        try:
            if pd.isna(val): return "N/A"
            v = float(val)
            if v.is_integer(): return str(int(v))
            return f"{v:.2f}".replace('.', ',')
        except:
            return str(val)

    display_pe = format_vn(data.get('P/E', 'N/A'))
    display_pb = format_vn(data.get('P/B', 'N/A'))
    display_roe = format_vn(data.get('ROE (%)', 'N/A'))
    
    try:
        current_price = float(data.get('Giá', 0))
        display_price = f"{current_price:,.0f} VNĐ".replace(',', '.')
    except:
        display_price = "N/A"
    
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
        
        # TÍNH TOÁN KHỐI LƯỢNG ĐỘT BIẾN REAL-TIME
        hist = stock.history(period="1mo")
        if not hist.empty and len(hist) > 0:
            current_vol = hist['Volume'].iloc[-1]
            avg_vol_20 = hist['Volume'].mean()
            surge_ratio = (current_vol / avg_vol_20) * 100 if avg_vol_20 > 0 else 0
            vol_info = f"Khối lượng phiên nay: {current_vol:,.0f} | KL Trung bình 20 phiên: {avg_vol_20:,.0f} | Mức độ đột biến: {surge_ratio:.1f}%"
        else:
            vol_info = "Không trích xuất được dữ liệu khối lượng."
            
        return f"[SYSTEM REAL-TIME UPDATE] Mã: {ticker} | Giá: {current_price:,.0f} VNĐ | {vol_info}."
    except Exception as e:
        return f"Hệ thống không thể truy xuất dữ liệu realtime cho {ticker}. Lỗi: {e}"

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
    st.session_state.messages = [{"role": "assistant", "content": "LINANCE CORE ONLINE. Hệ thống phân tích đã sẵn sàng tiếp nhận truy vấn. Tính năng soi Đột biến Khối lượng đã được kích hoạt."}]

# HIỂN THỊ LẠI LỊCH SỬ CHAT
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Nhập mã chứng khoán hoặc truy vấn phân tích..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("ĐANG XỬ LÝ TRUY VẤN..."):
            try:
                data_context = ""
                for sheet_name, df_sheet in dict_dfs.items():
                    if not df_sheet.empty:
                        df_clean = df_sheet.copy().round(2)
                        if sheet_name == "RS_DATA":
                            # ĐÃ BỔ SUNG CỘT KL_TB_20 VÀ Đột_Biến_KL VÀO CẤU TRÚC NGỮ CẢNH AI
                            essential_cols = [c for c in ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'KL_TB_20', 'Đột_Biến_KL', 'Tech_Score', 'Trạng Thái', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ'] if c in df_clean.columns]
                            if essential_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean[essential_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"
                                
                        elif sheet_name == "TA_DATA":
                            ta_cols = [c for c in ['Mã CK', 'Giá Hiện Tại', 'Tenkan_sen (9)', 'Kijun_sen (26)', 'Senkou_A (Mây)', 'Senkou_B (Mây)', 'Trạng Thái Mây', 'Tín Hiệu Kumo'] if c in df_clean.columns]
                            if ta_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean[ta_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"

                st.caption(f"Dữ liệu hệ thống đã nạp: {', '.join(dict_dfs.keys())}")

                client = genai.Client(api_key=API_KEY)
                
                sys_prompt = """
                Bạn là Bậc thầy Phân tích Định lượng và Cố vấn Giao dịch cấp tổ chức tại LINANCE Terminal.
                MỤC TIÊU CỐT LÕI: Đưa ra Kế hoạch Giao dịch (Actionable Trading Plan) quyết đoán. Tuyệt đối không nhận định nước đôi.

                NGUYÊN TẮC HOẠT ĐỘNG:
                1. ĐỘT BIẾN KHỐI LƯỢNG LÀ TÍN HIỆU CỐT LÕI: Khi phân tích, luôn chú ý đến sự đột biến khối lượng (Đột_Biến_KL hoặc dữ liệu Real-time). Nếu mức độ đột biến > 150%, xác nhận đây là dấu vết của dòng tiền lớn (Smart Money).
                2. KẾ HOẠCH GIAO DỊCH: BẮT BUỘC trình bày theo cấu trúc: 
                   - LUẬN ĐIỂM (Tập trung vào sự xác nhận của khối lượng và giá).
                   - VÙNG MUA (Entry Range).
                   - ĐIỂM CẮT LỖ CỨNG (Stop-loss).
                   - ĐIỂM CHỐT LỜI (Take-profit).
                   - TỶ LỆ R:R.
                3. BÁO CÁO TỔ CHỨC: Gọi `search_internet` tìm báo cáo phân tích mới nhất.
                4. KIỂM CHỨNG REAL-TIME: Luôn gọi `get_live_stock_data` để cập nhật giá và XÁC NHẬN KHỐI LƯỢNG TRONG NGÀY.
                5. VĂN PHONG VÀ TRÌNH BÀY: Chuyên nghiệp, lạnh lùng, định lượng. Tuyệt đối KHÔNG dùng emoji.
                6. MIỄN TRỪ TRÁCH NHIỆM: Cuối câu trả lời luôn có: "*Miễn trừ trách nhiệm: Kế hoạch giao dịch trên được tổng hợp từ thuật toán định lượng và dữ liệu thị trường hiện hành, nhà đầu tư tự quản trị rủi ro đối với quyết định giải ngân.*"
                """
                
                full_prompt = f"{sys_prompt}\n\nKHO DỮ LIỆU NỘI BỘ:\n{data_context}\n\nTRUY VẤN: {prompt}"
                
                response = client.models.generate_content(
                    model='gemini-3.1-flash-lite', 
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        tools=[search_internet, get_live_stock_data] 
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
                            st.caption(f"Hệ thống đang truy xuất Internet: '{query}'...")
                            result_text = search_internet(query)
                            
                        elif tool_call.name == "get_live_stock_data":
                            ticker = tool_call.args.get("ticker", "")
                            st.caption(f"Hệ thống đang lấy giá và khối lượng Real-time mã: {ticker}...")
                            result_text = get_live_stock_data(ticker)
                                
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

        # HIỂN THỊ KẾT QUẢ ĐẦU RA AN TOÀN NGOÀI SPINNER
        if response:
            st.markdown(response.text)
            
            # Lưu lại ngữ cảnh vào bộ nhớ hệ thống
            st.session_state.messages.append({"role": "assistant", "content": response.text})
