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
        # 1. LẤY DỮ LIỆU HÀNH VI GIÁ TỪ VNSTOCK (Vẫn mượt)
        df = stock_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, resolution='1D', type='stock')
        if df is None or len(df) < 66: return None 
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        close_price = float(close.iloc[-1])
        vol_last_20 = volume.tail(20)
        avg_value = (vol_last_20.mean() * close_price) / 1e6 
        
        if avg_value < (MIN_LIQUIDITY * 1000) or close_price < MIN_PRICE: return None 
        if (vol_last_20 == 0).sum() > 3: return None

        # --- TÍNH TOÁN ĐỘT BIẾN KHỐI LƯỢNG ---
        current_vol = float(volume.iloc[-1])
        avg_vol_20 = float(vol_last_20.mean())
        surge_ratio = round((current_vol / avg_vol_20) * 100, 2) if avg_vol_20 > 0 else 0.0

        # 2. CHẤM ĐIỂM KỸ THUẬT
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

        score = 0
        score += 1 if close_price > ma5 else -1
        score += 1 if close_price > ma20 else -1
        score += 1 if ma5 > ma20 else -1
        score += 1 if rsi_val > 50 else -1
        score += 1 if mfi_val > 50 else -1
        score += 1 if macd_val > signal_val else -1
        score += 1 if k_val > d_val else -1
        score += 1 if close_price >= hhv10 else (-1 if close_price <= llv10 else 0)
        
        tech_status = "KHẢ QUAN" if score >= 4 else ("TIÊU CỰC" if score <= -4 else "TRUNG TÍNH")

        # ==========================================
        # 3. LẤY DỮ LIỆU CƠ BẢN TỪ YAHOO FINANCE (QUỐC TẾ)
        # ==========================================
        try:
            # Gắn đuôi .VN để Yahoo hiểu đây là cổ phiếu Việt Nam
            yf_ticker = yf.Ticker(f"{ticker}.VN")
            info = yf_ticker.info
            
            # Yahoo trả về marketCap bằng VND (rất lớn), ta chia cho 1 tỷ để ra Tỷ VNĐ
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
        # ==========================================
        # 5. TÍNH TOÁN ICHIMOKU KINKO HYO
        # ==========================================
        high_9 = high.rolling(window=9).max()
        low_9 = low.rolling(window=9).min()
        tenkan_sen = (high_9 + low_9) / 2

        high_26 = high.rolling(window=26).max()
        low_26 = low.rolling(window=26).min()
        kijun_sen = (high_26 + low_26) / 2

        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)
        
        high_52 = high.rolling(window=52).max()
        low_52 = low.rolling(window=52).min()
        senkou_span_b = ((high_52 + low_52) / 2).shift(26)

        # Trích xuất giá trị tại cây nến cuối cùng
        cur_tenkan = float(tenkan_sen.iloc[-1]) if not pd.isna(tenkan_sen.iloc[-1]) else 0.0
        cur_kijun = float(kijun_sen.iloc[-1]) if not pd.isna(kijun_sen.iloc[-1]) else 0.0
        cur_senkou_a = float(senkou_span_a.iloc[-1]) if not pd.isna(senkou_span_a.iloc[-1]) else 0.0
        cur_senkou_b = float(senkou_span_b.iloc[-1]) if not pd.isna(senkou_span_b.iloc[-1]) else 0.0

        max_cloud = max(cur_senkou_a, cur_senkou_b)
        min_cloud = min(cur_senkou_a, cur_senkou_b)

        # Dịch trạng thái mây
        if close_price > max_cloud: cloud_status = "TRÊN Mây (Tích cực)"
        elif close_price < min_cloud: cloud_status = "DƯỚI Mây (Tiêu cực)"
        else: cloud_status = "TRONG Mây (Đi ngang)"

        # Dịch tín hiệu cắt
        if cur_tenkan > cur_kijun: kumo_signal = "MUA MẠNH" if close_price > max_cloud else "MUA PHỤC HỒI"
        elif cur_tenkan < cur_kijun: kumo_signal = "BÁN MẠNH" if close_price < min_cloud else "BÁN CHỐT LỜI"
        else: kumo_signal = "LƯỠNG LỰ"

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
            "Volume": current_vol,
            "KL_TB_20": avg_vol_20,      # CỘT MỚI
            "Đột_Biến_KL": surge_ratio,  # CỘT MỚI (%)
            "RSI_14": round(rsi_val, 2),
            "MFI_14": round(mfi_val, 2),
            "MACD_Hist": round(macd_val - signal_val, 3),
            # --- CÁC CỘT MỚI CHO TA_DATA ---
            "Tenkan_sen": round(cur_tenkan, 2),
            "Kijun_sen": round(cur_kijun, 2),
            "Senkou_A": round(cur_senkou_a, 2),
            "Senkou_B": round(cur_senkou_b, 2),
            "Trạng Thái Mây": cloud_status,
            "Tín Hiệu Kumo": kumo_signal
        }
    except Exception as e:
        return None

def main():
    print("🚀 Khởi động FinceptTerminal Bot (Dùng lõi API Quốc tế Yahoo Finance)...")
    df_companies = listing_companies(live=False)
    tickers_list = df_companies[['ticker', 'industry']].values.tolist()
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    
    raw_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_ticker, t[0], t[1], start_date, end_date): t[0] for t in tickers_list}
        
        for future in tqdm(as_completed(futures), total=len(tickers_list)):
            try:
                res = future.result(timeout=30) # Yahoo đôi khi hơi chậm, nới lỏng ra 30s
                if res: raw_results.append(res)
            except concurrent.futures.TimeoutError:
                continue
            except Exception:
                continue

    df_final = pd.DataFrame(raw_results)
    
    if not df_final.empty:
        df_final['RS_1M'] = (df_final['RS_1M'].rank(pct=True) * 99).astype(int) + 1
        df_final['RS_3M'] = (df_final['RS_3M'].rank(pct=True) * 99).astype(int) + 1
        
        # 1. LỌC CỘT CHO RS_DATA ĐÃ BỔ SUNG KHỐI LƯỢNG
        final_rs_columns = ['Mã CK', 'Ngành', 'RS_1M', 'RS_3M', 'Tech_Score', 'Trạng Thái', 'Thanh_Khoản_Tỷ', 'Giá', 
                            'Vốn Hóa', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ', 
                            'Open', 'High', 'Low', 'Volume', 'KL_TB_20', 'Đột_Biến_KL', 'RSI_14', 'MFI_14', 'MACD_Hist']
        df_rs_up = df_final[final_rs_columns].fillna("")
        
        # 2. LỌC CỘT CHO TA_DATA (Phân tích kỹ thuật)
        final_ta_columns = ['Mã CK', 'Giá', 'Tenkan_sen', 'Kijun_sen', 'Senkou_A', 'Senkou_B', 'Trạng Thái Mây', 'Tín Hiệu Kumo']
        df_ta_up = df_final[final_ta_columns].fillna("")
        
        print(f"☁️ Đang đẩy {len(df_rs_up)} mã lên RS_DATA...")
        ws_rs = get_google_sheet("RS_DATA")
        ws_rs.clear()
        ws_rs.update([df_rs_up.columns.values.tolist()] + df_rs_up.values.tolist())
        
        print(f"☁️ Đang đẩy {len(df_ta_up)} mã lên TA_DATA...")
        ws_ta = get_google_sheet("TA_DATA")
        ws_ta.clear()
        ws_ta.update([df_ta_up.columns.values.tolist()] + df_ta_up.values.tolist())
        
        print("✅ HOÀN TẤT! Dữ liệu đã đổ bộ thành công lên cả 2 Sheet.")
    else:
        print("❌ Lỗi: Không có dữ liệu đầu ra.")

if __name__ == "__main__":
    main()
