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
def generate_chart_base64(ticker: str, df_ta: pd.DataFrame, trade_plan: dict = None):
    """
    Biểu đồ nến 40 phiên nâng cấp:
    - Panel 1 (giá): nến + SMA20 + Ichimoku + vùng Entry/TP/Stop (nếu có trade_plan)
    - Panel 2 (RSI14): vùng quá mua/bán
    - Panel 3 (Volume): KL + MA20
    """
    try:
        full_hist, current_price = _fetch_ohlc_with_retry(ticker)
        if full_hist is None or full_hist.empty:
            return ""
        full_hist = full_hist.copy()

        # --- Tính các chỉ báo ---
        full_hist['SMA20'] = full_hist['Close'].rolling(20).mean()
        full_hist['Vol_SMA20'] = full_hist['Volume'].rolling(20).mean()

        # ATR20 — dùng 20 phiên cho giao dịch ngắn-trung hạn (chuẩn hơn ATR14 cho swing)
        tr = pd.concat([
            full_hist['High'] - full_hist['Low'],
            (full_hist['High'] - full_hist['Close'].shift()).abs(),
            (full_hist['Low']  - full_hist['Close'].shift()).abs()
        ], axis=1).max(axis=1)
        full_hist['ATR20'] = tr.rolling(20).mean()

        # RSI14
        delta = full_hist['Close'].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, 1e-10)
        full_hist['RSI14'] = 100 - 100 / (1 + rs)

        hist = full_hist.tail(40).copy()
        hist = hist.reset_index()
        n = len(hist)

        # --- Ichimoku từ TA_DATA ---
        tenkan_val = kijun_val = None
        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            try: tenkan_val = float(ta.get('Tenkan_sen', 0)) or None
            except Exception: pass
            try: kijun_val  = float(ta.get('Kijun_sen',  0)) or None
            except Exception: pass

        # --- Entry/Stop/TP từ trade_plan (nếu có) ---
        entry_low = stop_loss = take_profit = entry_high = None
        if trade_plan and trade_plan.get('valid'):
            entry_low  = trade_plan.get('entry_low')
            entry_high = trade_plan.get('entry_high')
            stop_loss  = trade_plan.get('stop_loss')
            take_profit= trade_plan.get('take_profit')

        # --- Layout ---
        plt.style.use('dark_background')
        fig, (ax1, ax_rsi, ax2) = plt.subplots(
            3, 1,
            gridspec_kw={'height_ratios': [4, 1.2, 1], 'hspace': 0.04},
            figsize=(14, 8), dpi=180
        )
        BG = '#0B0F17'
        for ax in (ax1, ax_rsi, ax2):
            ax.set_facecolor(BG)
        fig.patch.set_facecolor(BG)

        x = range(n)

        # ── Panel 1: GIÁ ──────────────────────────────────────────────────
        cp = float(hist['Close'].iloc[-1])

        # Vùng TP (xanh lá nhạt)
        if take_profit and entry_low:
            tp_pct = (take_profit - entry_low) / entry_low * 100
            ax1.axhspan(entry_low, take_profit, alpha=0.08, color='#10B981', zorder=0)
            ax1.axhline(y=take_profit, color='#10B981', linewidth=1.4, linestyle='--', alpha=0.9,
                        label=f'Chốt lời: {take_profit:,.0f}  (+{tp_pct:.1f}%)')

        # Vùng Stop (đỏ nhạt)
        if stop_loss and entry_low:
            sl_pct = (stop_loss - entry_low) / entry_low * 100
            ax1.axhspan(stop_loss, entry_low, alpha=0.08, color='#EF4444', zorder=0)
            ax1.axhline(y=stop_loss, color='#EF4444', linewidth=1.4, linestyle='--', alpha=0.9,
                        label=f'Cắt lỗ: {stop_loss:,.0f}  ({sl_pct:.1f}%)')

        # Vùng Entry (xanh dương nhạt)
        if entry_low and entry_high:
            ax1.axhspan(entry_low, entry_high, alpha=0.18, color='#0078D4', zorder=1)
            ax1.axhline(y=entry_low,  color='#0078D4', linewidth=1.2, linestyle='-', alpha=0.7)
            ax1.axhline(y=entry_high, color='#0078D4', linewidth=1.2, linestyle='-', alpha=0.7,
                        label=f'Vùng mua: {entry_low:,.0f}–{entry_high:,.0f}')

        # Nến
        for i in x:
            row = hist.iloc[i]
            color = '#10B981' if row['Close'] >= row['Open'] else '#EF4444'
            ax1.plot([i, i], [row['Low'], row['High']], color=color, linewidth=1.2, zorder=2)
            b_bot = min(row['Open'], row['Close'])
            b_top = max(row['Open'], row['Close'])
            ax1.add_patch(plt.Rectangle((i - 0.38, b_bot), 0.76,
                          max(b_top - b_bot, cp * 0.0005),
                          facecolor=color, edgecolor=color, zorder=2))

        # SMA20 + Ichimoku
        ax1.plot(x, hist['SMA20'], color='#A855F7', linewidth=1.4, label='SMA20', zorder=3)
        ax1.axhline(y=cp, color='#0A84FF', linewidth=1.6, alpha=0.9,
                    label=f'Giá: {cp:,.0f}', zorder=3)
        if tenkan_val and tenkan_val > 0:
            ax1.axhline(y=tenkan_val, color='#F59E0B', linewidth=1.1, linestyle='--', alpha=0.85,
                        label=f'Tenkan: {tenkan_val:,.0f}')
        if kijun_val and kijun_val > 0:
            ax1.axhline(y=kijun_val, color='#FB7185', linewidth=1.1, linestyle='-.', alpha=0.85,
                        label=f'Kijun: {kijun_val:,.0f}')

        ax1.set_title(f'PHÂN TÍCH KỸ THUẬT — {ticker}  |  40 PHIÊN  |  ATR20: {hist["ATR20"].iloc[-1]:,.0f}',
                      color='white', fontsize=11, fontweight='bold', pad=10)
        ax1.legend(loc='upper left', fontsize=8, facecolor='#1C2635',
                   edgecolor='#334155', framealpha=0.9, ncol=2)
        ax1.tick_params(axis='y', colors='#94A3B8', labelsize=8)
        ax1.set_xticks([])
        ax1.grid(True, color='white', alpha=0.04)
        for sp in ['top','right','bottom']: ax1.spines[sp].set_visible(False)
        ax1.spines['left'].set_color('#334155')

        # ── Panel 2: RSI ──────────────────────────────────────────────────
        ax_rsi.plot(x, hist['RSI14'], color='#F59E0B', linewidth=1.2, label='RSI(14)')
        ax_rsi.axhline(70, color='#EF4444', linewidth=0.8, linestyle='--', alpha=0.6)
        ax_rsi.axhline(30, color='#10B981', linewidth=0.8, linestyle='--', alpha=0.6)
        ax_rsi.axhspan(70, 100, alpha=0.04, color='#EF4444')
        ax_rsi.axhspan(0,  30,  alpha=0.04, color='#10B981')
        ax_rsi.fill_between(x, hist['RSI14'], 50,
                             where=(hist['RSI14'] >= 50), alpha=0.1, color='#10B981')
        ax_rsi.fill_between(x, hist['RSI14'], 50,
                             where=(hist['RSI14'] <  50), alpha=0.1, color='#EF4444')
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_yticks([30, 50, 70])
        ax_rsi.tick_params(axis='y', colors='#94A3B8', labelsize=7)
        ax_rsi.set_xticks([])
        ax_rsi.set_ylabel('RSI', color='#94A3B8', fontsize=7)
        ax_rsi.grid(True, color='white', alpha=0.03)
        ax_rsi.legend(loc='upper left', fontsize=7, facecolor='#1C2635',
                      edgecolor='none', framealpha=0.8)
        for sp in ['top','right','bottom']: ax_rsi.spines[sp].set_visible(False)
        ax_rsi.spines['left'].set_color('#334155')

        # ── Panel 3: VOLUME ───────────────────────────────────────────────
        for i in x:
            row = hist.iloc[i]
            color = '#10B981' if row['Close'] >= row['Open'] else '#EF4444'
            ax2.add_patch(plt.Rectangle((i - 0.38, 0), 0.76, row['Volume'],
                          facecolor=color, alpha=0.75))
        ax2.plot(x, hist['Vol_SMA20'], color='white', linewidth=1.2,
                 linestyle='--', label='KL TB20', alpha=0.7)
        step = max(1, n // 10)
        ax2.set_xticks(list(x)[::step])
        ax2.set_xticklabels(
            [hist['Date'].iloc[i].strftime('%d/%m') if hasattr(hist['Date'].iloc[i], 'strftime')
             else str(hist.index[i]) for i in list(x)[::step]],
            rotation=0, color='#94A3B8', fontsize=8
        )
        ax2.tick_params(axis='y', colors='#94A3B8', labelsize=7)
        ax2.set_yticklabels([])
        ax2.legend(loc='upper left', fontsize=7, facecolor='#1C2635', edgecolor='none')
        ax2.grid(True, color='white', alpha=0.03)
        for sp in ['top','right']: ax2.spines[sp].set_visible(False)
        ax2.spines['left'].set_color('#334155')
        ax2.spines['bottom'].set_color('#334155')

        plt.tight_layout(pad=0.5)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=180)
        plt.close(fig)
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
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
        <div class="avoid-break" style="margin:16px 0; padding:16px 20px; background:#FEF2F2;
             border-left:4px solid #EF4444; border-radius:6px;">
            <div style="font-weight:700; color:#B91C1C; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">
                CHƯA ĐỦ ĐIỀU KIỆN MỞ LỆNH
            </div>
            <div style="font-size:12px; color:#7F1D1D; margin-top:6px; line-height:1.5;">
                {plan.get('reason', '')}
            </div>
        </div>
        """

    p = plan
    rr = p['rr_ratio']
    rr_color  = "#059669" if rr >= 2.5 else ("#0078D4" if rr >= 1.5 else "#DC2626")
    win_color = "#059669" if p.get('win_rate_est', 0) >= 65 else ("#F59E0B" if p.get('win_rate_est', 0) >= 50 else "#DC2626")
    regime    = p.get('regime', '')
    regime_color = "#059669" if regime == "UPTREND" else ("#F59E0B" if regime == "SIDEWAY" else "#DC2626")

    position_rows = ""
    if "max_shares" in p:
        position_rows = f"""
        <tr style="border-top:2px solid #E2E8F0;">
            <td colspan="2" style="padding:10px 0 4px; font-size:11px; text-transform:uppercase;
                letter-spacing:0.8px; color:#94A3B8; font-weight:700;">Quản trị vốn</td>
        </tr>
        <tr>
            <td style="padding:5px 0; color:#475569; font-size:13px;">Khối lượng mua (tối đa)</td>
            <td style="text-align:right; font-weight:700; font-size:13px;">{p['max_shares']:,} CP</td>
        </tr>
        <tr>
            <td style="padding:5px 0; color:#475569; font-size:13px;">Giá trị vị thế</td>
            <td style="text-align:right; font-weight:700; font-size:13px;">
                {p['position_value']:,.0f} <span style="color:#94A3B8; font-weight:400;">({p['position_pct_of_nav']}% NAV)</span>
            </td>
        </tr>
        """

    return f"""
    <div class="avoid-break" style="margin:16px 0; border:1px solid #E2E8F0; border-radius:10px; overflow:hidden;">

        <!-- Header card -->
        <div style="background:#0F172A; padding:12px 18px; display:flex; justify-content:space-between; align-items:center;">
            <div style="color:white; font-weight:800; font-size:13px; letter-spacing:0.5px;">
                THIẾT LẬP GIAO DỊCH ĐỊNH LƯỢNG
            </div>
            <div style="display:flex; gap:12px; align-items:center;">
                <span style="color:{regime_color}; font-size:11px; font-weight:700; background:rgba(255,255,255,0.08);
                    padding:3px 8px; border-radius:4px;">{regime}</span>
                <span style="color:{win_color}; font-size:11px; font-weight:700;">
                    XS THẮNG: {p.get('win_rate_est', 0):.0f}%
                </span>
            </div>
        </div>

        <!-- 3 ô Entry / Stop / TP -->
        <div style="display:flex; border-bottom:1px solid #E2E8F0;">
            <div style="flex:1; padding:14px 16px; border-right:1px solid #E2E8F0; text-align:center;">
                <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.8px;
                    color:#64748B; font-weight:700; margin-bottom:6px;">Vùng Mua</div>
                <div style="font-size:15px; font-weight:900; color:#0078D4;">
                    {p['entry_low']:,.0f}
                </div>
                <div style="font-size:11px; color:#94A3B8; margin-top:2px;">
                    — {p['entry_high']:,.0f}
                </div>
                <div style="font-size:10px; color:#94A3B8; margin-top:4px;">
                    Hỗ trợ: {p.get('support_label','—')}
                </div>
            </div>
            <div style="flex:1; padding:14px 16px; border-right:1px solid #E2E8F0; text-align:center;">
                <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.8px;
                    color:#64748B; font-weight:700; margin-bottom:6px;">Cắt Lỗ</div>
                <div style="font-size:15px; font-weight:900; color:#DC2626;">
                    {p['stop_loss']:,.0f}
                </div>
                <div style="font-size:10px; color:#94A3B8; margin-top:6px; line-height:1.4;">
                    {p.get('stop_reason','—')}
                </div>
            </div>
            <div style="flex:1; padding:14px 16px; text-align:center;">
                <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.8px;
                    color:#64748B; font-weight:700; margin-bottom:6px;">Chốt Lời</div>
                <div style="font-size:15px; font-weight:900; color:#059669;">
                    {p['take_profit']:,.0f}
                </div>
                <div style="font-size:11px; font-weight:700; margin-top:4px; color:{rr_color};">
                    R:R = {rr} : 1
                </div>
            </div>
        </div>

        <!-- Thanh SVG price range -->
        <div style="padding:12px 18px 4px; background:#F8FAFC;">
            {render_price_range_svg(p)}
        </div>

        <!-- Bảng chi tiết -->
        <div style="padding:4px 18px 16px; background:#F8FAFC;">
            <table style="width:100%; font-size:13px; border-collapse:collapse;">
                <tr>
                    <td style="padding:5px 0; color:#475569;">Rủi ro / cổ phiếu</td>
                    <td style="text-align:right; font-weight:700;">{p['risk_per_share']:,.0f}</td>
                </tr>
                <tr>
                    <td style="padding:5px 0; color:#475569;">Biên độ biến động ATR(14)</td>
                    <td style="text-align:right; font-weight:700;">{p['atr14']:,.0f}
                        <span style="color:#94A3B8; font-size:11px; font-weight:400;">
                            (dao động trung bình 14 phiên)
                        </span>
                    </td>
                </tr>
                {position_rows}
            </table>
        </div>
    </div>
    """


def _safe_float(val, default=0.0) -> float:
    """Chuyển string (kể cả 'N/A', số có dấu phẩy) về float an toàn."""
    try:
        if val is None or str(val).strip() in ('', 'N/A', 'nan'):
            return default
        return float(str(val).replace(',', '.'))
    except Exception:
        return default


def render_pdf_button(ai_content, ticker_name, dict_dfs, trade_plan=None):
    current_time  = datetime.now().strftime("%d/%m/%Y")
    weekday_map   = {0:"Thứ Hai",1:"Thứ Ba",2:"Thứ Tư",3:"Thứ Năm",4:"Thứ Sáu",5:"Thứ Bảy",6:"Chủ Nhật"}
    today         = datetime.now()
    date_full     = f"{weekday_map[today.weekday()]}, {today.day} Tháng {today.month} {today.year}"
    report_code   = f"LC-{ticker_name}-{today.strftime('%Y%m%d')}"

    # ── Convert markdown AI content ─────────────────────────────────────────
    def md2html(text):
        text = re.sub(r'### (.*?)(\n|$)', r'<p style="font-size:13px;font-weight:700;color:#1a1a2e;margin:12px 0 4px;text-transform:uppercase;letter-spacing:0.3px;">\1</p>', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        text = re.sub(r'- (.*?)(\n|$)', r'<li style="margin:3px 0;">\1</li>', text)
        text = text.replace('\n', '<br>')
        return text

    html_content = md2html(ai_content)

    # ── Lấy dữ liệu ─────────────────────────────────────────────────────────
    df_rs = dict_dfs.get("RS_DATA", pd.DataFrame()) if dict_dfs else pd.DataFrame()
    df_ta = dict_dfs.get("TA_DATA", pd.DataFrame()) if dict_dfs else pd.DataFrame()

    stock_rs = df_rs[df_rs['Mã CK'] == ticker_name].iloc[0].to_dict() \
               if not df_rs.empty and ticker_name in df_rs['Mã CK'].values else {}
    stock_ta = df_ta[df_ta['Mã CK'] == ticker_name].iloc[0].to_dict() \
               if not df_ta.empty and ticker_name in df_ta['Mã CK'].values else {}

    industry = stock_rs.get('Ngành', 'N/A')

    def fnum(val, dec=2, pct=False, vol=False):
        try:
            if val == '' or val is None: return 'N/A'
            v = float(val)
            if pd.isna(v): return 'N/A'
            if vol: return f"{v:,.0f}"
            s = f"{v:,.{dec}f}"
            return f"{s}%" if pct else s
        except Exception:
            return str(val)

    gia_ht   = fnum(stock_rs.get('Giá','N/A'), 0)
    pe       = fnum(stock_rs.get('P/E','N/A'))
    pb       = fnum(stock_rs.get('P/B','N/A'))
    roe      = fnum(stock_rs.get('ROE (%)','N/A'), pct=True)
    debt     = fnum(stock_rs.get('Nợ/Vốn Chủ','N/A'))
    rs_1m    = fnum(stock_rs.get('RS_1M','N/A'), 0)
    rs_3m    = fnum(stock_rs.get('RS_3M','N/A'), 0)
    mfi      = fnum(stock_rs.get('MFI_14','N/A'))
    rsi      = fnum(stock_rs.get('RSI_14','N/A'))
    kl_tb    = fnum(stock_rs.get('KL_TB_20','N/A'), vol=True)
    dot_bien = fnum(stock_rs.get('Đột_Biến_KL','N/A'))
    macd_h   = fnum(stock_rs.get('MACD_Hist','N/A'), dec=3)
    cloud    = str(stock_ta.get('Trạng Thái Mây','N/A'))
    kumo     = str(stock_ta.get('Tín Hiệu Kumo','N/A'))
    tenkan   = fnum(stock_ta.get('Tenkan_sen','N/A'), 0)
    kijun    = fnum(stock_ta.get('Kijun_sen','N/A'), 0)
    senkou_a = fnum(stock_ta.get('Senkou_A','N/A'), 0)
    senkou_b = fnum(stock_ta.get('Senkou_B','N/A'), 0)
    tscore   = int(stock_rs.get('Tech_Score', 0)) if stock_rs else 0

    # Khuyến nghị & màu
    if trade_plan and trade_plan.get('valid'):
        regime     = trade_plan.get('regime','')
        win_rt     = trade_plan.get('win_rate_est', 0)
        rec_text   = trade_plan.get('rec_label', 'QUAN SÁT')
        rec_horizon= trade_plan.get('rec_horizon', '')
        actual_up  = trade_plan.get('upside_pct', 0)

        if rec_text == 'MUA MẠNH':    rec_bg, rec_fg = '#059669', 'white'
        elif rec_text == 'MUA':        rec_bg, rec_fg = '#0078D4', 'white'
        elif rec_text == 'TÍCH LŨY':   rec_bg, rec_fg = '#7C3AED', 'white'
        elif rec_text == 'NGẮN HẠN':   rec_bg, rec_fg = '#F59E0B', 'white'
        else:                           rec_bg, rec_fg = '#64748B', 'white'

        entry_low  = trade_plan.get('entry_low', 0)
        entry_high = trade_plan.get('entry_high', 0)
        stop_val   = trade_plan.get('stop_loss', 0)
        tp_val     = trade_plan.get('take_profit', 0)
        rr_val     = trade_plan.get('rr_ratio', 0)

        try:
            cp_num = float(trade_plan.get('current_price', 0))
            upside_pct   = f"+{actual_up:.1f}%" if actual_up >= 0 else f"{actual_up:.1f}%"
            downside_pct = f"{(stop_val - cp_num)/cp_num*100:.1f}%" if cp_num > 0 else 'N/A'
        except Exception:
            cp_num = 0; upside_pct = 'N/A'; downside_pct = 'N/A'

        # Bảng hỗ trợ/kháng cự từ Ichimoku
        try:
            ten_f = _safe_float(stock_ta.get('Tenkan_sen', 0))
            kij_f = _safe_float(stock_ta.get('Kijun_sen',  0))
            sen_a = _safe_float(stock_ta.get('Senkou_A',   0))
            sen_b = _safe_float(stock_ta.get('Senkou_B',   0))
            htro1    = fnum(max(ten_f, kij_f), 0) if max(ten_f, kij_f) > 0 else 'N/A'
            htro2    = fnum(min(ten_f, kij_f), 0) if min(ten_f, kij_f) > 0 else 'N/A'
            khangcu1 = fnum(max(sen_a, sen_b), 0) if max(sen_a, sen_b) > 0 else 'N/A'
            khangcu2 = fnum(tp_val * 1.05, 0)
        except Exception:
            htro1 = htro2 = khangcu1 = khangcu2 = 'N/A'

        trading_table_html = f"""
        <table style="width:100%;border-collapse:collapse;font-size:12px;text-align:center;margin-top:10px;">
          <tr style="background:#1a1a2e;color:white;font-weight:700;">
            <td style="padding:8px 4px;">KN (1)</td>
            <td style="padding:8px 4px;">KN (2)</td>
            <td style="padding:8px 4px;">Hỗ trợ (1)</td>
            <td style="padding:8px 4px;">Hỗ trợ (2)</td>
            <td style="padding:8px 4px;">Kháng cự (1)</td>
            <td style="padding:8px 4px;">Kháng cự (2)</td>
            <td style="padding:8px 4px;background:#DC2626;">Cắt lỗ</td>
            <td style="padding:8px 4px;background:#059669;">Mục tiêu</td>
          </tr>
          <tr style="background:#F8FAFC;font-weight:700;font-size:13px;">
            <td style="padding:10px 4px;color:#0078D4;">~{fnum(entry_low,0)}</td>
            <td style="padding:10px 4px;color:#0078D4;">~{fnum(entry_high,0)}</td>
            <td style="padding:10px 4px;">~{htro1}</td>
            <td style="padding:10px 4px;">~{htro2}</td>
            <td style="padding:10px 4px;">~{khangcu1}</td>
            <td style="padding:10px 4px;">~{khangcu2}</td>
            <td style="padding:10px 4px;color:#DC2626;">&lt;{fnum(stop_val,0)}</td>
            <td style="padding:10px 4px;color:#059669;">~{fnum(tp_val,0)}</td>
          </tr>
        </table>
        """
    else:
        rec_text, rec_bg, rec_fg = 'QUAN SÁT', '#64748B', 'white'
        entry_low = entry_high = stop_val = tp_val = rr_val = support_lv = 0
        upside_pct = downside_pct = 'N/A'
        trading_table_html = '<p style="color:#94A3B8;font-size:12px;">Chưa đủ dữ liệu để thiết lập bảng giao dịch.</p>'

    # ── Chart (truyền trade_plan để vẽ vùng Entry/Stop/TP) ──────────────────
    chart_b64 = generate_chart_base64(ticker_name, df_ta, trade_plan)

    # ── Peer comparison ──────────────────────────────────────────────────────
    peer_rows_html = ""
    if industry and not df_rs.empty:
        peers = df_rs[(df_rs['Ngành']==industry)&(df_rs['Mã CK']!=ticker_name)]\
                .sort_values('RS_1M',ascending=False).head(10)
        for _, row in peers.iterrows():
            p_trạng = str(row.get('Trạng Thái',''))
            p_color = '#059669' if 'KHẢ QUAN' in p_trạng else ('#DC2626' if 'TIÊU CỰC' in p_trạng else '#64748B')
            peer_rows_html += f"""
            <tr style="border-bottom:1px solid #E2E8F0;font-size:10px;">
                <td style="padding:4px 6px;font-weight:600;">{row.get('Mã CK','')}</td>
                <td style="text-align:right;padding:4px 6px;">{fnum(row.get('P/E',''))}</td>
                <td style="text-align:right;padding:4px 6px;">{fnum(row.get('P/B',''))}</td>
                <td style="text-align:right;padding:4px 6px;">{fnum(row.get('ROE (%)',''),pct=True)}</td>
                <td style="text-align:right;padding:4px 6px;">{fnum(row.get('RS_1M',''),0)}</td>
                <td style="text-align:right;padding:4px 6px;">{fnum(row.get('RS_3M',''),0)}</td>
                <td style="text-align:right;padding:4px 6px;color:{p_color};font-weight:600;">{p_trạng}</td>
            </tr>"""

    peer_table = f"""
    <table style="width:100%;border-collapse:collapse;font-size:10px;margin-top:8px;">
      <tr style="background:#1a1a2e;color:white;font-weight:700;font-size:10px;">
        <td style="padding:5px 6px;">Mã CK</td>
        <td style="text-align:right;padding:5px 6px;">P/E</td>
        <td style="text-align:right;padding:5px 6px;">P/B</td>
        <td style="text-align:right;padding:5px 6px;">ROE</td>
        <td style="text-align:right;padding:5px 6px;">RS 1M</td>
        <td style="text-align:right;padding:5px 6px;">RS 3M</td>
        <td style="text-align:right;padding:5px 6px;">Trạng thái</td>
      </tr>
      <tr style="background:#EFF6FF;font-weight:700;font-size:10px;border-bottom:2px solid #0078D4;">
        <td style="padding:5px 6px;color:#0078D4;">{ticker_name} ★</td>
        <td style="text-align:right;padding:5px 6px;">{pe}</td>
        <td style="text-align:right;padding:5px 6px;">{pb}</td>
        <td style="text-align:right;padding:5px 6px;">{roe}</td>
        <td style="text-align:right;padding:5px 6px;">{rs_1m}</td>
        <td style="text-align:right;padding:5px 6px;">{rs_3m}</td>
        <td style="text-align:right;padding:5px 6px;">{cloud}</td>
      </tr>
      {peer_rows_html}
    </table>
    """ if peer_rows_html else ""

    # ── CSS chung ────────────────────────────────────────────────────────────
    css = """
    <link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body, div { font-family: 'Be Vietnam Pro', 'Roboto', sans-serif; }
      .page { width: 100%; background: white; padding-bottom: 40px; }
      .new-page { page-break-before: always; break-before: page; padding-top: 0; }
      .avoid-break { page-break-inside: avoid; break-inside: avoid; }
      .header-bar { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; }
      .footer-bar { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #94A3B8; font-size: 9px; padding: 8px 28px; margin-top: 20px;
                    display: flex; justify-content: space-between; align-items: center; }
      .accent { color: #7C3AED; }
      .section-title { font-size: 11px; font-weight: 700; color: #1a1a2e;
                       text-transform: uppercase; letter-spacing: 0.8px;
                       border-left: 3px solid #7C3AED; padding-left: 8px; margin-bottom: 10px; }
      .card { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px; }
      .kpi-box { text-align:center; padding: 8px 4px; }
      .kpi-label { font-size:9px; color:#64748B; text-transform:uppercase; letter-spacing:0.5px; font-weight:600; }
      .kpi-val   { font-size:14px; font-weight:800; color:#1a1a2e; margin-top:2px; }
      td, th { vertical-align: middle; }
    </style>
    """

    # ══════════════════════════════════════════════════════════════════════════
    # TRANG 1: KHUYẾN NGHỊ + CHỈ SỐ TÀI CHÍNH + LUẬN ĐIỂM
    # ══════════════════════════════════════════════════════════════════════════
    page1 = f"""
    <div class="page">
      <!-- HEADER -->
      <div class="header-bar">
        <div>
          <div style="color:#94A3B8;font-size:9px;letter-spacing:1px;text-transform:uppercase;">
            LINANCE RESEARCH — BÁO CÁO PHÂN TÍCH KỸ THUẬT ĐỊNH LƯỢNG
          </div>
          <div style="color:white;font-size:13px;font-weight:800;margin-top:2px;">
            LINANCE<span class="accent">.CORE</span>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="color:white;font-size:16px;font-weight:800;">TECHNICAL REPORT</div>
          <div style="color:#94A3B8;font-size:10px;margin-top:2px;">{date_full}</div>
        </div>
      </div>

      <!-- SUBHEADER: Tên công ty -->
      <div style="padding:10px 28px;border-bottom:3px solid #7C3AED;background:#FAFAFA;">
        <div style="font-size:11px;color:#64748B;">Mã cổ phiếu: <b style="color:#1a1a2e;">{ticker_name}</b>
          &nbsp;|&nbsp; Ngành: <b style="color:#1a1a2e;">{industry}</b>
          &nbsp;|&nbsp; Mã báo cáo: <span style="color:#7C3AED;">{report_code}</span>
        </div>
      </div>

      <!-- BODY TRANG 1 -->
      <div style="padding:16px 28px;display:flex;gap:20px;">

        <!-- CỘT TRÁI: Khuyến nghị + Chỉ số -->
        <div style="flex:0 0 220px;">

          <!-- Box Khuyến nghị -->
          <div class="card avoid-break" style="margin-bottom:12px;text-align:center;">
            <div class="kpi-label" style="margin-bottom:6px;">KHUYẾN NGHỊ</div>
            <div style="background:{rec_bg};color:{rec_fg};font-weight:800;font-size:16px;
                 padding:7px 14px;border-radius:6px;display:inline-block;letter-spacing:1px;">
              {rec_text}
            </div>
            <div style="font-size:9px;color:#94A3B8;margin-top:4px;">{rec_horizon}</div>
            <div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:6px;">
              <div class="kpi-box" style="border-right:1px solid #E2E8F0;">
                <div class="kpi-label">Giá hiện tại</div>
                <div class="kpi-val" style="font-size:12px;">{gia_ht}</div>
              </div>
              <div class="kpi-box">
                <div class="kpi-label">Mục tiêu</div>
                <div class="kpi-val" style="font-size:12px;color:#059669;">{fnum(tp_val,0) if tp_val else 'N/A'}</div>
              </div>
              <div class="kpi-box" style="border-right:1px solid #E2E8F0;">
                <div class="kpi-label">Upside</div>
                <div class="kpi-val" style="font-size:12px;color:#059669;">{upside_pct}</div>
              </div>
              <div class="kpi-box">
                <div class="kpi-label">Cắt lỗ</div>
                <div class="kpi-val" style="font-size:12px;color:#DC2626;">{fnum(stop_val,0) if stop_val else 'N/A'}</div>
              </div>
            </div>
          </div>

          <!-- Chỉ số tài chính -->
          <div class="avoid-break" style="margin-bottom:12px;">
            <div class="section-title">Chỉ Số Tài Chính</div>
            <table style="width:100%;font-size:11px;border-collapse:collapse;">
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">P/E</td>
                <td style="text-align:right;font-weight:700;">{pe}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">P/B</td>
                <td style="text-align:right;font-weight:700;">{pb}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">ROE</td>
                <td style="text-align:right;font-weight:700;">{roe}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Nợ / Vốn chủ</td>
                <td style="text-align:right;font-weight:700;">{debt}</td>
              </tr>
            </table>
          </div>

          <!-- Chỉ báo kỹ thuật -->
          <div class="avoid-break" style="margin-bottom:12px;">
            <div class="section-title">Chỉ Báo Kỹ Thuật</div>
            <table style="width:100%;font-size:11px;border-collapse:collapse;">
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">RSI(14)</td>
                <td style="text-align:right;font-weight:700;">{rsi}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">MFI(14)</td>
                <td style="text-align:right;font-weight:700;">{mfi}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">MACD Hist</td>
                <td style="text-align:right;font-weight:700;">{macd_h}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">RS 1 tháng</td>
                <td style="text-align:right;font-weight:700;">{rs_1m}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">RS 3 tháng</td>
                <td style="text-align:right;font-weight:700;">{rs_3m}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">KL TB 20 phiên</td>
                <td style="text-align:right;font-weight:700;">{kl_tb}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Đột biến KL</td>
                <td style="text-align:right;font-weight:700;">{dot_bien}%</td>
              </tr>
            </table>
          </div>

          <!-- Ichimoku snapshot -->
          <div class="avoid-break">
            <div class="section-title">Ichimoku Kinko Hyo</div>
            <table style="width:100%;font-size:11px;border-collapse:collapse;">
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Tenkan-sen</td>
                <td style="text-align:right;font-weight:700;">{tenkan}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Kijun-sen</td>
                <td style="text-align:right;font-weight:700;">{kijun}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Senkou A</td>
                <td style="text-align:right;font-weight:700;">{senkou_a}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Senkou B</td>
                <td style="text-align:right;font-weight:700;">{senkou_b}</td>
              </tr>
              <tr style="border-bottom:1px solid #F1F5F9;">
                <td style="padding:5px 0;color:#64748B;">Trạng thái mây</td>
                <td style="text-align:right;font-weight:700;font-size:10px;">{cloud}</td>
              </tr>
              <tr>
                <td style="padding:5px 0;color:#64748B;">Tín hiệu Kumo</td>
                <td style="text-align:right;font-weight:700;color:#7C3AED;">{kumo}</td>
              </tr>
            </table>
          </div>
        </div>

        <!-- CỘT PHẢI: Luận điểm AI -->
        <div style="flex:1;min-width:0;">
          <div class="section-title">Luận Điểm Đầu Tư &amp; Kế Hoạch Giao Dịch</div>
          <div style="font-size:12px;line-height:1.7;color:#1E293B;text-align:justify;">
            {html_content}
          </div>

          <!-- So sánh ngành -->
          {f'<div class="avoid-break" style="margin-top:16px;"><div class="section-title">So Sánh Cùng Ngành ({industry})</div>{peer_table}</div>' if peer_table else ''}
        </div>
      </div>

      <!-- FOOTER -->
      <div class="footer-bar" style="position:absolute;bottom:0;left:0;right:0;">
        <div>LINANCE Research &nbsp;|&nbsp; Nguyễn Đào Thăng Long — Quantitative Analyst</div>
        <div>{report_code}</div>
      </div>
    </div>
    """

    # ══════════════════════════════════════════════════════════════════════════
    # TRANG 2: CHART KỸ THUẬT + BẢNG HỖ TRỢ/KHÁNG CỰ
    # ══════════════════════════════════════════════════════════════════════════
    chart_img_html = f'<img src="{chart_b64}" style="width:100%;border-radius:6px;display:block;">' \
                     if chart_b64 else '<div style="color:#94A3B8;text-align:center;padding:40px;">Không tải được biểu đồ</div>'

    page2 = f"""
    <div class="page new-page">
      <!-- HEADER -->
      <div class="header-bar">
        <div>
          <div style="color:#94A3B8;font-size:9px;letter-spacing:1px;text-transform:uppercase;">
            LINANCE RESEARCH — PHÂN TÍCH KỸ THUẬT
          </div>
          <div style="color:white;font-size:13px;font-weight:800;margin-top:2px;">
            LINANCE<span class="accent">.CORE</span>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="color:white;font-size:16px;font-weight:800;">TECHNICAL REPORT</div>
          <div style="color:#94A3B8;font-size:10px;margin-top:2px;">{date_full}</div>
        </div>
      </div>

      <div style="padding:6px 28px 2px;border-bottom:2px solid #7C3AED;background:#FAFAFA;">
        <div style="font-size:11px;color:#64748B;">
          Mã: <b style="color:#1a1a2e;">{ticker_name}</b> &nbsp;|&nbsp; {industry}
          &nbsp;|&nbsp; <span style="color:#7C3AED;">{report_code}</span>
        </div>
      </div>

      <div style="padding:12px 28px;">
        <!-- Bảng hỗ trợ/kháng cự/cắt lỗ/mục tiêu -->
        <div class="section-title" style="margin-bottom:8px;">Vùng Giao Dịch Tham Chiếu</div>
        {trading_table_html}

        <!-- Chart -->
        <div style="margin-top:12px;">
          <div class="section-title" style="margin-bottom:6px;">
            Phân Tích Kỹ Thuật — {ticker_name} (40 Phiên) | RSI(14) | Vùng Entry/SL/TP
          </div>
          {chart_img_html}
        </div>

        <!-- Chú thích chart -->
        <div style="margin-top:8px;font-size:9px;color:#64748B;display:flex;gap:16px;flex-wrap:wrap;">
          <span><span style="color:#0078D4;font-weight:700;">━</span> Vùng Mua</span>
          <span><span style="color:#DC2626;font-weight:700;">- -</span> Cắt lỗ</span>
          <span><span style="color:#059669;font-weight:700;">- -</span> Mục tiêu</span>
          <span><span style="color:#A855F7;font-weight:700;">━</span> SMA20</span>
          <span><span style="color:#F59E0B;font-weight:700;">- -</span> Tenkan-sen</span>
          <span><span style="color:#FB7185;font-weight:700;">-·-</span> Kijun-sen</span>
          <span><span style="color:#F59E0B;font-weight:700;">━</span> RSI(14)</span>
        </div>

        <!-- Phân tích kỹ thuật brief -->
        <div class="avoid-break" style="margin-top:14px;display:flex;gap:16px;">
          <div style="flex:1;">
            <div class="section-title">Phân Tích Kỹ Thuật</div>
            <div style="font-size:11px;color:#1E293B;line-height:1.65;">
              Dữ liệu hệ thống ghi nhận cổ phiếu <b>{ticker_name}</b> đang ở trạng thái
              <b>{cloud}</b> với tín hiệu Kumo <b style="color:#7C3AED;">{kumo}</b>.
              {'Tenkan-sen (' + tenkan + ') ' + ("trên" if _safe_float(tenkan) > _safe_float(kijun) else "dưới") + ' Kijun-sen (' + kijun + ') — phản ánh động lượng ngắn hạn ' + ("tích cực" if _safe_float(tenkan) > _safe_float(kijun) else "đang suy yếu") + '.' if tenkan != 'N/A' and kijun != 'N/A' else ''}
              {'RSI(14) tại ' + rsi + ' ' + ("cho thấy đà tăng còn dư địa" if _safe_float(rsi) < 70 else "tiệm cận vùng quá mua") + '.' if rsi != 'N/A' else ''}
              {'MACD Histogram ' + macd_h + ' ' + ("dương — xác nhận xu hướng tăng" if _safe_float(macd_h) > 0 else "âm — áp lực bán chiếm ưu thế") + '.' if macd_h != 'N/A' else ''}
            </div>
          </div>
          <div style="flex:1;">
            <div class="section-title">Chiến Lược Giao Dịch</div>
            <div style="font-size:11px;color:#1E293B;line-height:1.65;">
              <b>Vùng mua:</b> {fnum(entry_low,0)} — {fnum(entry_high,0)}<br>
              <b>Cắt lỗ cứng:</b> {fnum(stop_val,0)} ({downside_pct} từ entry)<br>
              <b>Mục tiêu:</b> {fnum(tp_val,0)} ({upside_pct} từ entry)<br>
              <b>Tỷ lệ R:R:</b> {rr_val} : 1<br>
              <b>Hỗ trợ tham chiếu:</b> {trade_plan.get('support_label','—') if trade_plan else '—'}<br>
              <b>Điều kiện vào lệnh:</b> Giá pullback về vùng mua, khối lượng
              {"duy trì trên mức TB 20 phiên" if dot_bien != 'N/A' else "cần theo dõi"}.
            </div>
          </div>
        </div>
      </div>

      <div class="footer-bar" style="position:absolute;bottom:0;left:0;right:0;">
        <div>LINANCE Research &nbsp;|&nbsp; Dữ liệu: HOSE/HNX &nbsp;|&nbsp; Nguồn tính toán: LINANCE Quantitative Engine</div>
        <div>{report_code} — Trang 2/3</div>
      </div>
    </div>
    """

    # ══════════════════════════════════════════════════════════════════════════
    # TRANG 3: DISCLAIMER + THÔNG TIN TỔ CHỨC
    # ══════════════════════════════════════════════════════════════════════════
    page3 = f"""
    <div class="page new-page">
      <div class="header-bar">
        <div>
          <div style="color:white;font-size:13px;font-weight:800;">LINANCE<span class="accent">.CORE</span></div>
          <div style="color:#94A3B8;font-size:9px;margin-top:2px;">LINANCE RESEARCH</div>
        </div>
        <div style="text-align:right;">
          <div style="color:white;font-size:16px;font-weight:800;">TECHNICAL REPORT</div>
          <div style="color:#94A3B8;font-size:10px;margin-top:2px;">{date_full}</div>
        </div>
      </div>

      <div style="padding:28px 40px;font-size:11px;color:#1E293B;line-height:1.75;">

        <div style="margin-bottom:20px;">
          <div class="section-title" style="font-size:12px;">Tổ Chức Thực Hiện Báo Cáo</div>
          <p style="margin-top:8px;">
            <b>LINANCE Research</b> là bộ phận phân tích định lượng thuộc Trung tâm Phân tích Định lượng LINANCE.
            Hệ thống sử dụng mô hình thuật toán kết hợp phân tích kỹ thuật, phân tích tương đối
            (Relative Strength) và Ichimoku Kinko Hyo để đánh giá cổ phiếu trên thị trường chứng khoán Việt Nam (HOSE, HNX, UPCoM).
          </p>
        </div>

        <div style="margin-bottom:20px;">
          <div class="section-title" style="font-size:12px;">Nhân Viên Phân Tích</div>
          <p style="margin-top:8px;">
            <b>Nguyễn Đào Thăng Long</b><br>
            Chuyên viên Phân tích Định lượng (Quantitative Analyst)<br>
            Trung tâm Phân tích Định lượng LINANCE
          </p>
        </div>

        <div style="margin-bottom:20px;">
          <div class="section-title" style="font-size:12px;">Khuyến Cáo Quan Trọng</div>
          <p style="margin-top:8px;font-style:italic;color:#475569;">
            Báo cáo này chỉ nhằm cung cấp thông tin phục vụ mục đích tham khảo và không cấu thành lời khuyên đầu tư
            hay lời mời chào mua hoặc bán bất kỳ chứng khoán nào. Các nhận định, đánh giá trong báo cáo phản ánh
            kết quả tính toán của mô hình định lượng tại thời điểm phát hành và có thể thay đổi mà không cần thông báo trước.
          </p>
          <p style="margin-top:8px;font-style:italic;color:#475569;">
            Nhà đầu tư cần tự thực hiện nghiên cứu độc lập và/hoặc tham khảo ý kiến chuyên gia tài chính được cấp phép
            trước khi đưa ra quyết định đầu tư. LINANCE Research không chịu trách nhiệm đối với bất kỳ tổn thất nào
            phát sinh từ việc sử dụng thông tin trong báo cáo này.
          </p>
          <p style="margin-top:8px;font-style:italic;color:#475569;">
            Thông tin sử dụng trong báo cáo được thu thập từ các nguồn được coi là đáng tin cậy (HOSE, HNX, Yahoo Finance,
            vnstock). Tuy nhiên, LINANCE Research không đảm bảo tính chính xác tuyệt đối của dữ liệu.
            Báo cáo này là tài sản của LINANCE Research. Không được phép sao chép, phát hành hoặc tái phân phối
            khi chưa có sự chấp thuận bằng văn bản.
          </p>
        </div>

        <div style="border-top:1px solid #E2E8F0;padding-top:16px;color:#64748B;font-size:10px;">
          <b>Mã báo cáo:</b> {report_code} &nbsp;|&nbsp;
          <b>Ngày phát hành:</b> {current_time} &nbsp;|&nbsp;
          <b>Phiên bản:</b> LINANCE Quantitative Engine v2.0
        </div>
      </div>

      <div class="footer-bar" style="position:absolute;bottom:0;left:0;right:0;">
        <div>LINANCE RESEARCH — PHÒNG PHÂN TÍCH ĐỊNH LƯỢNG</div>
        <div>{report_code} — Trang 3/3</div>
      </div>
    </div>
    """

    # ── Ghép 3 trang ─────────────────────────────────────────────────────────
    raw_report_html = css + page1 + page2 + page3

    b64_html  = base64.b64encode(raw_report_html.encode('utf-8')).decode('utf-8')
    file_name = f"LINANCE_{ticker_name}_{today.strftime('%d%m%Y_%H%M')}.pdf"

    button_code = f"""
    <body style="margin:0;padding:0;overflow:hidden;background:transparent;">
      <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
      <style>
        .pdf-btn{{background:transparent;color:#10B981;border:1px solid rgba(16,185,129,0.5);
                  border-radius:6px;padding:6px 12px;font-family:'JetBrains Mono',monospace;
                  font-size:11px;font-weight:bold;cursor:pointer;transition:all 0.3s;
                  display:inline-flex;align-items:center;}}
        .pdf-btn:hover{{background:#10B981;color:#fff;box-shadow:0 0 10px rgba(16,185,129,0.4);}}
      </style>
      <button class="pdf-btn" id="dlPdfBtn" onclick="exportPDF()">EXPORT PDF</button>
      <script>
      function exportPDF(){{
        document.getElementById("dlPdfBtn").innerText="⏳ GENERATING...";
        const b=window.atob('{b64_html}');
        const a=new Uint8Array(b.length);
        for(let i=0;i<b.length;i++) a[i]=b.charCodeAt(i);
        const html=new TextDecoder('utf-8').decode(a);
        const d=document.createElement('div');
        d.innerHTML=html;
        html2pdf().set({{
          margin:[0,0,0,0],
          filename:'{file_name}',
          image:{{type:'jpeg',quality:0.98}},
          html2canvas:{{scale:2,useCORS:true,logging:false}},
          jsPDF:{{unit:'mm',format:'a4',orientation:'portrait'}},
          pagebreak:{{mode:['css','legacy']}}
        }}).from(d).save().then(()=>{{
          document.getElementById("dlPdfBtn").innerText="✅ DOWNLOADED!";
          setTimeout(()=>document.getElementById("dlPdfBtn").innerText="EXPORT PDF",3000);
        }});
      }}
      </script>
    </body>
    """
    return button_code

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
    chart_html = f"""
    <div style="page-break-before: always; padding: 30px 40px 20px 40px; background:white;">
        <div style="font-size:13px; font-weight:700; color:#0078D4; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:12px; border-bottom:2px solid #0078D4; padding-bottom:6px;">
            BIỂU ĐỒ GIÁ &amp; KHỐI LƯỢNG — {ticker_name} (35 PHIÊN GẦN NHẤT)
        </div>
        <img src="{chart_base64}" style="width:95%; display:block; margin:0 auto;
             border:1px solid #E2E8F0; border-radius:8px;">
    </div>
    """ if chart_base64 else ""

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


def calculate_trade_plan(ticker: str, df_rs: pd.DataFrame, df_ta: pd.DataFrame) -> dict:
    """
    ENGINE TÍNH TOÁN GIAO DỊCH CHUẨN — v3.0
    ==========================================
    Bộ nguyên tắc cố định (không phụ thuộc user input):
      1. Xác định xu hướng → chỉ MUA khi UPTREND hoặc SIDEWAY có tín hiệu tốt
      2. Entry = vùng hỗ trợ kỹ thuật thật (Kijun → SMA20 → Tenkan → Swing Low 10p)
         Entry PHẢI ≤ giá hiện tại
      3. Stop = Entry − N×ATR20  (N=1.0 hỗ trợ mạnh, N=1.5 hỗ trợ yếu)
         Không dùng đáy lịch sử xa làm stop
      4. TP = Entry + RR × risk_per_share
         RR tự động theo win rate (1.5–3.5)
         TP PHẢI > giá hiện tại
         Kháng cự Ichimoku/swing chỉ giới hạn TP nếu nằm trên giá hiện tại ít nhất 1%
      5. R:R thực tế ≥ 1.5 mới chấp nhận
    """
    result = {"valid": False, "reason": "", "ticker": ticker}
    try:
        # ── 1. GIÁ & OHLC ────────────────────────────────────────────────────
        hist, current_price = _fetch_ohlc_with_retry(ticker)
        if hist is None or current_price is None:
            result["reason"] = "Không lấy được dữ liệu giá. Thử lại sau ít phút."
            return result

        close = hist['Close']
        high  = hist['High']
        low   = hist['Low']

        # ── 2. ATR20 ─────────────────────────────────────────────────────────
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr20 = tr.rolling(20).mean().iloc[-1]
        atr14 = tr.rolling(14).mean().iloc[-1]
        atr_use = atr20 if (not pd.isna(atr20) and atr20 > 0) else atr14

        if pd.isna(atr_use) or atr_use <= 0:
            result["reason"] = "Không tính được ATR — thiếu dữ liệu OHLC."
            return result

        # ── 3. CÁC MỨC KỸ THUẬT ─────────────────────────────────────────────
        sma20 = close.rolling(20).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None

        swing_low_10  = low.tail(10).min()
        swing_high_10 = high.tail(10).max()
        swing_high_20 = high.tail(20).max()

        # ── 4. ICHIMOKU TỪ TA_DATA ───────────────────────────────────────────
        kijun_val = tenkan_val = senkou_a_val = senkou_b_val = None
        cloud_status = kumo_signal = ""

        if df_ta is not None and not df_ta.empty and ticker in df_ta['Mã CK'].values:
            ta = df_ta[df_ta['Mã CK'] == ticker].iloc[0].to_dict()
            for key, var in [('Kijun_sen', 'kijun_val'), ('Tenkan_sen', 'tenkan_val'),
                              ('Senkou_A', 'senkou_a_val'), ('Senkou_B', 'senkou_b_val')]:
                try:
                    v = float(ta.get(key, 0))
                    if v > 0: locals()[var]  # just check
                    if key == 'Kijun_sen':    kijun_val    = v or None
                    if key == 'Tenkan_sen':   tenkan_val   = v or None
                    if key == 'Senkou_A':     senkou_a_val = v or None
                    if key == 'Senkou_B':     senkou_b_val = v or None
                except Exception:
                    pass
            cloud_status = str(ta.get('Trạng Thái Mây', ''))
            kumo_signal  = str(ta.get('Tín Hiệu Kumo', ''))

        # ── 5. DỮ LIỆU RS_DATA ───────────────────────────────────────────────
        tech_score = 0
        rs_1m      = 50
        if df_rs is not None and not df_rs.empty and ticker in df_rs['Mã CK'].values:
            rs_row = df_rs[df_rs['Mã CK'] == ticker].iloc[0].to_dict()
            try: tech_score = int(rs_row.get('Tech_Score', 0))
            except Exception: pass
            try: rs_1m = float(rs_row.get('RS_1M', 50))
            except Exception: pass

        # ── 6. XU HƯỚNG (REGIME) ─────────────────────────────────────────────
        above_sma20  = current_price > sma20 if sma20 else False
        above_sma50  = current_price > sma50 if sma50 else True
        above_kijun  = current_price > kijun_val if kijun_val else False
        above_cloud  = "TRÊN Mây" in cloud_status
        below_cloud  = "DƯỚI Mây" in cloud_status
        bullish_kumo = "MUA" in kumo_signal

        trend_points = sum([above_sma20, above_sma50, above_kijun, above_cloud, bullish_kumo])

        if trend_points >= 3:
            regime = "UPTREND"
        elif trend_points <= 1 and below_cloud:
            regime = "DOWNTREND"
        else:
            regime = "SIDEWAY"

        if regime == "DOWNTREND" and tech_score < -2:
            result["reason"] = (
                f"DOWNTREND xác nhận (xu hướng {trend_points}/5, Tech_Score {tech_score}). "
                f"Chưa đủ điều kiện mua — đứng ngoài."
            )
            return result

        # ── 7. WIN RATE & RR TỰ ĐỘNG ─────────────────────────────────────────
        score_norm   = min(max((tech_score + 8) / 16 * 100, 0), 100)
        ichimoku_pts = 70 if above_cloud else (40 if not below_cloud else 20)
        win_rate_est = round(score_norm * 0.4 + ichimoku_pts * 0.35 + rs_1m * 0.25, 1)

        if win_rate_est >= 65:
            rr_min, rr_use, quality_label = 1.5, 2.0, "CAO"
        elif win_rate_est >= 50:
            rr_min, rr_use, quality_label = 2.0, 2.5, "TRUNG BÌNH"
        else:
            if regime != "UPTREND":
                result["reason"] = f"Win rate thấp ({win_rate_est:.0f}%) + {regime}. Không mở lệnh."
                return result
            rr_min, rr_use, quality_label = 2.5, 3.0, "THẤP"

        # ── 8. ENTRY — HỖ TRỢ KỸ THUẬT ≤ GIÁ HIỆN TẠI ─────────────────────
        support_candidates = []
        if kijun_val  and 0 < kijun_val  <= current_price: support_candidates.append(("Kijun-sen",          kijun_val))
        if sma20      and 0 < sma20      <= current_price: support_candidates.append(("SMA20",               sma20))
        if tenkan_val and 0 < tenkan_val <= current_price: support_candidates.append(("Tenkan-sen",          tenkan_val))
        if swing_low_10 and 0 < swing_low_10 <= current_price: support_candidates.append(("Swing Low 10p",  swing_low_10))
        if senkou_b_val and 0 < senkou_b_val <= current_price: support_candidates.append(("Senkou_B",        senkou_b_val))

        if support_candidates:
            support_label, support_level = max(support_candidates, key=lambda x: x[1])
        else:
            support_label  = "ATR fallback"
            support_level  = current_price

        entry_low  = round(max(support_level * 0.997, support_level - 0.3 * atr_use), 0)
        entry_high = round(min(support_level * 1.003, current_price), 0)
        if entry_low >= entry_high:
            entry_low = round(entry_high - 0.2 * atr_use, 0)

        # ── 9. STOP — ENTRY − N×ATR (KHÔNG DÙNG ĐÁY LỊCH SỬ XA) ────────────
        strong_supports = {"Kijun-sen", "SMA20", "Tenkan-sen"}
        n_atr = 1.0 if support_label in strong_supports else 1.5
        stop_loss = round(entry_low - n_atr * atr_use, 0)
        stop_reason = f"Entry ({entry_low:,.0f}) − {n_atr}×ATR20 | Hỗ trợ: {support_label}"

        risk_per_share = entry_low - stop_loss
        if risk_per_share <= 0:
            result["reason"] = "Stop-loss không hợp lệ."
            return result

        # ── 10. TP — PHƯƠNG PHÁP TRUNG-DÀI HẠN (TARGET 15–35% UPSIDE) ──────
        # Tổ chức quant dùng 2 phương pháp tính TP rồi lấy giá trị hợp lý nhất:
        # (A) Price momentum target: current_price × upside_factor (15–35% tùy chất lượng)
        # (B) RR-based target: entry + RR × risk (đảm bảo R:R đủ hấp dẫn)
        # TP cuối = max(A, B), sau đó kiểm tra kháng cự

        # Upside target theo win rate (chuẩn báo cáo CTCK 3-6 tháng)
        if win_rate_est >= 65:
            upside_target = 0.25   # 25% — MUA MẠNH
            rec_horizon   = "Trung hạn (3–6 tháng)"
        elif win_rate_est >= 55:
            upside_target = 0.20   # 20% — MUA
            rec_horizon   = "Trung hạn (2–4 tháng)"
        elif win_rate_est >= 45:
            upside_target = 0.15   # 15% — TÍCH LŨY
            rec_horizon   = "Ngắn-trung hạn (1–3 tháng)"
        else:
            upside_target = 0.12   # 12% — NGẮN HẠN
            rec_horizon   = "Ngắn hạn (1–2 tháng)"

        tp_momentum = round(current_price * (1 + upside_target), 0)
        tp_rr_based = entry_low + risk_per_share * rr_use
        tp_primary  = max(tp_momentum, tp_rr_based)

        # TP phải > current_price ít nhất upside_target/2
        tp_minimum = round(current_price * (1 + upside_target * 0.5), 0)
        tp_primary = max(tp_primary, tp_minimum)

        # Kháng cự chỉ giới hạn TP nếu R:R tại kháng cự đó vẫn ≥ rr_min
        resistance_threshold = current_price * 1.03  # kháng cự cần cách giá ít nhất 3%
        resistance_candidates = []
        if swing_high_10 > resistance_threshold:
            resistance_candidates.append(("Swing High 10p", swing_high_10))
        if swing_high_20 > resistance_threshold:
            resistance_candidates.append(("Swing High 20p", swing_high_20))
        if senkou_a_val and senkou_a_val > resistance_threshold:
            resistance_candidates.append(("Senkou_A",       senkou_a_val))

        tp_note = f"Upside target {upside_target*100:.0f}% | {rec_horizon}"
        take_profit = round(tp_primary, 0)

        if resistance_candidates:
            nearest_res_label, nearest_res = min(resistance_candidates, key=lambda x: x[1])
            if nearest_res < tp_primary:
                rr_at_res = (nearest_res - entry_low) / risk_per_share
                if rr_at_res >= rr_min:
                    # Kháng cự đủ hấp dẫn → giới hạn TP sát dưới kháng cự
                    take_profit = round(nearest_res * 0.995, 0)
                    tp_note = f"{nearest_res_label} @ {nearest_res:,.0f} | {rec_horizon}"
                # Nếu kháng cự quá gần → bỏ qua, giữ TP momentum

        actual_rr = round((take_profit - entry_low) / risk_per_share, 2)
        actual_upside = round((take_profit - current_price) / current_price * 100, 1)

        if actual_rr < 1.5:
            result["reason"] = (
                f"R:R thực tế ({actual_rr}) < 1.5. "
                f"Giá ({current_price:,.0f}) quá xa hỗ trợ. Chờ pullback."
            )
            return result

        # ── 11. PHÂN LOẠI KHUYẾN NGHỊ THEO UPSIDE CHUẨN CTCK ───────────────
        if actual_upside >= 20:
            rec_label = "MUA MẠNH"
        elif actual_upside >= 15:
            rec_label = "MUA"
        elif actual_upside >= 10:
            rec_label = "TÍCH LŨY"
        else:
            rec_label = "NGẮN HẠN"

        result.update({
            "valid":          True,
            "ticker":         ticker,
            "regime":         regime,
            "trend_points":   trend_points,
            "win_rate_est":   win_rate_est,
            "quality_label":  quality_label,
            "rec_label":      rec_label,
            "rec_horizon":    rec_horizon,
            "current_price":  round(current_price, 0),
            "atr14":          round(atr14, 0),
            "atr_use":        round(atr_use, 0),
            "support_label":  support_label,
            "support_level":  round(support_level, 0),
            "entry_low":      entry_low,
            "entry_high":     entry_high,
            "stop_loss":      stop_loss,
            "stop_reason":    stop_reason,
            "take_profit":    take_profit,
            "risk_per_share": round(risk_per_share, 0),
            "rr_ratio":       actual_rr,
            "rr_used":        rr_use,
            "upside_pct":     actual_upside,
            "tp_note":        tp_note,
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
    st.markdown("### BỘ NGUYÊN TẮC GIAO DỊCH")
    st.caption("""
**Cố định — áp dụng toàn hệ thống:**
- Entry: Vùng hỗ trợ Kijun/SMA20/Swing Low
- Stop: Entry − 1.0×ATR20 (hỗ trợ mạnh) hoặc − 1.5×ATR20
- TP: Entry + RR × Risk (RR tự động theo win rate)
- Kháng cự Ichimoku giới hạn TP trên
- R:R ≥ 1.5 mới mở lệnh
    """)

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
        content_text = message.get("content") or ""
        if content_text:
            st.markdown(content_text)

        if "chart" in message and message["chart"] is not None:
            st.line_chart(message["chart"])

        if message["role"] == "assistant":
            col_btn1, col_btn2, _ = st.columns([1.5, 2.5, 6])
            with col_btn1:
                components.html(render_copy_button(content_text), height=35)
            with col_btn2:
                # Ưu tiên lấy ticker từ trade_plan (chính xác hơn regex trên text)
                stored_plan = message.get("trade_plan")
                if stored_plan and stored_plan.get("ticker"):
                    ticker_name = stored_plan["ticker"]
                else:
                    ticker_match = re.search(r'\b[A-Z]{3,4}\b', content_text)
                    ticker_name = ticker_match.group(0) if ticker_match else "STOCK"
                components.html(render_pdf_button(content_text, ticker_name, dict_dfs, stored_plan), height=35)

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
                    )
                    trade_plan_facts = format_trade_plan_facts(plan)

                client = genai.Client(api_key=API_KEY)

                sys_prompt = """
Bạn là Chuyên viên Phân tích Định lượng cấp cao (Senior Quantitative Analyst) tại LINANCE Research.
Nhiệm vụ: Soạn thảo báo cáo khuyến nghị đầu tư theo chuẩn tổ chức định lượng (Quant Fund / CTCK Research).

VĂN PHONG:
- Chuẩn báo cáo CTCK: SSI Research, VNDirect, MBS. Trung lập, khách quan, súc tích.
- KHÔNG dùng: "Bậc thầy", "cơ hội vàng", "tiềm năng bùng nổ", emoji, ngôn ngữ cổ vũ.
- Xưng hô: "Hệ thống ghi nhận...", "Dữ liệu cho thấy...", "Chúng tôi đánh giá...", "Khuyến nghị..."

KHUNG PHÂN LOẠI KHUYẾN NGHỊ (BẮT BUỘC dùng đúng label từ SYSTEM_FACTS):
- MUA MẠNH: Upside ≥ 20%, win rate cao, UPTREND rõ → horizon 3–6 tháng
- MUA: Upside 15–20%, tín hiệu tốt → horizon 2–4 tháng  
- TÍCH LŨY: Upside 10–15%, xu hướng trung tính-tích cực → horizon 1–3 tháng
- NGẮN HẠN: Upside 8–12%, giao dịch cơ hội → horizon 1–2 tháng
- QUAN SÁT: Chưa đủ điều kiện — nêu rõ điều kiện kích hoạt

NGUYÊN TẮC SỐ LIỆU:
1. SYSTEM_FACTS = nguồn DUY NHẤT cho Entry/Stop/TP/R:R. KHÔNG tự tính lại.
2. Luôn gọi get_live_stock_data để xác nhận giá real-time trước khi viết.
3. Nếu giá real-time khác giá trong SYSTEM_FACTS > 2% → ghi chú sự chênh lệch.
4. SYSTEM_FACTS báo "KHÔNG ĐỦ ĐIỀU KIỆN" → khuyến nghị QUAN SÁT, nêu điều kiện cần.

CẤU TRÚC BÁO CÁO (dùng ### cho tiêu đề):

### TÓM TẮT KHUYẾN NGHỊ
Một dòng: Mã [XX] — [rec_label] — Mục tiêu [TP] (+upside%) — Cắt lỗ [Stop] — Horizon [X tháng]

### DIỄN BIẾN GIÁ & KỸ THUẬT
Xu hướng, vị trí Ichimoku, tín hiệu khối lượng, RSI/MFI. Ngắn gọn 3–4 câu.

### ĐÁNH GIÁ CƠ BẢN
P/E, P/B, ROE so sánh ngành. Nhận xét định giá. 2–3 câu.

### KẾ HOẠCH GIAO DỊCH
- **Vùng mua:** [từ SYSTEM_FACTS]
- **Điểm cắt lỗ:** [từ SYSTEM_FACTS] — *Lý do: [giải thích hỗ trợ kỹ thuật bị vi phạm]*
- **Mục tiêu chốt lời:** [từ SYSTEM_FACTS] — *Lý do: [kháng cự kỹ thuật/upside target]*
- **Tỷ lệ R:R:** [từ SYSTEM_FACTS]

### RỦI RO CẦN LƯU Ý
2–3 rủi ro cụ thể (thị trường chung, kỹ thuật, cơ bản).

*Khuyến nghị tổng hợp từ mô hình định lượng LINANCE. Nhà đầu tư tự chịu trách nhiệm với quyết định giải ngân.*
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
            response_text = getattr(response, 'text', None) or ""
            if response_text:
                st.markdown(response_text)

            col_btn1, col_btn2, _ = st.columns([1.5, 2.5, 6])
            with col_btn1:
                components.html(render_copy_button(response_text), height=35)
            with col_btn2:
                current_plan = plan if ticker_detect else None
                if current_plan and current_plan.get("ticker"):
                    ticker_name = current_plan["ticker"]
                else:
                    ticker_match = re.search(r'\b[A-Z]{3,4}\b', response_text)
                    ticker_name = ticker_match.group(0) if ticker_match else "STOCK"
                components.html(render_pdf_button(response_text, ticker_name, dict_dfs, current_plan), height=35)

            if chart_data_to_save is not None:
                st.line_chart(chart_data_to_save)

            new_msg = {"role": "assistant", "content": response_text}
            if chart_data_to_save is not None:
                new_msg["chart"] = chart_data_to_save
            new_msg["trade_plan"] = plan if ticker_detect else None
            st.session_state.messages.append(new_msg)
