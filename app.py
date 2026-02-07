import streamlit as st
import pandas as pd
import bcrypt
from supabase import create_client, Client
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
import urllib.parse
import time

# --- 1. 初始化與 UI 設定 (Apple-Style Clean UI) ---
st.set_page_config(
    page_title="專業保險管家 Pro",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed" # 隱藏側邊欄，讓畫面更寬廣
)

# 自定義 CSS：隱藏 Streamlit 原生選單與 Footer，讓它更像一個獨立 App
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stTabs [data-baseweb="tab-list"] {
            gap: 24px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            white-space: pre-wrap;
            border-radius: 4px 4px 0px 0px;
            font-size: 16px;
            font-weight: 600;
        }
        /* 讓 Metric 數值更顯眼 */
        div[data-testid="stMetricValue"] {
            font-size: 32px;
            color: #333;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. 安全性與連線 (保持不變的核心邏輯) ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    ENCRYPTION_KEY = st.secrets["general"]["encryption_key"]
except Exception as e:
    st.error("❌ 設定檔讀取失敗！請檢查 Secrets。")
    st.stop()

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()
cipher_suite = Fernet(ENCRYPTION_KEY)

# --- 3. 核心功能函數 ---

def encrypt_text(text: str) -> str:
    if not text: return ""
    return cipher_suite.encrypt(text.encode()).decode()

def decrypt_text(text: str) -> str:
    try:
        return cipher_suite.decrypt(text.encode()).decode()
    except:
        return "[解密失敗]"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def generate_calendar_link(client_name, expiry_date_str, insurance_type):
    try:
        exp_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
        rem_date = exp_date - timedelta(days=30)
        start = rem_date.strftime("%Y%m%d")
        end = (rem_date + timedelta(days=1)).strftime("%Y%m%d")
        title = f"續保提醒：{client_name} ({insurance_type})"
        details = f"客戶 {client_name} 的 {insurance_type} 即將於 {expiry_date_str} 到期。"
        base_url = "https://calendar.google.com/calendar/render"
        params = {"action": "TEMPLATE", "text": title, "dates": f"{start}/{end}", "details": details}
        return f"{base_url}?{urllib.parse.urlencode(params)}"
    except:
        return "#"

# --- 4. 資料庫操作 (CRUD) - 更新版 ---

def login_user(username, password):
    response = supabase.table("users").select("*").eq("username", username).execute()
    if not response.data: return False, None
    user_data = response.data[0]
    if check_password(password, user_data["password_hash"]):
        return True, user_data
    return False, None

def add_client(agent_user, name, plate, phone, expiry, insurance_type, notes):
    """新增資料：包含保險種類"""
    payload = {
        "agent_username": agent_user,
        "encrypted_name": encrypt_text(name),
        "encrypted_plate": encrypt_text(plate),
        "phone_number": phone,
        "expiry_date": str(expiry),
        "insurance_type": insurance_type, # 新增欄位
        "notes": notes
    }
    try:
        supabase.table("clients").insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

def get_clients(agent_user):
    """讀取資料：包含保險種類與狀態計算"""
    try:
        response = supabase.table("clients").select("*").eq("agent_username", agent_user).order("expiry_date").execute()
        data = response.data
        if not data: return pd.DataFrame()

        processed_data = []
        today = datetime.now().date()

        for row in data:
            expiry_date = datetime.strptime(row["expiry_date"], "%Y-%m-%d").date()
            days_left = (expiry_date - today).days
            
            # 狀態判斷
            if days_left < 0: status = "❌ 已過期"
            elif days_left <= 30: status = "⚠️ 即將到期"
            else: status = "✅ 正常"

            processed_data.append({
                "ID": row["id"],
                "狀態": status,
                "姓名": decrypt_text(row["encrypted_name"]),
                "保險種類": row.get("insurance_type", "未分類"), # 讀取新欄位
                "車牌": decrypt_text(row["encrypted_plate"]),
                "到期日": row["expiry_date"],
                "剩餘天數": days_left,
                "電話": row["phone_number"],
                "備註": row["notes"]
            })
        return pd.DataFrame(processed_data)
    except Exception as e:
        st.error(f"讀取失敗: {e}")
        return pd.DataFrame()

def delete_client(client_id):
    supabase.table("clients").delete().eq("id", client_id).execute()

# --- 5. 主程式 (UI/UX) ---

def main():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_info"] = {}

    # --- 登入畫面 (極簡風格) ---
    if not st.session_state["logged_in"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("<br><br><h1 style='text-align: center;'>🛡️ 保險管家 Pro</h1>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: gray;'>專為頂尖業務打造的客戶管理系統</p>", unsafe_allow_html=True)
            
            with st.container(border=True):
                st.subheader("歡迎回來")
                with st.form("login_form"):
                    u_name = st.text_input("帳號")
                    p_word = st.text_input("密碼", type="password")
                    if st.form_submit_button("立即登入", use_container_width=True):
                        success, user_data = login_user(u_name, p_word)
                        if success:
                            st.session_state["logged_in"] = True
                            st.session_state["user_info"] = user_data
                            st.rerun()
                        else:
                            st.error("帳號或密碼錯誤")

    # --- 登入後主畫面 (Dashboard Style) ---
    else:
        user = st.session_state["user_info"]
        
        # Header 區域
        st.markdown(f"### 👋 早安，{user['full_name']}")
        
        # 準備資料
        df = get_clients(user["username"])
        
        # 分頁設計
        tab_dashboard, tab_add, tab_settings = st.tabs(["📊 總覽與查詢", "➕ 新增客戶", "⚙️ 設定"])

        # === Tab 1: 儀表板 (Dashboard) ===
        with tab_dashboard:
            if not df.empty:
                # 1. 關鍵指標 (Key Metrics)
                total_clients = len(df)
                # 篩選 30 天內到期 (且未過期)
                urgent_clients = df[(df["剩餘天數"] <= 30) & (df["剩餘天數"] >= 0)]
                urgent_count = len(urgent_clients)
                expired_count = len(df[df["剩餘天數"] < 0])

                m1, m2, m3 = st.columns(3)
                m1.metric("總客戶數", f"{total_clients} 位", delta="累積名單")
                m2.metric("30天內到期", f"{urgent_count} 位", delta="需立即聯繫", delta_color="inverse")
                m3.metric("已過期", f"{expired_count} 位", delta="失效名單", delta_color="off")
                
                st.divider()

                # 2. 搜尋列
                search_term = st.text_input("🔍 搜尋客戶 (輸入姓名或車牌)", placeholder="Ex: 王小明 or ABC-1234")
                
                # 3. 資料展示 (Data Display)
                display_df = df.copy()
                if search_term:
                    display_df = display_df[
                        display_df["姓名"].str.contains(search_term) | 
                        display_df["車牌"].str.contains(search_term)
                    ]

                st.markdown("##### 📋 客戶詳細名單")
                
                # 使用 Pandas Style 進行高亮顯示 (紅色背景標示緊急)
                def highlight_urgent(row):
                    if 0 <= row["剩餘天數"] <= 30:
                        return ['background-color: #ffe6e6'] * len(row) # 淺紅色
                    elif row["剩餘天數"] < 0:
                        return ['color: #999999'] * len(row) # 灰色字體
                    return [''] * len(row)

                styled_df = display_df[["狀態", "姓名", "保險種類", "車牌", "到期日", "剩餘天數", "備註"]].style.apply(highlight_urgent, axis=1)

                # 互動式表格
                st.dataframe(
                    styled_df,
                    column_config={
                        "狀態": st.column_config.TextColumn("狀態", width="small"),
                        "剩餘天數": st.column_config.NumberColumn("剩餘天數 (天)", format="%d"),
                        "到期日": st.column_config.DateColumn("到期日", format="YYYY-MM-DD"),
                    },
                    use_container_width=True,
                    height=400
                )
                
                # 4. 快速操作區 (針對搜尋結果)
                if not display_df.empty:
                    st.markdown("###### ⚡ 快速操作")
                    selected_client_idx = st.selectbox("選擇客戶進行操作:", display_df.index, format_func=lambda x: f"{display_df.loc[x, '姓名']} ({display_df.loc[x, '車牌']})")
                    
                    if selected_client_idx is not None:
                        sel_row = display_df.loc[selected_client_idx]
                        col_a, col_b, col_c = st.columns([1, 1, 1])
                        
                        with col_a:
                            link = generate_calendar_link(sel_row['姓名'], str(sel_row['到期日']), sel_row['保險種類'])
                            st.link_button("📅 加入 Google 日曆", link, use_container_width=True)
                        
                        with col_b:
                            if sel_row['電話']:
                                st.markdown(f'<a href="tel:{sel_row["電話"]}" target="_self"><button style="width:100%; border:1px solid #ddd; background:white; padding:10px; border-radius:5px;">📞 撥打電話</button></a>', unsafe_allow_html=True)
                            else:
                                st.button("無電話", disabled=True, use_container_width=True)
                        
                        with col_c:
                            if st.button("🗑️ 刪除此資料", key=f"del_btn_{sel_row['ID']}", use_container_width=True, type="primary"):
                                delete_client(sel_row['ID'])
                                st.toast(f"已刪除 {sel_row['姓名']} 的資料", icon="🗑️")
                                time.sleep(1)
                                st.rerun()

            else:
                st.info("目前尚無資料，請至「新增客戶」分頁建立第一筆資料。")

        # === Tab 2: 新增客戶 (Add Client) ===
        with tab_add:
            st.markdown("#### 📝 建立新保單")
            with st.container(border=True):
                with st.form("add_client_form", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        c_name = st.text_input("客戶姓名", placeholder="真實姓名")
                        c_phone = st.text_input("電話號碼", placeholder="09xx-xxx-xxx")
                        # [NEW] 保險種類選單
                        c_type = st.selectbox("保險種類", ["強制險", "任意險", "兩者皆是(日期相同)"])
                    
                    with c2:
                        c_plate = st.text_input("車牌號碼", placeholder="ABC-1234")
                        c_expiry = st.date_input("保險到期日")
                        c_notes = st.text_area("備註事項", placeholder="例如：客戶偏好富邦產險...")
                    
                    st.caption("🔒 個資保護中：姓名與車牌將加密儲存")
                    submitted = st.form_submit_button("確認新增", use_container_width=True, type="primary")
                    
                    if submitted:
                        if c_name and c_plate:
                            success = add_client(user["username"], c_name, c_plate, c_phone, c_expiry, c_type, c_notes)
                            if success:
                                st.toast("✅ 資料新增成功！", icon="🎉")
                                time.sleep(1) # 給一點時間讓 user 看到 toast
                                st.rerun() # 重新整理以更新 dashboard 數據
                        else:
                            st.toast("❌ 姓名與車牌為必填欄位", icon="⚠️")

        # === Tab 3: 設定 (Settings) ===
        with tab_settings:
            st.markdown("#### ⚙️ 帳號設定")
            st.write(f"當前登入帳號：**{user['username']}**")
            
            st.divider()
            
            if st.button("登出系統", type="primary"):
                st.session_state["logged_in"] = False
                st.session_state["user_info"] = {}
                st.rerun()

if __name__ == '__main__':
    main()
