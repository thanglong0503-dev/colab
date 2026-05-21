import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from vnstock import listing_companies, stock_historical_data
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# CẤU HÌNH PHỄU LỌC
# ==========================================
MIN_LIQUIDITY = 1.0  
MIN_PRICE = 2.0      
SHEET_NAME = "RS_DATA" # Tên file Google Sheets của Ngài
CREDENTIALS_FILE = "credentials.json"
MAX_WORKERS = 10

def get_google_sheet(worksheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(worksheet_name)

def process_ticker(ticker, industry, start_date, end_date):
    try:
        # Tải dữ liệu lịch sử từ vnstock
        df = stock_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, resolution='1D', type='stock')
        if df is None or len(df) < 66: return None 
        
        # --- BỘ LỌC OHLCV NÂNG CẤP CHO AI ---
        open_price = float(df['open'].iloc[-1])
        high_price = float(df['high'].iloc[-1])
        low_price = float(df['low'].iloc[-1])
        close_price = float(df['close'].iloc[-1])
        volume = float(df['volume'].iloc[-1])
        close = df['close']
        
        avg_vol = df['volume'].tail(20).mean()
        avg_value = (avg_vol * close_price) / 1e6 
        
        if avg_value < (MIN_LIQUIDITY * 1000) or close_price < MIN_PRICE:
            return None 

        zero_vol_days = (df['volume'].tail(20) == 0).sum()
        if zero_vol_days > 3: return None

        # --- TÍNH TOÁN SỨC MẠNH ---
        perf_1m = (close_price - close.iloc[-22]) / close.iloc[-22]
        perf_3m = (close_price - close.iloc[-66]) / close.iloc[-66]
        
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()
        score = 0
        if close_price > ma20: score += 1
        if close_price > ma50: score += 1
        if ma20 > ma50: score += 1
        if close_price > close.iloc[-5]: score += 1 
        if avg_value > (df['volume'].shift(1).tail(20).mean() * close.shift(1).tail(20).mean() / 1e6): score += 1 

        # --- TÍNH TOÁN RSI & MACD CHO AI AGENT ---
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
        loss = -delta.clip(upper=0).rolling(window=14, min_periods=1).mean()
        rs = gain / loss
        rsi_14 = 100 - (100 / (1 + rs))
        latest_rsi = round(float(rsi_14.iloc[-1]), 2) if not pd.isna(rsi_14.iloc[-1]) else 50.0

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = round(float((macd - signal).iloc[-1]), 3)

        return {
            "Mã CK": ticker,
            "Ngành": industry,
            "RS_1M": perf_1m,
            "RS_3M": perf_3m,
            "Điểm_KT": score,
            "Thanh_Khoản_": round(avg_value / 1000, 2),
            "Giá": close_price,
            # Các cột vũ khí mới
            "Open": open_price,
            "High": high_price,
            "Low": low_price,
            "Volume": volume,
            "RSI_14": latest_rsi,
            "MACD_Hist": macd_hist
        }
    except:
        return None

def main():
    print("🚀 Khởi động Phễu lọc FinceptTerminal (Bản nâng cấp AI)...")
    df_companies = listing_companies(live=False)
    tickers_list = df_companies[['ticker', 'industry']].values.tolist()
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    
    raw_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_ticker, t[0], t[1], start_date, end_date) for t in tickers_list]
        for future in tqdm(as_completed(futures), total=len(tickers_list)):
            res = future.result()
            if res: raw_results.append(res)

    df_final = pd.DataFrame(raw_results)
    
    # Xếp hạng RS 
    df_final['RS_1M'] = (df_final['RS_1M'].rank(pct=True) * 99).astype(int) + 1
    df_final['RS_3M'] = (df_final['RS_3M'].rank(pct=True) * 99).astype(int) + 1
    
    # Cấu trúc xuất file đầy đủ
    final_columns = ['Mã CK', 'Ngành', 'RS_1M', 'RS_3M', 'Điểm_KT', 'Thanh_Khoản_', 'Giá', 
                     'Open', 'High', 'Low', 'Volume', 'RSI_14', 'MACD_Hist']
    df_rs_up = df_final[final_columns].fillna("")
    
    # Đẩy lên Sheet
    print(f"☁️ Đã lọc còn {len(df_rs_up)} mã chất lượng. Đang đẩy lên Google Sheets...")
    ws_rs = get_google_sheet("RS_DATA") # Đẩy vào tab RS_DATA
    ws_rs.clear()
    ws_rs.update([df_rs_up.columns.values.tolist()] + df_rs_up.values.tolist())
    print("✅ HOÀN TẤT! Dữ liệu đã sẵn sàng cho hệ thống AI.")

if __name__ == "__main__":
    main()
