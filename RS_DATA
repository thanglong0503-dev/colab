import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from vnstock import listing_companies, stock_historical_data
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# CẤU HÌNH PHỄU LỌC (GIÁM ĐỐC CÓ THỂ TỰ CHỈNH)
# ==========================================
MIN_LIQUIDITY = 1.0  # Tối thiểu 1 tỷ VNĐ/phiên
MIN_PRICE = 2.0      # Tối thiểu giá 2,000 VNĐ
SHEET_NAME = "LINANCE_DB"
CREDENTIALS_FILE = "credentials.json"
MAX_WORKERS = 10

def get_google_sheet(worksheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(worksheet_name)

def process_ticker(ticker, industry, start_date, end_date):
    try:
        df = stock_historical_data(symbol=ticker, start_date=start_date, end_date=end_date, resolution='1D', type='stock')
        if df is None or len(df) < 50: return None
        
        close = df['close']
        current_price = close.iloc[-1]
        
        # --- TẦNG 1 & 2: LỌC THANH KHOẢN VÀ GIÁ ---
        avg_vol = df['volume'].tail(20).mean()
        avg_value = (avg_vol * current_price) / 1e6 # Đơn vị: Triệu đồng
        
        if avg_value < (MIN_LIQUIDITY * 1000) or current_price < MIN_PRICE:
            return None # Loại bỏ ngay lập tức nếu là "rác"

        # --- TẦNG 3: LỌC "ZOMBIE" (Mã không giao dịch) ---
        zero_vol_days = (df['volume'].tail(20) == 0).sum()
        if zero_vol_days > 3: return None

        # --- TÍNH TOÁN DỮ LIỆU TINH KHIẾT ---
        perf_1m = (current_price - close.iloc[-22]) / close.iloc[-22]
        perf_3m = (current_price - close.iloc[-66]) / close.iloc[-66] if len(close) >= 66 else perf_1m
        
        # Điểm kỹ thuật nhanh
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()
        score = 0
        if current_price > ma20: score += 1
        if current_price > ma50: score += 1
        if ma20 > ma50: score += 1
        if current_price > close.iloc[-5]: score += 1 # Giá cao hơn 1 tuần trước
        if avg_value > (df['volume'].shift(1).tail(20).mean() * close.shift(1).tail(20).mean() / 1e6): score += 1 # Tiền đang vào

        return {
            "Mã CK": ticker,
            "Ngành": industry,
            "Giá": current_price,
            "RS_1M_Raw": perf_1m,
            "RS_3M_Raw": perf_3m,
            "Điểm_KT": score,
            "Thanh_Khoản_Tỷ": round(avg_value / 1000, 2)
        }
    except:
        return None

def main():
    print(f"🚀 Khởi động Phễu lọc LINANCE (Min Liquidity: {MIN_LIQUIDITY} tỷ)...")
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
    if df_final.empty:
        print("❌ Không tìm thấy mã nào khớp phễu lọc!")
        return

    # Xếp hạng RS trên tập dữ liệu đã lọc sạch
    df_final['RS_1M'] = (df_final['RS_1M_Raw'].rank(pct=True) * 99).astype(int) + 1
    df_final['RS_3M'] = (df_final['RS_3M_Raw'].rank(pct=True) * 99).astype(int) + 1
    
    # Phân tích ngành dựa trên mã chất lượng
    df_ind = df_final.groupby('Ngành').agg({'RS_1M': 'mean', 'Điểm_KT': 'mean', 'Mã CK': 'count'}).reset_index()
    df_ind.columns = ['Ngành', 'RS_TB', 'Điểm_KT_TB', 'Số_Mã']
    df_ind['Xu_Hướng'] = df_ind['Điểm_KT_TB'].apply(lambda x: "TÍCH CỰC" if x >= 3.0 else ("TRUNG TÍNH" if x >= 1.5 else "YẾU"))
    df_ind['Top_Ngành'] = df_ind['RS_TB'].apply(lambda x: "TOP" if x >= df_ind['RS_TB'].quantile(0.8) else "")
    df_ind = df_ind.round(1).sort_values(by='RS_TB', ascending=False)

    # Đẩy lên Sheet
    print(f"☁️ Đã lọc còn {len(df_final)} mã chất lượng. Đang upload...")
    ws_rs = get_google_sheet("RS_DATA")
    ws_rs.clear()
    df_rs_up = df_final[['Mã CK', 'Ngành', 'RS_1M', 'RS_3M', 'Điểm_KT', 'Thanh_Khoản_Tỷ', 'Giá']]
    ws_rs.update([df_rs_up.columns.values.tolist()] + df_rs_up.values.tolist())
    
    ws_ind = get_google_sheet("INDUSTRY_DATA")
    ws_ind.clear()
    ws_ind.update([df_ind.columns.values.tolist()] + df_ind.values.tolist())
    print("✅ HOÀN TẤT!")

if __name__ == "__main__":
    main()
