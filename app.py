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
import time

# ==========================================
# CẤU HÌNH GIAO DIỆN CHÍNH
# ==========================================
st.set_page_config(page_title="LINANCE TERMINAL", page_icon="CORE", layout="centered")

# ==========================================
# 1. LÕI KỸ THUẬT: VẼ ĐỒ THỊ NẾN & MÃ HÓA BASE64
# ==========================================
def generate_chart_base64(ticker: str, df_ta: pd.DataFrame):
    """Hàm vẽ đồ thị nến Nhật + Khối lượng (2 tầng), CĂNG NGANG."""
    try:
        # Dùng chung cache/retry với calculate_trade_plan (period 90d ⊇ 60d cần cho MA20)
        # để tránh gọi Yahoo Finance thêm lần nữa cho cùng mã trong 90s.
        full_hist, _ = _fetch_ohlc_with_retry(ticker)
        if full_hist is None or full_hist.empty:
            return ""
        full_hist = full_hist.copy()

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
        ax1.set_xticks([])  # Ẩn trục X của ax1 để nhường cho ax2
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
    except Exception:
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


def render_price_range_svg(plan: dict) -> str:
    """Vẽ thanh SVG trực quan: Stop-loss --- Entry --- Giá hiện tại --- Take-profit."""
    if not plan or not plan.get("valid"):
        return ""
    try:
        sl = plan["stop_loss"]
        el = plan["entry_low"]
        eh = plan["entry_high"]
        tp = plan["take_profit"]
        cp = plan["current_price"]

        lo = min(sl, el, cp) * 0.98
        hi = max(tp, cp) * 1.02
        span = hi - lo if (hi - lo) != 0 else 1

        def x(v):
            return 40 + ((v - lo) / span) * 720  # width canvas 800, margin 40

        entry_x1, entry_x2 = x(el), x(eh)
        sl_x, tp_x, cp_x = x(sl), x(tp), x(cp)

        svg = f"""
        <svg width="100%" viewBox="0 0 800 130" xmlns="http://www.w3.org/2000/svg" style="font-family:'Roboto',sans-serif;">
            <line x1="40" y1="65" x2="760" y2="65" stroke="#CBD5E1" stroke-width="3" stroke-linecap="round"/>
            <rect x="{entry_x1:.1f}" y="58" width="{max(entry_x2 - entry_x1, 4):.1f}" height="14" rx="4" fill="#0078D4" opacity="0.85"/>
            <line x1="{sl_x:.1f}" y1="45" x2="{sl_x:.1f}" y2="85" stroke="#EF4444" stroke-width="4"/>
            <line x1="{tp_x:.1f}" y1="45" x2="{tp_x:.1f}" y2="85" stroke="#10B981" stroke-width="4"/>
            <circle cx="{cp_x:.1f}" cy="65" r="6" fill="#1E293B" stroke="white" stroke-width="2"/>

            <text x="{sl_x:.1f}" y="105" text-anchor="middle" font-size="13" fill="#EF4444" font-weight="700">CẮT LỖ</text>
            <text x="{sl_x:.1f}" y="122" text-anchor="middle" font-size="13" fill="#EF4444">{sl:,.0f}</text>

            <text x="{(entry_x1 + entry_x2) / 2:.1f}" y="30" text-anchor="middle" font-size="13" fill="#0078D4" font-weight="700">VÙNG MUA</text>
            <text x="{(entry_x1 + entry_x2) / 2:.1f}" y="105" text-anchor="middle" font-size="12" fill="#0078D4">{el:,.0f}-{eh:,.0f}</text>

            <text x="{tp_x:.1f}" y="105" text-anchor="middle" font-size="13" fill="#10B981" font-weight="700">CHỐT LỜI</text>
            <text x="{tp_x:.1f}" y="122" text-anchor="middle" font-size="13" fill="#10B981">{tp:,.0f}</text>

            <text x="{cp_x:.1f}" y="30" text-anchor="middle" font-size="12" fill="#1E293B" font-weight="700">GIÁ HIỆN TẠI: {cp:,.0f}</text>
        </svg>
        """
        return svg
    except Exception:
        return ""


def render_trade_plan_card_html(plan: dict) -> str:
    if not plan:
        return ""
    if not plan.get("valid"):
        return f"""
        <div class="avoid-break" style="margin: 20px 0; padding: 18px; background: #FEF2F2; border: 1px solid #FCA5A5; border-radius: 10px;">
            <div style="font-weight:700; color:#B91C1C; font-size:14px;">⚠ CHƯA ĐỦ ĐIỀU KIỆN THIẾT LẬP GIAO DỊCH</div>
            <div style="font-size:12px; color:#7F1D1D; margin-top:5px;">{plan.get('reason', '')}</div>
        </div>
        """

    rr = plan['rr_ratio']
    rr_color = "#10B981" if rr >= 2 else ("#F59E0B" if rr >= 1.2 else "#EF4444")
    position_html = ""
    if "max_shares" in plan:
        position_html = f"""
        <tr style="border-top:1px solid #E2E8F0;">
            <td style="padding:8px 0; color:#475569;">Khối lượng tối đa</td>
            <td style="text-align:right; font-weight:700;">{plan['max_shares']:,} CP</td>
        </tr>
        <tr>
            <td style="padding:8px 0; color:#475569;">Giá trị vị thế / % NAV</td>
            <td style="text-align:right; font-weight:700;">{plan['position_value']:,.0f} ({plan['position_pct_of_nav']}%)</td>
        </tr>
        """

    return f"""
    <div class="avoid-break" style="margin: 20px 0; padding: 20px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px;">
        <div style="font-size:15px; font-weight:900; color:#0078D4; margin-bottom:12px;">THIẾT LẬP GIAO DỊCH ĐỊNH LƯỢNG (ATR14 + Ichimoku)</div>
        {render_price_range_svg(plan)}
        <table style="width:100%; font-size:13px; border-collapse:collapse; margin-top:10px;">
            <tr><td style="padding:8px 0; color:#475569;">ATR(14) - Biến động</td><td style="text-align:right; font-weight:700;">{plan['atr14']:,.0f}</td></tr>
            <tr style="border-top:1px solid #E2E8F0;"><td style="padding:8px 0; color:#475569;">Rủi ro / cổ phiếu</td><td style="text-align:right; font-weight:700;">{plan['risk_per_share']:,.0f}</td></tr>
            <tr style="border-top:1px solid #E2E8F0;"><td style="padding:8px 0; color:#475569;">Tỷ lệ R:R</td><td style="text-align:right; font-weight:900; color:{rr_color};">{rr} : 1</td></tr>
            {position_html}
        </table>
    </div>
    """


def render_pdf_button(ai_content, ticker_name, dict_dfs, trade_plan=None):
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

    # --- Xếp hạng Tier + mã báo cáo (Executive badge) ---
    tscore = int(stock_rs.get('Tech_Score', 0)) if stock_rs else 0
    if tscore >= 6:
        tier_label, tier_color = "S-TIER — KHẢ QUAN MẠNH", "#FFD700"
    elif tscore >= 3:
        tier_label, tier_color = "A-TIER — KHẢ QUAN", "#10B981"
    elif tscore >= -2:
        tier_label, tier_color = "B-TIER — TRUNG TÍNH", "#0A84FF"
    else:
        tier_label, tier_color = "C-TIER — TIÊU CỰC", "#EF4444"

    tier_badge_html = f"""
    <div class="avoid-break" style="padding: 14px 40px; background:#0F172A; display:flex; justify-content:space-between; align-items:center;">
        <div style="color:{tier_color}; font-weight:900; font-size:14px; letter-spacing:1px;">XẾP HẠNG ĐỊNH LƯỢNG: {tier_label}</div>
        <div style="color:#94A3B8; font-size:11px;">Tech Score: {tscore} | Mã báo cáo: LC-{ticker_name}-{datetime.now().strftime('%Y%m%d')}</div>
    </div>
    """

    trade_plan_html = render_trade_plan_card_html(trade_plan)

    def format_num(val, is_percent=False, is_vol=False):
        try:
            if pd.isna(val):
                return "N/A"
            v = float(val)
            if is_vol:
                return f"{v:,.0f}"
            res = f"{v:.2f}".replace('.', ',')
            return f"{res}%" if is_percent else res
        except Exception:
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

    svg_watermark = "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><text x='50%' y='50%' font-size='40' fill='%230078D4' fill-opacity='0.03' font-family='Arial' font-weight='bold' text-anchor='middle' transform='rotate(-45 200 200)'>LINANCE.CORE</text></svg>"
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

        {tier_badge_html}

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
                        <tr><td colspan="2" style="padding: 15px 0 5px 0; font-weight: bold; color: #0078D4; font-size: 14px;">Chỉ Báo Kỹ Thuật &amp; Dòng Tiền</td></tr>
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

                    {trade_plan_html}

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
            if pd.isna(val):
                return "N/A"
            v = float(val)
            if v.is_integer():
                return str(int(v))
            return f"{v:.2f}".replace('.', ',')
        except Exception:
            return str(val)

    display_pe = format_vn(data.get('P/E', 'N/A'))
    display_pb = format_vn(data.get('P/B', 'N/A'))
    display_roe = format_vn(data.get('ROE (%)', 'N/A'))

    try:
        current_price = float(data.get('Giá', 0))
        display_price = f"{current_price:,.0f} VNĐ".replace(',', '.')
    except Exception:
        display_price = "N/A"

    atk_score = int(data.get('RS_1M', 50))
    mp_score = int(data.get('MFI_14', 50))
    tech_score = data.get('Tech_Score', 0)

    def_score = 50
    if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
        ta_data = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
        if "TRÊN Mây" in str(ta_data.get('Trạng Thái Mây', '')):
            def_score += 30
        elif "DƯỚI Mây" in str(ta_data.get('Trạng Thái Mây', '')):
            def_score -= 20

    try:
        if float(data.get('ROE (%)', 0)) > 15:
            def_score += 20
    except Exception:
        pass

    int_score = 50
    try:
        pe_f = float(data.get('P/E', 0))
        if 0 < pe_f < 15:
            int_score += 20
        elif pe_f > 25 or pe_f < 0:
            int_score -= 20

        pb_f = float(data.get('P/B', 0))
        if 0 < pb_f < 1.5:
            int_score += 20
        elif pb_f > 3.0:
            int_score -= 20

        debt_f = float(data.get('Nợ/Vốn Chủ', 0))
        if 0 <= debt_f < 1.0:
            int_score += 10
        elif debt_f > 2.0:
            int_score -= 10
    except Exception:
        pass

    atk_score = min(max(atk_score, 0), 100)
    mp_score = min(max(mp_score, 0), 100)
    def_score = min(max(def_score, 0), 100)
    int_score = min(max(int_score, 0), 100)

    if tech_score >= 6:
        tier, t_col = "S-TIER", "#FFD700"
    elif tech_score >= 3:
        tier, t_col = "A-TIER", "#00FF00"
    elif tech_score >= 0:
        tier, t_col = "B-TIER", "#0A84FF"
    else:
        tier, t_col = "C-TIER", "#FF3A3A"

    industry = str(data.get('Ngành', ''))
    if "Ngân hàng" in industry:
        rpg_class = "TANKER (Phòng thủ)"
    elif "Chứng khoán" in industry:
        rpg_class = "ASSASSIN (Đột phá)"
    elif "Công nghệ" in industry:
        rpg_class = "MAGE (Công nghệ)"
    elif "Bất động sản" in industry:
        rpg_class = "BERSERKER (Chu kỳ)"
    else:
        rpg_class = "RANGER (Linh hoạt)"

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
        if not results:
            return "Hệ thống không tìm thấy thông tin phù hợp trên Internet."
        formatted_results = [f"- Tiêu đề: {r['title']}\n  Nội dung: {r['body']}\n  Nguồn: {r['href']}" for r in results]
        return "\n".join(formatted_results)
    except Exception as e:
        return f"SYSTEM ERROR (NETWORK): {e}"


def get_live_stock_data(ticker: str) -> str:
    try:
        ticker = ticker.strip().upper()
        hist, current_price = _fetch_ohlc_with_retry(ticker)

        if hist is None:
            return f"[SYSTEM CẢNH BÁO] Không thể truy xuất dữ liệu realtime cho {ticker} (giới hạn truy vấn hoặc thiếu dữ liệu). Không suy diễn số liệu thay thế."

        vol_20 = hist['Volume'].tail(20)
        current_vol = float(hist['Volume'].iloc[-1])
        avg_vol_20 = float(vol_20.mean())
        surge_ratio = (current_vol / avg_vol_20) * 100 if avg_vol_20 > 0 else 0
        vol_info = f"Khối lượng phiên nay: {current_vol:,.0f} | KL Trung bình 20 phiên: {avg_vol_20:,.0f} | Mức độ đột biến: {surge_ratio:.1f}%"

        return f"[SYSTEM REAL-TIME UPDATE] Mã: {ticker} | Giá: {current_price:,.0f} VNĐ | {vol_info}."
    except Exception as e:
        return f"Hệ thống không thể truy xuất dữ liệu realtime cho {ticker}. Lỗi: {e}"


def draw_technical_chart(ticker: str) -> str:
    return f"[SYSTEM CHART COMMAND TRIGGERED] Hãy xác nhận bằng văn bản rằng đồ thị kỹ thuật mã {ticker} đang được hiển thị ngay bên dưới đoạn hội thoại."


@st.cache_data(ttl=90, show_spinner=False)
def _fetch_ohlc_with_retry(ticker: str, max_retries: int = 3):
    """
    Gọi Yahoo Finance có retry/backoff + cache 90s theo ticker (dùng chung
    cho mọi người dùng trong TTL này, tránh gọi trùng lặp gây rate-limit).
    Trả về (hist_dataframe, current_price) hoặc (None, None) nếu thất bại hẳn.
    """
    import yfinance as yf

    yf_ticker = f"{ticker}.VN" if not ticker.endswith(".VN") else ticker
    last_err = None
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="90d")
            if hist.empty or len(hist) < 20:
                return None, None

            try:
                current_price = float(stock.fast_info['lastPrice'])
                if current_price < 1000:
                    current_price *= 1000
            except Exception:
                current_price = float(hist['Close'].iloc[-1])

            return hist, current_price
        except Exception as e:
            last_err = e
            # Backoff tăng dần: 0.5s, 1s, 2s — chỉ chờ nếu còn lượt retry
            if attempt < max_retries - 1:
                time.sleep(0.5 * (2 ** attempt))
            continue

    return None, None


def calculate_trade_plan(ticker: str, df_rs: pd.DataFrame, df_ta: pd.DataFrame,
                          nav: float = None, risk_pct: float = 2.0,
                          rr_target: float = 2.0) -> dict:
    """
    ENGINE TÍNH TOÁN GIAO DỊCH CHUẨN — v2.0
    ==========================================
    Nguyên tắc:
      1. Xác định xu hướng (UPTREND / SIDEWAY / DOWNTREND) trước khi tính bất cứ thứ gì
      2. Entry = vùng hỗ trợ kỹ thuật thật (Kijun, SMA20, swing low) — KHÔNG được > giá hiện tại
      3. Stop = dưới vùng hỗ trợ + đệm 0.5 ATR (tránh bị quét bởi noise)
      4. Stop phải cách Entry tối thiểu 0.8 ATR (không để stop sát quá gây lỗi nhỏ bị stop)
      5. RR điều chỉnh theo xác suất thắng ước lượng từ Tech_Score + Ichimoku + RS
      6. Position size: giới hạn cứng ≤ 30% NAV để bảo vệ vốn
    """
    result = {"valid": False, "reason": "", "ticker": ticker}
    try:
        # ── 1. LẤY DỮ LIỆU GIÁ ──────────────────────────────────────────────
        hist, current_price = _fetch_ohlc_with_retry(ticker)
        if hist is None or current_price is None:
            result["reason"] = "Không lấy được dữ liệu giá (giới hạn API hoặc mã không hợp lệ). Thử lại sau ít phút."
            return result

        close  = hist['Close']
        high   = hist['High']
        low    = hist['Low']

        # ── 2. ATR(14) ───────────────────────────────────────────────────────
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]

        if pd.isna(atr14) or atr14 <= 0:
            result["reason"] = "Không tính được ATR(14) — thiếu dữ liệu OHLC."
            return result

        # ── 3. CÁC MỨC KỸ THUẬT TỪ PRICE ACTION ────────────────────────────
        sma20  = close.rolling(20).mean().iloc[-1]
        sma50  = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None

        # Swing low / high (10 và 20 phiên) — dùng làm hỗ trợ/kháng cự thực
        swing_low_10  = low.tail(10).min()
        swing_low_20  = low.tail(20).min()
        swing_high_10 = high.tail(10).max()
        swing_high_20 = high.tail(20).max()

        # ── 4. DỮ LIỆU ICHIMOKU TỪ TA_DATA ─────────────────────────────────
        kijun_val    = None
        tenkan_val   = None
        senkou_a_val = None
        senkou_b_val = None
        cloud_status = ""
        kumo_signal  = ""

        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            try: kijun_val    = float(ta.get('Kijun_sen',  0)) or None
            except Exception: pass
            try: tenkan_val   = float(ta.get('Tenkan_sen', 0)) or None
            except Exception: pass
            try: senkou_a_val = float(ta.get('Senkou_A',   0)) or None
            except Exception: pass
            try: senkou_b_val = float(ta.get('Senkou_B',   0)) or None
            except Exception: pass
            cloud_status = str(ta.get('Trạng Thái Mây', ''))
            kumo_signal  = str(ta.get('Tín Hiệu Kumo',  ''))

        # ── 5. DỮ LIỆU CƠ BẢN + ĐIỂM SỐ TỪ RS_DATA ────────────────────────
        tech_score = 0
        rs_1m      = 50
        if df_rs is not None and not df_rs.empty and ticker in df_rs['Mã CK'].values:
            rs = df_rs[df_rs['Mã CK'] == ticker].iloc[0].to_dict()
            try: tech_score = int(rs.get('Tech_Score', 0))
            except Exception: pass
            try: rs_1m = float(rs.get('RS_1M', 50))
            except Exception: pass

        # ── 6. XÁC ĐỊNH XU HƯỚNG (REGIME) ───────────────────────────────────
        above_sma20    = current_price > sma20
        above_sma50    = current_price > sma50 if sma50 else True
        above_kijun    = current_price > kijun_val if kijun_val else True
        above_cloud    = "TRÊN Mây" in cloud_status
        below_cloud    = "DƯỚI Mây" in cloud_status
        bullish_kumo   = "MUA" in kumo_signal

        # Tính điểm xu hướng (0–5)
        trend_points = sum([above_sma20, above_sma50, above_kijun, above_cloud, bullish_kumo])

        if trend_points >= 3:
            regime = "UPTREND"
        elif trend_points <= 1 and below_cloud:
            regime = "DOWNTREND"
        else:
            regime = "SIDEWAY"

        # DOWNTREND rõ → đứng ngoài (không mua theo downtrend)
        if regime == "DOWNTREND" and tech_score < -2:
            result["reason"] = (
                f"Xu hướng DOWNTREND xác nhận (điểm xu hướng: {trend_points}/5, "
                f"Tech_Score: {tech_score}). Chưa đủ điều kiện mở vị thế mua — đứng ngoài thị trường."
            )
            return result

        # ── 7. XÁC SUẤT THẮNG ƯỚC LƯỢNG → ĐIỀU CHỈNH RR ───────────────────
        # Win rate ước lượng dựa trên 3 tín hiệu độc lập:
        # (a) Tech_Score: -8 đến +8  →  normalize về 0–100
        # (b) Vị trí Ichimoku: TRÊN mây = tốt, DƯỚI mây = xấu
        # (c) RS_1M: sức mạnh tương đối so với thị trường (percentile 1–100)
        score_norm   = min(max((tech_score + 8) / 16 * 100, 0), 100)  # 0–100
        ichimoku_pts = 70 if above_cloud else (40 if not below_cloud else 20)
        win_rate_est = round((score_norm * 0.4 + ichimoku_pts * 0.35 + rs_1m * 0.25), 1)

        # Ngưỡng chất lượng kèo và RR tương ứng:
        # Win rate cao (≥65) → kèo chắc, giữ RR thấp hơn (1.5–2.0) để tỷ lệ lệnh thắng cao
        # Win rate trung bình (50–65) → cần RR ≥ 2.0 để expectancy dương
        # Win rate thấp (<50) → cần RR ≥ 2.5 để bù rủi ro, hoặc không mở kèo
        if win_rate_est >= 65:
            rr_min, rr_cap = 1.5, 3.0
            quality_label = "CAO"
        elif win_rate_est >= 50:
            rr_min, rr_cap = 2.0, 3.5
            quality_label = "TRUNG BÌNH"
        else:
            if regime != "UPTREND":
                result["reason"] = (
                    f"Xác suất thắng ước lượng thấp ({win_rate_est:.0f}%) + xu hướng {regime}. "
                    f"Expectancy âm — không mở kèo."
                )
                return result
            rr_min, rr_cap = 2.5, 4.0
            quality_label = "THẤP (cần RR cao bù rủi ro)"

        # RR thực dùng: lấy max(user_input, rr_min), giới hạn bởi rr_cap
        rr_use = round(min(max(rr_target, rr_min), rr_cap), 1)

        # ── 8. VÙNG MUA (ENTRY) — CHỈ ≤ GIÁ HIỆN TẠI ──────────────────────
        # Ưu tiên theo thứ tự: Kijun-sen → SMA20 → Swing low 10 phiên
        # Chỉ dùng mức nào ≤ current_price (không bảo người dùng chờ giá tăng lên mới mua)
        support_candidates = []
        if kijun_val and 0 < kijun_val <= current_price:
            support_candidates.append(("Kijun-sen", kijun_val))
        if sma20 and 0 < sma20 <= current_price:
            support_candidates.append(("SMA20", sma20))
        if swing_low_10 and 0 < swing_low_10 <= current_price:
            support_candidates.append(("Swing Low 10 phiên", swing_low_10))
        if senkou_b_val and 0 < senkou_b_val <= current_price:
            support_candidates.append(("Senkou_B", senkou_b_val))

        if support_candidates:
            # Chọn mức hỗ trợ gần giá nhất (cao nhất trong các ứng viên ≤ giá)
            support_label, support_level = max(support_candidates, key=lambda x: x[1])
            entry_low  = round(support_level * 0.999, 0)   # sát dưới hỗ trợ 0.1%
            entry_high = round(min(support_level * 1.005, current_price), 0)  # max = giá hiện tại
        else:
            # Không có hỗ trợ rõ ràng phía dưới → dùng ATR làm fallback, Entry = giá hiện tại
            support_label  = "ATR fallback (không có hỗ trợ kỹ thuật rõ ràng)"
            support_level  = current_price
            entry_low      = round(current_price - 0.3 * atr14, 0)
            entry_high     = round(current_price, 0)

        # ── 9. STOP-LOSS — DƯỚI HỖ TRỢ + ĐỆM ATR ───────────────────────────
        # Dùng hỗ trợ sâu hơn (swing_low_20 hoặc Senkou_B) làm đáy stop
        deeper_support = None
        if senkou_b_val and 0 < senkou_b_val < support_level:
            deeper_support = senkou_b_val
        elif sma50 and 0 < sma50 < support_level:
            deeper_support = sma50
        elif swing_low_20 and 0 < swing_low_20 < support_level:
            deeper_support = swing_low_20

        raw_stop = deeper_support if deeper_support else support_level
        stop_loss = round(raw_stop - 0.5 * atr14, 0)

        # Đảm bảo khoảng cách Entry→Stop tối thiểu 0.8 ATR (không để stop quá sát)
        min_stop_distance = 0.8 * atr14
        if (entry_low - stop_loss) < min_stop_distance:
            stop_loss = round(entry_low - min_stop_distance, 0)

        risk_per_share = entry_low - stop_loss
        if risk_per_share <= 0:
            result["reason"] = "Không thể thiết lập Stop-loss hợp lệ (risk/share ≤ 0)."
            return result

        stop_reason = f"Dưới {support_label} ({support_level:,.0f}), đệm 0.5 ATR"

        # ── 10. TAKE-PROFIT — TẠI VÙNG KHÁNG CỰ GẦN NHẤT ──────────────────
        tp_by_rr = entry_low + risk_per_share * rr_use

        # Tìm vùng kháng cự phía trên (swing high, Senkou_A) để đặt TP thực tế
        resistance_candidates = []
        if swing_high_10 > current_price:
            resistance_candidates.append(swing_high_10)
        if swing_high_20 > current_price:
            resistance_candidates.append(swing_high_20)
        if senkou_a_val and senkou_a_val > current_price:
            resistance_candidates.append(senkou_a_val)

        if resistance_candidates:
            nearest_resistance = min(resistance_candidates)
            # TP = min(RR-based TP, kháng cự gần nhất) — không đặt TP vượt kháng cự cứng
            take_profit = round(min(tp_by_rr, nearest_resistance * 0.995), 0)
        else:
            take_profit = round(tp_by_rr, 0)

        actual_rr = round((take_profit - entry_low) / risk_per_share, 2)

        # ── 11. POSITION SIZING — GIỚI HẠN CỨNG ≤ 30% NAV ──────────────────
        result.update({
            "valid":           True,
            "ticker":          ticker,
            "regime":          regime,
            "trend_points":    trend_points,
            "win_rate_est":    win_rate_est,
            "quality_label":   quality_label,
            "current_price":   round(current_price, 0),
            "atr14":           round(atr14, 0),
            "support_label":   support_label,
            "support_level":   round(support_level, 0),
            "entry_low":       entry_low,
            "entry_high":      entry_high,
            "stop_loss":       stop_loss,
            "stop_reason":     stop_reason,
            "take_profit":     take_profit,
            "risk_per_share":  round(risk_per_share, 0),
            "rr_ratio":        actual_rr,
            "rr_used":         rr_use,
        })

        if nav and nav > 0 and risk_pct and risk_pct > 0:
            risk_amount  = nav * (risk_pct / 100)
            raw_shares   = risk_amount / risk_per_share
            max_shares   = int(raw_shares // 100) * 100  # làm tròn xuống lô 100

            position_value = max_shares * entry_low
            position_pct   = (position_value / nav) * 100

            # GIỚI HẠN CỨNG: vị thế không được vượt 30% NAV
            # (tránh trường hợp risk/share nhỏ → số CP lớn → vị thế khổng lồ)
            MAX_POSITION_PCT = 30.0
            if position_pct > MAX_POSITION_PCT:
                max_shares     = int((nav * MAX_POSITION_PCT / 100 / entry_low) // 100) * 100
                position_value = max_shares * entry_low
                position_pct   = (position_value / nav) * 100
                size_note      = f"Đã giới hạn về {MAX_POSITION_PCT}% NAV (risk/CP nhỏ → khối lượng lý thuyết vượt giới hạn an toàn)"
            else:
                size_note = f"Rủi ro tối đa {risk_pct}% NAV = {risk_amount:,.0f} VNĐ"

            result.update({
                "nav":                nav,
                "risk_pct":           risk_pct,
                "risk_amount":        round(risk_amount, 0),
                "max_shares":         max_shares,
                "position_value":     round(position_value, 0),
                "position_pct_of_nav": round(position_pct, 1),
                "size_note":          size_note,
            })

        return result

    except Exception as e:
        result["reason"] = f"Lỗi hệ thống: {e}"
        return result


def format_trade_plan_facts(plan: dict) -> str:
    if not plan.get("valid"):
        return (
            f"[SYSTEM_FACTS — {plan.get('ticker', '')}]\n"
            f"KHÔNG ĐỦ ĐIỀU KIỆN MỞ LỆNH: {plan.get('reason')}\n"
            "=> AI BẮT BUỘC trả lời rằng CHƯA ĐỦ CƠ SỞ để giải ngân. "
            "TUYỆT ĐỐI không tự bịa vùng mua/stop/TP thay thế.\n"
        )

    p = plan
    lines = [
        f"[SYSTEM_FACTS — THIẾT LẬP GIAO DỊCH ĐỊNH LƯỢNG: {p['ticker']}]",
        f"",
        f"── XU HƯỚNG & CHẤT LƯỢNG KÈO ──",
        f"Regime thị trường   : {p['regime']} (điểm xu hướng: {p['trend_points']}/5)",
        f"Xác suất thắng ước lượng: {p['win_rate_est']:.0f}%  →  Chất lượng kèo: {p['quality_label']}",
        f"R:R mục tiêu áp dụng: {p['rr_used']} (điều chỉnh theo win rate — KHÔNG dùng R:R khác)",
        f"",
        f"── SỐ LIỆU GIAO DỊCH (AI CHỈ ĐƯỢC DÙNG CÁC CON SỐ NÀY) ──",
        f"Giá hiện tại       : {p['current_price']:,.0f}",
        f"ATR(14) biến động  : {p['atr14']:,.0f}",
        f"Vùng hỗ trợ tham chiếu: {p['support_label']} @ {p['support_level']:,.0f}",
        f"VÙNG MUA (Entry)   : {p['entry_low']:,.0f} — {p['entry_high']:,.0f}",
        f"CẮT LỖ CỨNG (Stop): {p['stop_loss']:,.0f}  [{p['stop_reason']}]",
        f"CHỐT LỜI (TP)      : {p['take_profit']:,.0f}",
        f"Rủi ro / CP        : {p['risk_per_share']:,.0f}  |  R:R thực tế: {p['rr_ratio']}",
    ]

    if "max_shares" in p:
        lines += [
            f"",
            f"── QUẢN TRỊ VỐN ──",
            f"NAV                : {p['nav']:,.0f} VNĐ",
            f"Rủi ro / lệnh      : {p['risk_pct']}% = {p['risk_amount']:,.0f} VNĐ",
            f"Khối lượng mua     : {p['max_shares']:,} CP  (tối đa, lô 100)",
            f"Giá trị vị thế     : {p['position_value']:,.0f} VNĐ  ({p['position_pct_of_nav']}% NAV)",
            f"Ghi chú sizing     : {p['size_note']}",
        ]

    lines += [
        f"",
        f"=> AI BẮT BUỘC: trích dẫn NGUYÊN VĂN các số trên, KHÔNG tự tính lại, "
        f"KHÔNG làm tròn khác. Giải thích Ý NGHĨA KỸ THUẬT của từng mức — tại sao "
        f"entry nằm ở vùng này, tại sao stop dưới mức này, kháng cự nào giới hạn TP."
    ]
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
                components.html(render_pdf_button(message["content"], ticker_name, dict_dfs, message.get("trade_plan")), height=35)

if prompt := st.chat_input("Nhập mã CK hoặc truy vấn..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        chart_data_to_save = None
        plan = None
        ticker_detect = None
        response = None

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
                ticker_detect = re.search(r'\b[A-Z]{3,4}\b', prompt.upper())
                if ticker_detect:
                    df_rs_ref = dict_dfs.get("RS_DATA", pd.DataFrame())
                    df_ta_ref = dict_dfs.get("TA_DATA", pd.DataFrame())
                    plan = calculate_trade_plan(
                        ticker_detect.group(0),
                        df_rs=df_rs_ref,
                        df_ta=df_ta_ref,
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
                   - ĐIỂM CẮT LỖ CỨNG (Stop-loss): Lấy nguyên số liệu từ SYSTEM_FACTS, giải thích ý nghĩa kỹ thuật.
                   - ĐIỂM CHỐT LỜI (Take-profit): Lấy nguyên số liệu từ SYSTEM_FACTS.
                   - TỶ TRỌNG ĐI TIỀN: (Chỉ hiện ra nếu có dữ liệu NAV và Rủi ro trong SYSTEM_FACTS).
                   - TỶ LỆ R:R: Lấy nguyên số liệu từ SYSTEM_FACTS.
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
                        except Exception:
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
                components.html(render_pdf_button(response.text, ticker_name, dict_dfs, plan if ticker_detect else None), height=35)

            if chart_data_to_save is not None:
                st.line_chart(chart_data_to_save)

            new_msg = {"role": "assistant", "content": response.text}
            if chart_data_to_save is not None:
                new_msg["chart"] = chart_data_to_save
            new_msg["trade_plan"] = plan if ticker_detect else None
            st.session_state.messages.append(new_msg)
