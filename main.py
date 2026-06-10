import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from vnstock import listing_companies, stock_historical_data
from datetime import datetime, timedelta
from tqdm import tqdm
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
import yfinance as yf # VŨ KHÍ MỚI: YAHOO FINANCE

warnings.filterwarnings('ignore')

# ==========================================
# CẤU HÌNH HỆ THỐNG FINCEPT TERMINAL
# ==========================================
MIN_LIQUIDITY = 1.0  
MIN_PRICE = 2.0      
SHEET_NAME = "RS_DATA"
CREDENTIALS_FILE = "credentials.json"
MAX_WORKERS = 5 

def get_google_sheet(worksheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(worksheet_name)

def process_ticker(ticker, industry, start_date, end_date):
    try:
        # 1. LẤY DỮ LIỆU HÀNH VI GIÁ TỪ VNSTOCK
        df = stock_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, resolution='1D', type='stock')
        
        # Đã trả về 66 để không loại bỏ nhầm cổ phiếu như nguyên bản của Ngài
        if df is None or len(df) < 66: return None 
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        close_price = float(close.iloc[-1])
        avg_value = (volume.tail(20).mean() * close_price) / 1e6 
        
        if avg_value < (MIN_LIQUIDITY * 1000) or close_price < MIN_PRICE: return None 
        if (volume.tail(20) == 0).sum() > 3: return None

        # ==========================================
        # 2. CHẤM ĐIỂM KỸ THUẬT (BẢN NÂNG CẤP TOÀN DIỆN)
        # ==========================================
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        hhv10 = high.rolling(10).max().iloc[-1]
        llv10 = low.rolling(10).min().iloc[-1]
        
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
        loss = -delta.clip(upper=0).rolling(window=14, min_periods=1).mean()
        rsi_val = float(100 - (100 / (1 + (gain / loss))).iloc[-1])

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_val = float(macd.iloc[-1])
        signal_val = float(signal.iloc[-1])

        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        k_percent = 100 * ((close - low14) / (high14 - low14))
        d_val = float(k_percent.rolling(3).mean().iloc[-1])
        k_val = float(k_percent.iloc[-1])

        typical_price = (high + low + close) / 3
        raw_money_flow = typical_price * volume
        pos_flow = np.where(typical_price > typical_price.shift(1), raw_money_flow, 0)
        neg_flow = np.where(typical_price < typical_price.shift(1), raw_money_flow, 0)
        mfi_val = float((100 - (100 / (1 + (pd.Series(pos_flow).rolling(14).sum() / pd.Series(neg_flow).rolling(14).sum())))).iloc[-1])

        # --- CHỈ BÁO BỔ SUNG: Xu hướng trung/dài hạn ---
        sma50 = float(close.rolling(50).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])

        # --- CHỈ BÁO BỔ SUNG: Bollinger Bands (20, 2) ---
        std20 = close.rolling(20).std()
        upper_band = float((close.rolling(20).mean() + 2 * std20).iloc[-1])
        lower_band = float((close.rolling(20).mean() - 2 * std20).iloc[-1])

        # --- CHỈ BÁO BỔ SUNG: Ichimoku Cloud (9, 26, 52) ---
        nine_period_high = high.rolling(window=9).max()
        nine_period_low = low.rolling(window=9).min()
        tenkan_sen = float(((nine_period_high + nine_period_low) / 2).iloc[-1])
        
        period26_high = high.rolling(window=26).max()
        period26_low = low.rolling(window=26).min()
        kijun_sen = float(((period26_high + period26_low) / 2).iloc[-1])
        
        senkou_span_a = float(((nine_period_high + nine_period_low) / 2 + (period26_high + period26_low) / 2) / 2).iloc[-1]
        
        period52_high = high.rolling(window=52).max()
        period52_low = low.rolling(window=52).min()
        senkou_span_b = float(((period52_high + period52_low) / 2).iloc[-1])

        # Xác định trạng thái so với mây Ichimoku
        if close_price > senkou_span_a and close_price > senkou_span_b:
            ichimoku_status = "Trên Mây"
        elif close_price < senkou_span_a and close_price < senkou_span_b:
            ichimoku_status = "Dưới Mây"
        else:
            ichimoku_status = "Trong Mây"

        # Cập nhật điểm kỹ thuật
        score = 0
        score += 1 if close_price > ma5 else -1
        score += 1 if close_price > ma20 else -1
        score += 1 if close_price > sma50 else -1 
        score += 1 if ma5 > ma20 else -1
        score += 1 if rsi_val > 50 else -1
        score += 1 if mfi_val > 50 else -1
        score += 1 if macd_val > signal_val else -1
        score += 1 if k_val > d_val else -1
        score += 1 if close_price >= hhv10 else (-1 if close_price <= llv10 else 0)
        
        tech_status = "KHẢ QUAN" if score >= 5 else ("TIÊU CỰC" if score <= -5 else "TRUNG TÍNH")

        # ==========================================
        # 3. LẤY DỮ LIỆU CƠ BẢN TỪ YAHOO FINANCE (QUỐC TẾ)
        # ==========================================
        try:
            yf_ticker = yf.Ticker(f"{ticker}.VN")
            info = yf_ticker.info
            market_cap = round(info.get('marketCap', 0) / 1e9, 1) 
            pe = round(info.get('trailingPE', 0), 2)
            pb = round(info.get('priceToBook', 0), 2)
            roe = round(info.get('returnOnEquity', 0) * 100, 2)
            debt_equity = round(info.get('debtToEquity', 0), 2)
            
        except Exception as e:
            market_cap = pe = pb = roe = debt_equity = 0.0

        # 4. TÍNH SỨC MẠNH GIÁ (MOMENTUM)
        perf_1m = (close_price - close.iloc[-22]) / close.iloc[-22]
        perf_3m = (close_price - close.iloc[-66]) / close.iloc[-66]

        return {
            "Mã CK": ticker,
            "Ngành": industry,
            "RS_1M": perf_1m,
            "RS_3M": perf_3m,
            "Tech_Score": score,
            "Trạng Thái": tech_status,
            "Thanh_Khoản_Tỷ": round(avg_value / 1000, 2),
            "Giá": close_price,
            "Vốn Hóa": market_cap,
            "P/E": pe,
            "P/B": pb,
            "ROE (%)": roe,
            "Nợ/Vốn Chủ": debt_equity,
            "Open": float(df['open'].iloc[-1]),
            "High": float(high.iloc[-1]),
            "Low": float(low.iloc[-1]),
            "Volume": float(volume.iloc[-1]),
            "RSI_14": round(rsi_val, 2),
            "MFI_14": round(mfi_val, 2),
            "MACD_Hist": round(macd_val - signal_val, 3),
            "SMA_50": round(sma50, 2),
            "SMA_200": round(sma200, 2),
            "BB_Upper": round(upper_band, 2),
            "BB_Lower": round(lower_band, 2),
            "Ichi_Trạng_Thái": ichimoku_status,
            "Tenkan": round(tenkan_sen, 2),
            "Kijun": round(kijun_sen, 2)
        }
    except Exception as e:
        return None

def main():
    print("🚀 Khởi động FinceptTerminal Bot (Dùng lõi API Quốc tế Yahoo Finance)...")
    df_companies = listing_companies(live=False)
    tickers_list = df_companies[['ticker', 'industry']].values.tolist()
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # Đã nâng lên 365 ngày (1 năm) để đảm bảo quét đủ >200 phiên giao dịch cho mọi mã
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d") 
    
    raw_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_ticker, t[0], t[1], start_date, end_date): t[0] for t in tickers_list}
        
        for future in tqdm(as_completed(futures), total=len(tickers_list)):
            try:
                res = future.result(timeout=30) 
                if res: raw_results.append(res)
            except concurrent.futures.TimeoutError:
                continue
            except Exception:
                continue

    df_final = pd.DataFrame(raw_results)
    
    if not df_final.empty:
        df_final['RS_1M'] = (df_final['RS_1M'].rank(pct=True) * 99).astype(int) + 1
        df_final['RS_3M'] = (df_final['RS_3M'].rank(pct=True) * 99).astype(int) + 1
        
        # Bổ sung các cột chỉ báo mới vào df đẩy lên Google Sheets
        final_columns = ['Mã CK', 'Ngành', 'RS_1M', 'RS_3M', 'Tech_Score', 'Trạng Thái', 'Thanh_Khoản_Tỷ', 'Giá', 
                         'Vốn Hóa', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ', 
                         'Open', 'High', 'Low', 'Volume', 'RSI_14', 'MFI_14', 'MACD_Hist',
                         'SMA_50', 'SMA_200', 'BB_Upper', 'BB_Lower', 'Ichi_Trạng_Thái', 'Tenkan', 'Kijun']
        
        df_rs_up = df_final[final_columns].fillna("")
        
        print(f"☁️ Đang đẩy {len(df_rs_up)} mã chất lượng lên kho dữ liệu nội bộ...")
        ws_rs = get_google_sheet("RS_DATA")
        ws_rs.clear()
        
        # BƯỚC QUYẾT ĐỊNH: Ép Google Sheets phải mở rộng đủ cột trước khi điền dữ liệu
        if ws_rs.col_count < len(df_rs_up.columns):
            ws_rs.add_cols(len(df_rs_up.columns) - ws_rs.col_count)
            
        # Đẩy dữ liệu lên sheet bắt đầu từ ô A1
        ws_rs.update([df_rs_up.columns.values.tolist()] + df_rs_up.values.tolist(), 'A1')
        print("✅ HOÀN TẤT! Dữ liệu đã đổ bộ thành công lên Google Sheets.")
    else:
        print("❌ Lỗi: Không có dữ liệu đầu ra.")

if __name__ == "__main__":
    main()
