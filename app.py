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
    """Hàm vẽ đồ thị nến Nhật + Khối lượng (2 tầng), CĂNG NGANG."""
    import yfinance as yf
    try:
        yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
        stock = yf.Ticker(yf_ticker)
        
        # Lấy 60 ngày để tính MA chuẩn, sau đó cắt lấy 35 nến gần nhất để hiển thị
        full_hist = stock.history(period="60d")
        if full_hist.empty:
            return ""
            
        full_hist['SMA20'] = full_hist['Close'].rolling(window=20).mean()
        full_hist['Vol_SMA20'] = full_hist['Volume'].rolling(window=20).mean()
        
        hist = full_hist.tail(35)

        tenkan_val, kijun_val = None, None
        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta_data = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            tenkan_val = float(ta_data.get('Tenkan_sen', 0))
            kijun_val = float(ta_data.get('Kijun_sen', 0))

        # Tăng figsize, chia 2 trục: Trục giá (ax1) và Trục Volume (ax2)
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(2, 1, gridspec_kw={'height_ratios': [3, 1]}, figsize=(12, 6.5), dpi=200)
        fig.patch.set_facecolor('#0B0F17')
        ax1.set_facecolor('#0B0F17')
        ax2.set_facecolor('#0B0F17')

        x_indices = range(len(hist))
        
        # Vẽ nến và Volume
        for i in x_indices:
            row = hist.iloc[i]
            color = '#10B981' if row['Close'] >= row['Open'] else '#EF4444'
            
            # Ax1: Nến giá
            ax1.plot([i, i], [row['Low'], row['High']], color=color, linewidth=1.5)
            body_bottom = min(row['Open'], row['Close'])
            body_top = max(row['Open'], row['Close'])
            body_height = max(body_top - body_bottom, 0.001)
            ax1.add_patch(plt.Rectangle((i - 0.4, body_bottom), 0.8, body_height, facecolor=color, edgecolor=color))
            
            # Ax2: Khối lượng
            ax2.add_patch(plt.Rectangle((i - 0.4, 0), 0.8, row['Volume'], facecolor=color, alpha=0.8))

        # Ax1: Vẽ các đường chỉ báo kỹ thuật
        current_price = hist['Close'].iloc[-1]
        ax1.axhline(y=current_price, color='#0A84FF', linestyle='-', linewidth=1.5, alpha=0.8, label=f'Giá hiện tại: {current_price:,.0f}')
        ax1.plot(x_indices, hist['SMA20'], color='#A855F7', linewidth=1.5, label='SMA 20 (Xu hướng giá)')
        
        if tenkan_val and tenkan_val > 0:
            ax1.axhline(y=tenkan_val, color='#F59E0B', linestyle='--', linewidth=1.2, alpha=0.8, label=f'Tenkan-sen: {tenkan_val:,.0f}')
        if kijun_val and kijun_val > 0:
            ax1.axhline(y=kijun_val, color='#EF4444', linestyle='-.', linewidth=1.2, alpha=0.8, label=f'Kijun-sen (Cắt lỗ): {kijun_val:,.0f}')

        # Ax2: Vẽ đường trung bình khối lượng
        ax2.plot(x_indices, hist['Vol_SMA20'], color='#F8FAFC', linestyle='--', linewidth=1.5, label='Trung bình KL (20 Phiên)')

        # Tinh chỉnh Ax1 (Giá)
        ax1.set_title(f"BIỂU ĐỒ HÀNH VI GIÁ VÀ DÒNG TIỀN (35 PHIÊN) - {ticker}", color='white', pad=15, fontsize=13, fontweight='bold', fontfamily='sans-serif')
        ax1.legend(loc='upper left', fontsize=9, facecolor='#1C2635', edgecolor='none')
        ax1.grid(True, color='white', alpha=0.05)
        ax1.set_xticks([]) # Ẩn trục X của ax1 để nhường cho ax2
        ax1.tick_params(axis='y', colors='#94A3B8', labelsize=9)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['left'].set_color('#333333')
        ax1.spines['bottom'].set_visible(False)

        # Tinh chỉnh Ax2 (Volume)
        ax2.legend(loc='upper left', fontsize=9, facecolor='#1C2635', edgecolor='none')
        ax2.grid(True, color='white', alpha=0.05)
        ax2.set_xticks(x_indices[::3])
        ax2.set_xticklabels([hist.index[i].strftime('%d/%m') for i in x_indices[::3]], rotation=0, color='#94A3B8', fontsize=9)
        ax2.tick_params(axis='y', colors='#94A3B8', labelsize=9)
        # Ẩn nhãn trục Y của Volume cho gọn
        ax2.set_yticklabels([])
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_color('#333333')
        ax2.spines['bottom'].set_color('#333333')
        
        plt.tight_layout()
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
    current_time = datetime.now().strftime("%d/%m/%Y")
    
    html_content = ai_content
    html_content = re.sub(r'### (.*?)\n', r'<h3 style="color:#0078D4; font-size: 16px; margin-top: 25px; margin-bottom: 10px; border-bottom: 1px dashed #ddd; padding-bottom: 5px;">\1</h3>', html_content)
    html_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html_content)
    html_content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html_content)
    html_content = html_content.replace('\n', '<br>')
    
    df_rs = dict_dfs.get("RS_DATA", pd.DataFrame()) if dict_dfs else pd.DataFrame()
    df_ta = dict_dfs.get("TA_DATA", pd.DataFrame()) if dict_dfs else pd.DataFrame()
    
    stock_rs = df_rs[df_rs['Mã CK'] == ticker_name].iloc[0].to_dict() if not df_rs.empty and ticker_name in df_rs['Mã CK'].values else {}
    stock_ta = df_ta[df_ta['Mã CK'] == ticker_name].iloc[0].to_dict() if not df_ta.empty and ticker_name in df_ta['Mã CK'].values else {}
    industry = stock_rs.get('Ngành', '')

    def format_num(val, is_percent=False, is_vol=False):
        try:
            if pd.isna(val): return "N/A"
            v = float(val)
            if is_vol: return f"{v:,.0f}"
            res = f"{v:.2f}".replace('.', ',')
            return f"{res}%" if is_percent else res
        except:
            return str(val)

    gia_ht = format_num(stock_rs.get('Giá', 'N/A'))
    pe = format_num(stock_rs.get('P/E', 'N/A'))
    pb = format_num(stock_rs.get('P/B', 'N/A'))
    roe = format_num(stock_rs.get('ROE (%)', 'N/A'), is_percent=True)
    debt = format_num(stock_rs.get('Nợ/Vốn Chủ', 'N/A'))
    rs_1m = format_num(stock_rs.get('RS_1M', 'N/A'))
    mfi = format_num(stock_rs.get('MFI_14', 'N/A'))
    kl_20 = format_num(stock_rs.get('KL_TB_20', 'N/A'), is_vol=True)
    cloud_status = str(stock_ta.get('Trạng Thái Mây', 'N/A'))
    kumo_signal = str(stock_ta.get('Tín Hiệu Kumo', 'N/A'))
    
    peer_html = ""
    if industry and not df_rs.empty:
        peers_df = df_rs[(df_rs['Ngành'] == industry) & (df_rs['Mã CK'] != ticker_name)].sort_values(by='RS_1M', ascending=False).head(3)
        if not peers_df.empty:
            peer_rows = f"<tr style='background-color: #EBF5FF;'><td style='font-weight: bold; padding: 8px;'>{ticker_name}</td><td style='font-weight: bold;'>{pe}</td><td style='font-weight: bold;'>{pb}</td><td style='font-weight: bold;'>{roe}</td><td style='font-weight: bold; color: #0078D4;'>{rs_1m}</td></tr>"
            
            for _, row in peers_df.iterrows():
                p_ticker = row.get('Mã CK', 'N/A')
                p_pe = format_num(row.get('P/E', 'N/A'))
                p_pb = format_num(row.get('P/B', 'N/A'))
                p_roe = format_num(row.get('ROE (%)', 'N/A'), is_percent=True)
                p_rs = format_num(row.get('RS_1M', 'N/A'))
                peer_rows += f"<tr style='border-bottom: 1px solid #E2E8F0;'><td style='padding: 8px;'>{p_ticker}</td><td>{p_pe}</td><td>{p_pb}</td><td>{p_roe}</td><td>{p_rs}</td></tr>"
            
            peer_html = f"""
            <div class="avoid-break" style="margin-top: 35px; margin-bottom: 15px;">
                <div style="font-size: 15px; font-weight: 700; color: #0078D4; margin-bottom: 10px;">SO SÁNH CÙNG NGÀNH ({industry.upper()})</div>
                <table style="width: 100%; font-size: 13px; border-collapse: collapse; text-align: center; border: 1px solid #E2E8F0;">
                    <tr style="background-color: #0078D4; color: white;">
                        <th style="padding: 10px;">Mã CK</th>
                        <th style="padding: 10px;">P/E</th>
                        <th style="padding: 10px;">P/B</th>
                        <th style="padding: 10px;">ROE</th>
                        <th style="padding: 10px;">RS 1M</th>
                    </tr>
                    {peer_rows}
                </table>
            </div>
            """

    chart_base64 = generate_chart_base64(ticker_name, df_ta)
    chart_html = f'<div class="avoid-break" style="margin-top: 40px; text-align: center; position: relative; z-index: 2;"><img src="{chart_base64}" style="width: 100%; border: 1px solid #E2E8F0; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);"></div>' if chart_base64 else ""
    
    svg_watermark = f"<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><text x='50%' y='50%' font-size='40' fill='%230078D4' fill-opacity='0.03' font-family='Arial' font-weight='bold' text-anchor='middle' transform='rotate(-45 200 200)'>LINANCE.CORE</text></svg>"
    b64_watermark = base64.b64encode(svg_watermark.encode('utf-8')).decode('utf-8')
    bg_style = f"background-image: url('data:image/svg+xml;base64,{b64_watermark}'); background-repeat: repeat;"

    raw_report_html = f"""
    <link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,700;1,400&subset=vietnamese&display=swap" rel="stylesheet">
    <style>
        .avoid-break {{
            page-break-inside: avoid !important;
            break-inside: avoid !important;
            -webkit-column-break-inside: avoid !important;
            display: block;
        }}
    </style>
    <div style="font-family: 'Roboto', sans-serif; padding: 0; color: #333; line-height: 1.6; background-color: white; max-width: 1000px; margin: 0 auto; box-sizing: border-box; {bg_style}">
        
        <div style="background-color: #0078D4; color: white; padding: 40px; display: flex; justify-content: space-between; align-items: center; position: relative; z-index: 2;">
            <div>
                <div style="font-size: 14px; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 5px;">BÁO CÁO CẬP NHẬT ĐỊNH LƯỢNG</div>
                <div style="font-size: 38px; font-weight: 900; letter-spacing: 1px;">MÃ CỔ PHIẾU: {ticker_name}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 26px; font-weight: 900;">LINANCE<span style="color: #93C5FD;">.CORE</span></div>
                <div style="font-size: 13px; margin-top: 5px;">Ngày {current_time}</div>
            </div>
        </div>
        
        <div style="padding: 40px; padding-bottom: 0; position: relative; z-index: 2;">
            <div style="display: flex; gap: 50px;">
                
                <div style="flex: 0 0 35%;">
                    <div style="font-size: 24px; font-weight: 900; color: #0078D4; margin-bottom: 5px;">THỐNG KÊ TÀI CHÍNH</div>
                    <div style="height: 3px; background-color: #0078D4; width: 100%; margin-bottom: 20px;"></div>
                    
                    <table style="width: 100%; font-size: 13px; border-collapse: collapse; background: rgba(255,255,255,0.8);">
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Giá hiện tại</td><td style="text-align:right; font-weight: bold; font-size: 15px;">{gia_ht}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">P/E định giá</td><td style="text-align:right; font-weight: bold;">{pe}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">P/B</td><td style="text-align:right; font-weight: bold;">{pb}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">ROE</td><td style="text-align:right; font-weight: bold;">{roe}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Nợ / Vốn chủ</td><td style="text-align:right; font-weight: bold;">{debt}</td></tr>
                        <tr><td colspan="2" style="padding: 15px 0 5px 0; font-weight: bold; color: #0078D4; font-size: 14px;">Chỉ Báo Kỹ Thuật & Dòng Tiền</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Khối lượng TB (20 phiên)</td><td style="text-align:right; font-weight: bold;">{kl_20}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Sức mạnh giá (RS_1M)</td><td style="text-align:right; font-weight: bold;">{rs_1m}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Dòng tiền (MFI)</td><td style="text-align:right; font-weight: bold;">{mfi}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Trạng thái Ichimoku</td><td style="text-align:right; font-weight: bold; color: #EF4444;">{cloud_status}</td></tr>
                        <tr style="border-bottom: 1px solid #E2E8F0;"><td style="padding: 10px 0; color: #475569;">Tín hiệu Kumo</td><td style="text-align:right; font-weight: bold; color: #0078D4;">{kumo_signal}</td></tr>
                    </table>
                </div>
                
                <div style="flex: 1;">
                    <div style="font-size: 24px; font-weight: 900; color: #0078D4; margin-bottom: 5px;">KẾ HOẠCH GIAO DỊCH</div>
                    <div style="height: 3px; background-color: #0078D4; width: 100%; margin-bottom: 20px;"></div>
                    
                    <div style="font-size: 14px; text-align: justify; line-height: 1.7; color: #1E293B;">
                        {html_content}
                    </div>
                    
                    {peer_html}
                </div>
            </div>
            
            {chart_html}
            
        </div>
        
        <div class="avoid-break" style="margin: 40px 40px 20px 40px; background: rgba(255,255,255,0.9); position: relative; z-index: 2;">
            <div style="padding-top: 20px; border-top: 2px solid #0078D4; display: flex; justify-content: space-between; align-items: flex-start;">
                <div style="font-size: 13px; color: #1E293B; line-height: 1.5;">
                    <b style="color: #0078D4; font-size: 15px;">Nguyễn Đào Thăng Long</b><br>
                    Chuyên viên phân tích định lượng (Quantitative Analyst - Quant)<br>
                    <b>Trung tâm phân tích định lượng LINANCE</b>
                </div>
                <div style="font-size: 11px; color: #94A3B8; text-align: right; font-style: italic; max-width: 450px; line-height: 1.4;">
                    CONFIDENTIAL REPORT. Generated by LINANCE Quantitative AI System.<br>
                    Disclaimer: Báo cáo được tạo tự động bởi thuật toán định lượng dựa trên dữ liệu hiện hành. Nhà đầu tư tự chịu trách nhiệm và quản trị rủi ro đối với quyết định giải ngân.
                </div>
            </div>
        </div>
    </div>
    """
    
    b64_html = base64.b64encode(raw_report_html.encode('utf-8')).decode('utf-8')
    file_name = f"LINANCE_{ticker_name}_{datetime.now().strftime('%d%m%Y_%H%M')}.pdf"
    
    button_code = f"""
    <body style="margin: 0; padding: 0; overflow: hidden; background-color: transparent;">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <style>
        .pdf-btn {{ background-color: transparent; color: #10B981; border: 1px solid rgba(16, 185, 129, 0.5); border-radius: 6px; padding: 6px 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: bold; cursor: pointer; transition: all 0.3s ease; display: inline-flex; align-items: center; justify-content: center; }}
        .pdf-btn:hover {{ background-color: #10B981; color: #FFFFFF; box-shadow: 0 0 10px rgba(16, 185, 129, 0.4); border: 1px solid #10B981; }}
        </style>
        <button class="pdf-btn" id="dlPdfBtn" onclick="exportPDF()">EXPORT PDF</button>
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
              margin:       [0.4, 0, 0.4, 0],
              filename:     '{file_name}',
              image:        {{ type: 'jpeg', quality: 0.98 }},
              html2canvas:  {{ scale: 2, useCORS: true }},
              jsPDF:        {{ unit: 'in', format: 'a4', orientation: 'portrait' }},
              pagebreak:    {{ mode: ['css', 'legacy'] }}
            }};
            
            setTimeout(() => {{
                html2pdf().set(opt).from(tempDiv).save().then(function() {{
                    document.getElementById("dlPdfBtn").innerText = "✅ DOWNLOADED!";
                    setTimeout(() => document.getElementById("dlPdfBtn").innerText = "EXPORT PDF", 3000);
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
def calculate_trade_plan(ticker: str, df_ta: pd.DataFrame, nav: float = None,
                          risk_pct: float = None, rr_target: float = 2.0) -> dict:
    """
    TÍNH TOÁN THỰC (deterministic) vùng mua / cắt lỗ / chốt lời / khối lượng.
    AI KHÔNG được tự suy diễn các con số này — chỉ được phép diễn giải kết quả.
    """
    import yfinance as yf

    result = {"valid": False, "reason": "", "ticker": ticker}
    try:
        yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="90d")
        if hist.empty or len(hist) < 20:
            result["reason"] = "Không đủ dữ liệu giá lịch sử để tính toán."
            return result

        try:
            current_price = float(stock.fast_info['lastPrice'])
            if current_price < 1000:
                current_price *= 1000
        except Exception:
            current_price = float(hist['Close'].iloc[-1])

        # --- ATR(14): đo biến động thực để đặt Stop-loss theo rủi ro thật của từng mã ---
        high_low = hist['High'] - hist['Low']
        high_close = (hist['High'] - hist['Close'].shift()).abs()
        low_close = (hist['Low'] - hist['Close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr14 = true_range.rolling(14).mean().iloc[-1]

        if pd.isna(atr14) or atr14 <= 0:
            result["reason"] = "Không tính được ATR (biến động) cho mã này."
            return result

        # --- Kijun-sen / Tenkan-sen từ TA_DATA (nếu có) ---
        kijun_val = None
        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta_row = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            try:
                kijun_val = float(ta_row.get('Kijun_sen', 0)) or None
            except Exception:
                pass

        # --- VÙNG MUA: quanh giá hiện tại, biên độ theo ATR ---
        entry_low = current_price - 0.5 * atr14
        entry_high = current_price + 0.3 * atr14

        # --- STOP-LOSS: ưu tiên Kijun-sen nếu hợp lý (≤3 ATR dưới giá), nếu không dùng ATR-stop ---
        atr_based_stop = current_price - 1.5 * atr14
        if kijun_val and 0 < kijun_val < current_price and (current_price - kijun_val) <= 3 * atr14:
            stop_loss = min(kijun_val, entry_low) - 0.1 * atr14
            stop_reason = f"Dưới Kijun-sen ({kijun_val:,.0f}), đệm 0.1 ATR"
        else:
            stop_loss = atr_based_stop
            stop_reason = "Kijun-sen không hợp lệ/quá xa → dùng Stop theo ATR (1.5x)"

        risk_per_share = entry_low - stop_loss
        if risk_per_share <= 0:
            result["reason"] = "Thiết lập không hợp lệ: Stop-loss cao hơn/bằng vùng mua."
            return result

        take_profit = entry_low + risk_per_share * rr_target
        actual_rr = round((take_profit - entry_low) / risk_per_share, 2)

        result.update({
            "valid": True,
            "current_price": round(current_price, 0),
            "atr14": round(atr14, 0),
            "entry_low": round(entry_low, 0),
            "entry_high": round(entry_high, 0),
            "stop_loss": round(stop_loss, 0),
            "stop_reason": stop_reason,
            "take_profit": round(take_profit, 0),
            "risk_per_share": round(risk_per_share, 0),
            "rr_ratio": actual_rr,
        })

        if nav and risk_pct and nav > 0 and risk_pct > 0:
            risk_amount = nav * (risk_pct / 100)
            max_shares = int((risk_amount / risk_per_share) // 100) * 100  # làm tròn xuống lô 100 (HOSE)
            position_value = max_shares * entry_low
            result.update({
                "nav": nav, "risk_pct": risk_pct,
                "risk_amount": round(risk_amount, 0),
                "max_shares": max_shares,
                "position_value": round(position_value, 0),
                "position_pct_of_nav": round((position_value / nav) * 100, 1),
            })
        return result
    except Exception as e:
        result["reason"] = f"Lỗi hệ thống khi tính toán: {e}"
        return result


def format_trade_plan_facts(plan: dict) -> str:
    if not plan.get("valid"):
        return (f"[SYSTEM_FACTS - THIẾT LẬP GIAO DỊCH {plan.get('ticker','')}]\n"
                f"KHÔNG ĐỦ ĐIỀU KIỆN TÍNH TOÁN: {plan.get('reason')}\n"
                f"=> AI BẮT BUỘC trả lời rằng CHƯA ĐỦ CƠ SỞ để đưa kế hoạch giao dịch cụ thể "
                f"(được phép đứng ngoài), TUYỆT ĐỐI không tự bịa vùng mua/stop/TP.\n")

    lines = [
        f"[SYSTEM_FACTS - THIẾT LẬP GIAO DỊCH ĐÃ TÍNH SẴN CHO {plan['ticker']} (dùng ATR14 + Kijun-sen)]",
        f"Giá hiện tại: {plan['current_price']:,.0f}",
        f"ATR(14) - biến động trung bình: {plan['atr14']:,.0f}",
        f"VÙNG MUA (Entry): {plan['entry_low']:,.0f} - {plan['entry_high']:,.0f}",
        f"CẮT LỖ CỨNG (Stop-loss): {plan['stop_loss']:,.0f}  [Lý do: {plan['stop_reason']}]",
        f"CHỐT LỜI (Take-profit): {plan['take_profit']:,.0f}",
        f"Rủi ro/cổ phiếu: {plan['risk_per_share']:,.0f} | Tỷ lệ R:R thực tế: {plan['rr_ratio']}",
    ]
    if "max_shares" in plan:
        lines += [
            f"NAV: {plan['nav']:,.0f} | Rủi ro chấp nhận: {plan['risk_pct']}% ({plan['risk_amount']:,.0f} VNĐ)",
            f"KHỐI LƯỢNG TỐI ĐA ĐƯỢC MUA: {plan['max_shares']:,} CP (đã làm tròn lô 100)",
            f"Giá trị vị thế: {plan['position_value']:,.0f} VNĐ (~{plan['position_pct_of_nav']}% NAV)",
        ]
    lines.append("=> AI CHỈ ĐƯỢC DÙNG ĐÚNG CÁC CON SỐ TRÊN. TUYỆT ĐỐI KHÔNG TỰ TÍNH LẠI HAY SUY DIỄN SỐ KHÁC.")
    return "\n".join(lines)

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
    st.markdown("### QUẢN TRỊ VỐN")
    nav_input = st.number_input("Tổng vốn (NAV, VNĐ):", min_value=0, value=0, step=10_000_000, format="%d")
    risk_input = st.slider("Mức rủi ro chấp nhận / lệnh (%):", 0.5, 5.0, 2.0, step=0.5)
    rr_input = st.slider("Tỷ lệ R:R mục tiêu:", 1.0, 4.0, 2.0, step=0.5)

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
    st.session_state.messages = [{"role": "assistant", "content": "LINANCE CORE ONLINE. . ."}]

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
                ticker_match = re.search(r'\b[A-Z0-9]{3,4}\b', message["content"])
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

                # --- Tính sẵn Kế hoạch giao dịch bằng Python (không để AI tự suy diễn) ---
                trade_plan_facts = ""
                ticker_detect = re.search(r'\b[A-Z]{3}\b', prompt.upper())
                if ticker_detect:
                    df_ta_ref = dict_dfs.get("TA_DATA", pd.DataFrame())
                    plan = calculate_trade_plan(
                        ticker_detect.group(0),
                        df_ta_ref,
                        nav=nav_input if nav_input > 0 else None,
                        risk_pct=risk_input,
                        rr_target=rr_input,
                    )
                    trade_plan_facts = format_trade_plan_facts(plan)
                client = genai.Client(api_key=API_KEY)
                
                sys_prompt = """
                Bạn là Bậc thầy Phân tích Định lượng và Cố vấn Giao dịch cấp tổ chức tại LINANCE Terminal.
                MỤC TIÊU CỐT LÕI: Đưa ra Kế hoạch Giao dịch (Actionable Trading Plan) quyết đoán. Tuyệt đối không nhận định nước đôi.

                NGUYÊN TẮC HOẠT ĐỘNG:
                1. ĐỘT BIẾN KHỐI LƯỢNG LÀ TÍN HIỆU CỐT LÕI: Luôn kiểm tra sự đột biến khối lượng (Đột_Biến_KL hoặc dữ liệu Real-time).
                2. PHÂN TÍCH KỸ THUẬT & ICHIMOKU: Bắt buộc đối chiếu sự đồng thuận của hệ thống Ichimoku từ bảng TA_DATA để củng cố luận điểm.
                3. NGUỒN SỐ LIỆU DUY NHẤT CHO KẾ HOẠCH GIAO DỊCH: Toàn bộ VÙNG MUA, CẮT LỖ, CHỐT LỜI, R:R, KHỐI LƯỢNG được cung cấp sẵn trong khối [SYSTEM_FACTS] ở đầu ngữ cảnh. TUYỆT ĐỐI KHÔNG được tự tính toán lại, làm tròn khác, hay suy diễn con số khác — chỉ được trích dẫn nguyên văn và giải thích ý nghĩa kỹ thuật của chúng. Nếu SYSTEM_FACTS báo "KHÔNG ĐỦ ĐIỀU KIỆN", BẮT BUỘC trả lời rằng chưa đủ cơ sở để giải ngân — được phép đứng ngoài thị trường, không ép quyết đoán khi thiết lập không hợp lệ.
                4. KẾ HOẠCH GIAO DỊCH: BẮT BUỘC trình bày theo cấu trúc: 
                   - LUẬN ĐIỂM ĐẦU TƯ: Sự hội tụ giữa Dòng tiền, Kỹ thuật và Cơ bản.
                   - VÙNG MUA (Entry Range): Lấy nguyên số liệu từ SYSTEM_FACTS.
                   - ĐIỂM CẮT LỖ CỨNG (Stop-loss): Có giải thích lý do kỹ thuật rõ ràng.
                   - ĐIỂM CHỐT LỜI (Take-profit): Vùng giá mục tiêu kỳ vọng.
                   - TỶ TRỌNG ĐI TIỀN: (Chỉ hiện ra nếu có dữ liệu NAV và Rủi ro).
                   - TỶ LỆ R:R: Tính toán rủi ro/lợi nhuận thực tế.
                5. KIỂM CHỨNG REAL-TIME: Luôn gọi `get_live_stock_data` để cập nhật giá.
                6. VĂN PHONG VÀ TRÌNH BÀY: Chuyên nghiệp, lạnh lùng, định lượng. Tuyệt đối KHÔNG dùng emoji.
                7. MIỄN TRỪ TRÁCH NHIỆM: Ở cuối câu trả lời luôn chèn: "*Miễn trừ trách nhiệm: Kế hoạch giao dịch trên được tổng hợp từ thuật toán định lượng và dữ liệu thị trường hiện hành, nhà đầu tư tự quản trị rủi ro đối với quyết định giải ngân.*"
                """
                
                full_prompt = f"{sys_prompt}\n\n{trade_plan_facts}\n\nKHO DỮ LIỆU NỘI BỘ:\n{data_context}\n\nTRUY VẤN: {prompt}"
                
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
                ticker_match = re.search(r'\b[A-Z0-9]{3,4}\b', response.text)
                ticker_name = ticker_match.group(0) if ticker_match else "STOCK"
                components.html(render_pdf_button(response.text, ticker_name, dict_dfs), height=35)
            
            if chart_data_to_save is not None:
                st.line_chart(chart_data_to_save)
                
            new_msg = {"role": "assistant", "content": response.text}
            if chart_data_to_save is not None:
                new_msg["chart"] = chart_data_to_save
            st.session_state.messages.append(new_msg)
