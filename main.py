import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from vnstock import listing_companies, stock_historical_data, company_overview
from datetime import datetime, timedelta
from tqdm import tqdm
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

warnings.filterwarnings('ignore')

# ==========================================
# CẤU HÌNH HỆ THỐNG FINCEPT TERMINAL
# ==========================================
MIN_LIQUIDITY = 1.0  
MIN_PRICE = 2.0      
SHEET_NAME = "RS_DATA"
CREDENTIALS_FILE = "credentials.json"
MAX_WORKERS = 5 # Giữ ở mức 5 để không bị các hệ thống chặn vì DDoS

def get_google_sheet(worksheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(worksheet_name)

def process_ticker(ticker, industry, start_date, end_date):
    try:
        # 1. LẤY DỮ LIỆU HÀNH VI GIÁ TỪ VNSTOCK
        df = stock_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, resolution='1D', type='stock')
        if df is None or len(df) < 66: return None 
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        close_price = float(close.iloc[-1])
        avg_value = (volume.tail(20).mean() * close_price) / 1e6 
        
        # Lọc rác và thanh khoản
        if avg_value < (MIN_LIQUIDITY * 1000) or close_price < MIN_PRICE: return None 
        if (volume.tail(20) == 0).sum() > 3: return None

        # 2. TÍNH TOÁN CÁC CHỈ BÁO KỸ THUẬT NÂNG CAO BẰNG TAY (PANDAS)
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

        # 3. CHẤM ĐIỂM KỸ THUẬT (FORM TIÊU CHUẨN)
        score = 0
        score += 1 if close_price > ma5 else -1
        score += 1 if close_price > ma20 else -1
        score += 1 if ma5 > ma20 else -1
        score += 1 if rsi_val > 50 else -1
        score += 1 if mfi_val > 50 else -1
        score += 1 if macd_val > signal_val else -1
        score += 1 if k_val > d_val else -1
        score += 1 if close_price >= hhv10 else (-1 if close_price <= llv10 else 0)
        
        if score >= 4:
            tech_status = "KHẢ QUAN"
        elif score <= -4:
            tech_status = "TIÊU CỰC"
        else:
            tech_status = "TRUNG TÍNH"

        # 4. TỰ TÍNH TAY DỮ LIỆU CƠ BẢN TỪ COMPANY_OVERVIEW
        try:
            overview = company_overview(ticker) 
            out_share = float(overview['outstandingShare'].iloc[0]) 
            market_cap = round((out_share * close_price) / 1000, 1) # Vốn hóa
            
            pe = round(float(overview['pe'].iloc[0]), 2) if 'pe' in overview.columns else 0.0
            pb = round(float(overview['pb'].iloc[0]), 2) if 'pb' in overview.columns else 0.0
            roe = round(float(overview['roe'].iloc[0]) * 100, 2) if 'roe' in overview.columns else 0.0
            debt_equity = 0.0 # Bỏ qua tỷ lệ nợ
            
        except Exception as e:
            market_cap = pe = pb = roe = debt_equity = 0.0

        # 5. TÍNH SỨC MẠNH GIÁ (MOMENTUM)
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
            "MACD_Hist": round(macd_val - signal_val, 3)
        }
    except Exception as e:
        return None

def main():
    print("🚀 Khởi động FinceptTerminal Bot (Bản tính tay tự lực cánh sinh)...")
    df_companies = listing_companies(live=False)
    tickers_list = df_companies[['ticker', 'industry']].values.tolist()
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    
    raw_results = []
    # Khởi chạy đa luồng
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_ticker, t[0], t[1], start_date, end_date): t[0] for t in tickers_list}
        
        # Cơ chế chống kẹt: Quá 25s không phản hồi thì bỏ qua
        for future in tqdm(as_completed(futures), total=len(tickers_list)):
            try:
                res = future.result(timeout=25) 
                if res: raw_results.append(res)
            except concurrent.futures.TimeoutError:
                ticker = futures[future]
                print(f"⚠️ Bỏ qua mã {ticker} vì hết thời gian chờ!")
                continue
            except Exception:
                continue

    df_final = pd.DataFrame(raw_results)
    
    if not df_final.empty:
        # Chấm điểm RS (Percentile)
        df_final['RS_1M'] = (df_final['RS_1M'].rank(pct=True) * 99).astype(int) + 1
        df_final['RS_3M'] = (df_final['RS_3M'].rank(pct=True) * 99).astype(int) + 1
        
        # Cấu trúc 20 cột vũ khí
        final_columns = ['Mã CK', 'Ngành', 'RS_1M', 'RS_3M', 'Tech_Score', 'Trạng Thái', 'Thanh_Khoản_Tỷ', 'Giá', 
                         'Vốn Hóa', 'P/E', 'P/B', 'ROE (%)', 'Nợ/Vốn Chủ', 
                         'Open', 'High', 'Low', 'Volume', 'RSI_14', 'MFI_14', 'MACD_Hist']
        
        df_rs_up = df_final[final_columns].fillna("")
        
        print(f"☁️ Đang đẩy {len(df_rs_up)} mã chất lượng lên kho dữ liệu nội bộ...")
        ws_rs = get_google_sheet("RS_DATA")
        ws_rs.clear()
        ws_rs.update([df_rs_up.columns.values.tolist()] + df_rs_up.values.tolist())
        print("✅ HOÀN TẤT! Dữ liệu đã đổ bộ thành công lên Google Sheets.")
    else:
        print("❌ Lỗi: Không có dữ liệu đầu ra.")

if __name__ == "__main__":
    main()
