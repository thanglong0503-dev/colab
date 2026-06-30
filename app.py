import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
import re
import streamlit.components.v1 as components
import base64
from datetime import datetime
import matplotlib.pyplot as plt
import io

# ==========================================
# CẤU HÌNH GIAO DIỆN CHÍNH
# ==========================================
st.set_page_config(page_title="LINANCE TERMINAL", page_icon="CORE", layout="centered")

# ==========================================
# 1. LÕI KỸ THUẬT: VẼ ĐỒ THỊ NẾN & MÃ HÓA BASE64
# ==========================================
def generate_chart_base64(ticker: str, df_ta: pd.DataFrame):
    """Hàm vẽ đồ thị nến Nhật 30 phiên và ghim các mốc chiến thuật, trả về mã Base64."""
    import yfinance as yf
    try:
        # 1. Lấy dữ liệu 30 phiên gần nhất
        yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="45d").tail(30) # Lấy dư để chốt đúng 30 nến
        
        if hist.empty:
            return ""

        # 2. Lấy dữ liệu TA để kẻ mốc chiến thuật
        tenkan_val, kijun_val = None, None
        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta_data = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            tenkan_val = float(ta_data.get('Tenkan_sen', 0))
            kijun_val = float(ta_data.get('Kijun_sen', 0))

        # 3. Khởi tạo Figure Matplotlib
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
        fig.patch.set_facecolor('#0B0F17')
        ax.set_facecolor('#0B0F17')

        # 4. Vẽ biểu đồ nến thủ công
        x_indices = range(len(hist))
        for i in x_indices:
            row = hist.iloc[i]
            color = '#10B981' if row['Close'] >= row['Open'] else '#EF4444' # Xanh/Đỏ
            # Vẽ râu nến (Shadow)
            ax.plot([i, i], [row['Low'], row['High']], color=color, linewidth=1)
            # Vẽ thân nến (Body)
            body_bottom = min(row['Open'], row['Close'])
            body_top = max(row['Open'], row['Close'])
            body_height = max(body_top - body_bottom, 0.001) # Tránh nến Doji bị ẩn
            ax.add_patch(plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height, facecolor=color, edgecolor=color))

        # 5. Kẻ các đường mốc chiến thuật (Từ TA_DATA)
        current_price = hist['Close'].iloc[-1]
        ax.axhline(y=current_price, color='#0A84FF', linestyle='-', linewidth=1.5, alpha=0.8, label=f'Giá hiện tại: {current_price:,.0f}')
        
        if tenkan_val and tenkan_val > 0:
            ax.axhline(y=tenkan_val, color='#F59E0B', linestyle='--', linewidth=1.2, alpha=0.8, label=f'Hỗ trợ (Tenkan): {tenkan_val:,.0f}')
        if kijun_val and kijun_val > 0:
            ax.axhline(y=kijun_val, color='#EF4444', linestyle='-.', linewidth=1.2, alpha=0.8, label=f'Cắt lỗ cứng (Kijun): {kijun_val:,.0f}')

        # 6. Tinh chỉnh giao diện đồ thị
        ax.set_title(f"Hành vi giá 30 phiên & Các mốc chiến thuật - {ticker}", color='white', pad=15, fontsize=12, fontfamily='monospace')
        ax.legend(loc='upper left', fontsize=8, facecolor='#1C2635', edgecolor='none')
        ax.grid(True, color='white', alpha=0.05)
        ax.set_xticks(x_indices[::5]) # Hiện ngày cách nhau 5 phiên
        ax.set_xticklabels([hist.index[i].strftime('%d/%m') for i in x_indices[::5]], rotation=45, color='gray', fontsize=8)
        ax.tick_params(axis='y', colors='gray', labelsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#333333')
        ax.spines['bottom'].set_color('#333333')
        
        plt.tight_layout()

        # 7. Xuất ra luồng Base64
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{img_b64}"
    except Exception as e:
        return ""

# ==========================================
# 2. KHAI BÁO CÁC HÀM TIỆN ÍCH, UI & AI SKILLS
# ==========================================
def render_copy_button(text_to_copy):
    text_b64 = base64.b64encode(text_to_copy.encode('utf-8')).decode('utf-8')
    html_code = f"""
    <body style="margin: 0; padding: 0; overflow: hidden; background-color: transparent;">
        <style>
        .copy-btn {{ background-color: transparent; color: #0A84FF; border: 1px solid rgba(10, 132, 255, 0.5); border-radius: 6px; padding: 6px 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: bold; cursor: pointer; transition: all 0.3s ease; display: inline-flex; align-items: center; justify-content: center; }}
        .copy-btn:hover {{ background-color: #0A84FF; color: #FFFFFF; box-shadow: 0 0 10px rgba(10, 132, 255, 0.4); border: 1px solid #0A84FF; }}
        </style>
        <button class="copy-btn" id="copyBtn">COPY PLAN</button>
        <script>
        document.getElementById("copyBtn").addEventListener("click", function() {{
            const binaryString = window.atob('{text_b64}');
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {{ bytes[i] = binaryString.charCodeAt(i); }}
            const decodedText = new TextDecoder('utf-8').decode(bytes);
            navigator.clipboard.writeText(decodedText).then(function() {{
                document.getElementById("copyBtn").innerText = "✅ COPIED!";
                setTimeout(() => document.getElementById("copyBtn").innerText = "COPY PLAN", 2000);
            }});
        }});
        </script>
    </body>
    """
    return html_code

def render_pdf_button(ai_content, ticker_name, dict_dfs):
    """Render file PDF nhúng Font Roboto, ĐỒ THỊ KỸ THUẬT và BỐ CỤC 2 CỘT CHUYÊN NGHIỆP."""
    current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    # Tiền xử lý nội dung văn bản của AI
    html_content = ai_content.replace('\n', '<br>').replace('**', '<b>')
    html_content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html_content)
    
    # 1. Trích xuất dữ liệu tài chính từ RS_DATA cho Cột Trái
    df_rs = dict_dfs.get("RS_DATA", pd.DataFrame()) if dict_dfs else pd.DataFrame()
    stock_data = {}
    if not df_rs.empty and ticker_name in df_rs['Mã CK'].values:
        stock_data = df_rs[df_rs['Mã CK'] == ticker_name].iloc[0].to_dict()
        
    def format_vn(val):
        try:
            if pd.isna(val): return "N/A"
            v = float(val)
            if v.is_integer(): return str(int(v))
            return f"{v:.2f}".replace('.', ',')
        except:
            return str(val)

    gia_ht = format_vn(stock_data.get('Giá', 'N/A'))
    pe = format_vn(stock_data.get('P/E', 'N/A'))
    pb = format_vn(stock_data.get('P/B', 'N/A'))
    roe = format_vn(stock_data.get('ROE (%)', 'N/A'))
    
    # 2. Tạo mã Base64 cho biểu đồ (lấy từ TA_DATA để vẽ Hỗ trợ/Kháng cự)
    df_ta = dict_dfs.get("TA_DATA", None) if dict_dfs else None
    chart_base64 = generate_chart_base64(ticker_name, df_ta)
    
    chart_html = ""
    if chart_base64:
        chart_html = f'<div style="margin-top: 20px; border: 1px solid #ddd; padding: 10px; border-radius: 8px;"><img src="{chart_base64}" style="width: 100%; height: auto;"></div>'
    
    # 3. Xây dựng Bố cục 2 Cột (Chuẩn Institutional Report)
    raw_report_html = f"""
    <link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,700;1,400&subset=vietnamese&display=swap" rel="stylesheet">
    <div style="font-family: 'Roboto', sans-serif; padding: 40px; color: #333; line-height: 1.6; background-color: white; max-width: 1000px; margin: 0 auto;">
        
        <!-- HEADER BÁO CÁO -->
        <div style="background: #0078D4; color: white; padding: 20px 30px; margin-bottom: 30px; border-radius: 8px 8px 0 0; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 14px; text-transform: uppercase; letter-spacing: 2px; opacity: 0.8;">BÁO CÁO PHÂN TÍCH ĐỊNH LƯỢNG</div>
                <div style="font-size: 32px; font-weight: 900; margin-top: 5px;">MÃ CỔ PHIẾU: {ticker_name}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 20px; font-weight: 700;">LINANCE.CORE</div>
                <div style="font-size: 12px; margin-top: 5px;">Ngày {current_time}</div>
            </div>
        </div>
        
        <!-- BODY 2 CỘT -->
        <div style="display: flex; gap: 40px;">
            <!-- CỘT TRÁI: DATA & CHART -->
            <div style="flex: 1; min-width: 300px; border-right: 2px solid #f0f0f0; padding-right: 30px;">
                <div style="font-size: 18px; font-weight: 700; color: #0078D4; border-bottom: 2px solid #0078D4; padding-bottom: 5px; margin-bottom: 15px;">THỐNG KÊ TÀI CHÍNH</div>
                <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px 0; color: #555;">Giá hiện tại</td><td style="text-align:right; font-weight: bold;">{gia_ht}</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px 0; color: #555;">P/E định giá</td><td style="text-align:right; font-weight: bold;">{pe}</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px 0; color: #555;">P/B</td><td style="text-align:right; font-weight: bold;">{pb}</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px 0; color: #555;">ROE (%)</td><td style="text-align:right; font-weight: bold;">{roe}%</td></tr>
                </table>
                
                {chart_html}
            </div>
            
            <!-- CỘT PHẢI: LUẬN ĐIỂM -->
            <div style="flex: 2;">
                <div style="font-size: 18px; font-weight: 700; color: #0078D4; border-bottom: 2px solid #0078D4; padding-bottom: 5px; margin-bottom: 15px;">KẾ HOẠCH GIAO DỊCH (ACTIONABLE PLAN)</div>
                <div style="font-size: 14px; text-align: justify;">
                    {html_content}
                </div>
            </div>
        </div>
        
        <!-- FOOTER -->
        <div style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 10px; color: #999; text-align: center; font-style: italic;">
            CONFIDENTIAL REPORT. Generated by LINANCE Quantitative AI System.<br>
            Disclaimer: Bản báo cáo này được tạo tự động bởi thuật toán định lượng. Nhà đầu tư tự chịu trách nhiệm với quyết định giải ngân.
        </div>
    </div>
    """
    
    # 4. Đóng gói Base64 và tạo Nút xuất PDF
    b64_html = base64.b64encode(raw_report_html.encode('utf-8')).decode('utf-8')
    file_name = f"LINANCE_{ticker_name}_{datetime.now().strftime('%d%m%Y_%H%M')}.pdf"
    
    button_code = f"""
    <body style="margin: 0; padding: 0; overflow: hidden; background-color: transparent;">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <style>
        .pdf-btn {{ background-color: transparent; color: #10B981; border: 1px solid rgba(16, 185, 129, 0.5); border-radius: 6px; padding: 6px 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: bold; cursor: pointer; transition: all 0.3s ease; display: inline-flex; align-items: center; justify-content: center; }}
        .pdf-btn:hover {{ background-color: #10B981; color: #FFFFFF; box-shadow: 0 0 10px rgba(16, 185, 129, 0.4); border: 1px solid #10B981; }}
        </style>
        <button class="pdf-btn" id="dlPdfBtn" onclick="exportPDF()">📥 EXPORT PDF</button>
        <script>
        function exportPDF() {{
            document.getElementById("dlPdfBtn").innerText = "⏳ GENERATING...";
            const binaryString = window.atob('{b64_html}');
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {{ bytes[i] = binaryString.charCodeAt(i); }}
            const decodedHtml = new TextDecoder('utf-8').decode(bytes);
            
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = decodedHtml;
            
            var opt = {{
              margin:       0.4,
              filename:     '{file_name}',
              image:        {{ type: 'jpeg', quality: 0.98 }},
              html2canvas:  {{ scale: 2, useCORS: true }},
              jsPDF:        {{ unit: 'in', format: 'a4', orientation: 'portrait' }}
            }};
            
            setTimeout(() => {{
                html2pdf().set(opt).from(tempDiv).save().then(function() {{
                    document.getElementById("dlPdfBtn").innerText = "✅ DOWNLOADED!";
                    setTimeout(() => document.getElementById("dlPdfBtn").innerText = "📥 EXPORT PDF", 3000);
                }});
            }}, 500);
        }}
        </script>
    </body>
    """
    return button_code

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
# 3. HÀM GIAO DIỆN HỒ SƠ SỨC KHỎE
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

def draw_technical_chart(ticker: str) -> str:
    return f"[SYSTEM CHART COMMAND TRIGGERED] Hãy xác nhận bằng văn bản rằng đồ thị kỹ thuật mã {ticker} đang được hiển thị ngay bên dưới đoạn hội thoại."

# ==========================================
# 4. KHỞI TẠO BỘ NHỚ TRUNG TÂM
# ==========================================
dict_dfs = load_all_sheets()
API_KEY = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 5. GIAO DIỆN CHÍNH & CSS
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
    div.stButton > button { background-color: transparent !important; color: #10B981 !important; font-weight: 700 !important; font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.5px; border-radius: 6px !important; border: 1px solid rgba(16, 185, 129, 0.5) !important; transition: all 0.3s ease; padding: 4px 12px; }
    div.stButton > button:hover { background-color: #10B981 !important; color: #FFFFFF !important; box-shadow: 0 0 10px rgba(16, 185, 129, 0.4) !important; border: 1px solid #10B981 !important; transform: translateY(-1px); }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'><h1>LINANCE TERMINAL</h1><p>SYS.CORE // AI QUANTITATIVE ANALYSIS</p></div>", unsafe_allow_html=True)

# ==========================================
# 6. BẢNG ĐIỀU KHIỂN HỆ THỐNG (SIDEBAR)
# ==========================================
with st.sidebar:
    st.markdown("### HỆ THỐNG ĐIỀU KHIỂN")
    st.caption("TRẠNG THÁI: KẾT NỐI API ỔN ĐỊNH")
    if st.button("🔄 CẬP NHẬT DỮ LIỆU"):
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
# 7. TRUNG TÂM XỬ LÝ CHATBOT AI AGENT
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "LINANCE CORE ONLINE. Hệ thống xuất bản biểu đồ nến Tự động đã vào trạng thái trực chiến."}]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        if "chart" in message and message["chart"] is not None:
            st.line_chart(message["chart"])
            
        if message["role"] == "assistant":
            col_btn1, col_btn2, _ = st.columns([1.5, 2.5, 6])
            with col_btn1:
                components.html(render_copy_button(message["content"]), height=35)
            with col_btn2:
                ticker_match = re.search(r'\b[A-Z]{3}\b', message["content"])
                ticker_name = ticker_match.group(0) if ticker_match else "STOCK"
                components.html(render_pdf_button(message["content"], ticker_name, dict_dfs), height=35)

if prompt := st.chat_input("Nhập mã CK hoặc truy vấn..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        chart_data_to_save = None 
        
        with st.spinner("ĐANG XỬ LÝ TRUY VẤN VÀ VẼ ĐỒ THỊ..."):
            try:
                data_context = ""
                for sheet_name, df_sheet in dict_dfs.items():
                    if not df_sheet.empty:
                        df_clean = df_sheet.copy()
                        for col in df_clean.select_dtypes(include=['float64', 'float32']).columns:
                            df_clean[col] = df_clean[col].round(2)

                        if sheet_name == "RS_DATA":
                            essential_cols = [c for c in ['Mã CK', 'Ngành', 'Giá', 'RS_1M', 'KL_TB_20', 'Đột_Biến_KL', 'Tech_Score', 'Trạng Thái', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ'] if c in df_clean.columns]
                            if essential_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean[essential_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"
                                
                        elif sheet_name == "TA_DATA":
                            ta_cols = [c for c in ['Mã CK', 'Giá Hiện Tại', 'Tenkan_sen', 'Kijun_sen', 'Senkou_A', 'Senkou_B', 'Trạng Thái Mây', 'Tín Hiệu Kumo'] if c in df_clean.columns]
                            if ta_cols: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean[ta_cols].head(200).to_csv(index=False)}\n\n"
                            else: 
                                data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"
                        else:
                            data_context += f"--- DATASET: {sheet_name} ---\n{df_clean.head(200).to_csv(index=False)}\n\n"

                client = genai.Client(api_key=API_KEY)
                
                sys_prompt = """
                Bạn là Bậc thầy Phân tích Định lượng và Cố vấn Giao dịch cấp tổ chức tại LINANCE Terminal.
                MỤC TIÊU CỐT LÕI: Đưa ra Kế hoạch Giao dịch (Actionable Trading Plan) quyết đoán. Tuyệt đối không nhận định nước đôi.

                NGUYÊN TẮC HOẠT ĐỘNG:
                1. ĐỘT BIẾN KHỐI LƯỢNG LÀ TÍN HIỆU CỐT LÕI: Luôn kiểm tra sự đột biến khối lượng (Đột_Biến_KL hoặc dữ liệu Real-time).
                2. PHÂN TÍCH KỸ THUẬT & ICHIMOKU: Bắt buộc đối chiếu sự đồng thuận của hệ thống Ichimoku từ bảng TA_DATA để củng cố luận điểm.
                3. QUẢN TRỊ VỐN (POSITION SIZING): NẾU người dùng cung cấp quy mô vốn (NAV) và mức rủi ro, BẮT BUỘC thiết lập hạng mục TỶ TRỌNG ĐI TIỀN. Tính toán rõ số lượng cổ phiếu tối đa được phép mua.
                4. KẾ HOẠCH GIAO DỊCH: BẮT BUỘC trình bày theo cấu trúc: 
                   - LUẬN ĐIỂM ĐẦU TƯ: Sự hội tụ giữa Dòng tiền, Kỹ thuật và Cơ bản.
                   - VÙNG MUA (Entry Range): Dựa vào các mức hỗ trợ cứng của Ichimoku.
                   - ĐIỂM CẮT LỖ CỨNG (Stop-loss): Có giải thích lý do kỹ thuật rõ ràng.
                   - ĐIỂM CHỐT LỜI (Take-profit): Vùng giá mục tiêu kỳ vọng.
                   - TỶ TRỌNG ĐI TIỀN: (Chỉ hiện ra nếu có dữ liệu NAV và Rủi ro).
                   - TỶ LỆ R:R: Tính toán rủi ro/lợi nhuận thực tế.
                5. KIỂM CHỨNG REAL-TIME: Luôn gọi `get_live_stock_data` để cập nhật giá.
                6. VĂN PHONG VÀ TRÌNH BÀY: Chuyên nghiệp, lạnh lùng, định lượng. Tuyệt đối KHÔNG dùng emoji.
                7. MIỄN TRỪ TRÁCH NHIỆM: Ở cuối câu trả lời luôn chèn: "*Miễn trừ trách nhiệm: Kế hoạch giao dịch trên được tổng hợp từ thuật toán định lượng và dữ liệu thị trường hiện hành, nhà đầu tư tự quản trị rủi ro đối với quyết định giải ngân.*"
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
                            result_text = search_internet(query)
                            
                        elif tool_call.name == "get_live_stock_data":
                            ticker = tool_call.args.get("ticker", "")
                            result_text = get_live_stock_data(ticker)
                            
                        elif tool_call.name == "draw_technical_chart":
                            ticker = tool_call.args.get("ticker", "").strip().upper()
                            try:
                                import yfinance as yf
                                yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
                                stock = yf.Ticker(yf_ticker)
                                hist_data = stock.history(period="6mo")
                                if not hist_data.empty:
                                    chart_df = hist_data[['Close']].copy()
                                    chart_df.rename(columns={'Close': f'Giá {ticker}'}, inplace=True)
                                    chart_df.index = chart_df.index.tz_localize(None) 
                                    chart_data_to_save = chart_df
                                    result_text = "[SYSTEM] Đã nhận được mảng dữ liệu. Hãy trả lời người dùng."
                                else:
                                    result_text = f"[SYSTEM CẢNH BÁO] Không tìm thấy lịch sử giá {ticker}."
                            except Exception as chart_err:
                                result_text = f"[SYSTEM FAULT] Lỗi: {chart_err}"
                                
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
            
                if chart_data_to_save is None and ("đồ thị" in prompt.lower() or "biểu đồ" in prompt.lower() or "chart" in prompt.lower()):
                    match = re.search(r'\b[A-Z]{3}\b', prompt.upper())
                    fallback_ticker = match.group(0) if match else (rpg_ticker if rpg_ticker else None)
                    
                    if fallback_ticker:
                        import yfinance as yf
                        try:
                            yf_ticker = f"{fallback_ticker}.VN" if not fallback_ticker.endswith(".VN") else fallback_ticker
                            stock = yf.Ticker(yf_ticker)
                            hist_data = stock.history(period="6mo")
                            if not hist_data.empty:
                                chart_df = hist_data[['Close']].copy()
                                chart_df.rename(columns={'Close': f'Giá {fallback_ticker}'}, inplace=True)
                                chart_df.index = chart_df.index.tz_localize(None)
                                chart_data_to_save = chart_df
                        except:
                            pass

            except Exception as e:
                st.error(f"SYSTEM FAULT: {e}")
                response = None

        if response:
            st.markdown(response.text)
            
            col_btn1, col_btn2, _ = st.columns([1.5, 2.5, 6])
            with col_btn1:
                components.html(render_copy_button(response.text), height=35)
            with col_btn2:
                ticker_match = re.search(r'\b[A-Z]{3}\b', response.text)
                ticker_name = ticker_match.group(0) if ticker_match else "STOCK"
                components.html(render_pdf_button(response.text, ticker_name, dict_dfs), height=35)
            
            if chart_data_to_save is not None:
                st.line_chart(chart_data_to_save)
                
            new_msg = {"role": "assistant", "content": response.text}
            if chart_data_to_save is not None:
                new_msg["chart"] = chart_data_to_save
            st.session_state.messages.append(new_msg)
