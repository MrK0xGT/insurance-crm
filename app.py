
import streamlit as st
import pandas as pd
import bcrypt
from supabase import create_client, Client
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
import urllib.parse
import time

# --- 把這段貼在你的 app.py 最上面 ---
st.markdown("""
    <style>
        /* 隱藏右上角的選單 (漢堡選單) */
        #MainMenu {visibility: hidden;}
        
        /* 隱藏頁尾 (Made with Streamlit) */
        footer {visibility: hidden;}
        
        /* 隱藏最上面的彩條與 GitHub 圖示 */
        header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)
# ----------------------------------
# --- 1. 初始化設定與安全性 ---
st.set_page_config(page_title="專業保險管家 CRM", page_icon="🛡️", layout="wide")

# 從 Secrets 讀取設定
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    # 必須是 32 url-safe base64-encoded bytes
    ENCRYPTION_KEY = st.secrets["general"]["encryption_key"]
except Exception as e:
    st.error("❌ 設定檔讀取失敗！請檢查 .streamlit/secrets.toml 是否設定正確。")
    st.stop()

# 初始化 Supabase
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# 初始化加密器
cipher_suite = Fernet(ENCRYPTION_KEY)

# --- 2. 核心功能函數 (Helper Functions) ---

# 加密與解密
def encrypt_text(text: str) -> str:
    if not text: return ""
    return cipher_suite.encrypt(text.encode()).decode()

def decrypt_text(text: str) -> str:
    try:
        return cipher_suite.decrypt(text.encode()).decode()
    except:
        return "[解密失敗]"

# 密碼處理 (Bcrypt)
def hash_password(password: str) -> str:
    # 產生 Salt 並雜湊，回傳字串儲存
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

# Google 行事曆連結生成
def generate_calendar_link(client_name, expiry_date_str):
    try:
        exp_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
        rem_date = exp_date - timedelta(days=30) # 提早30天
        
        start = rem_date.strftime("%Y%m%d")
        end = (rem_date + timedelta(days=1)).strftime("%Y%m%d")
        
        title = f"續保提醒：{client_name}"
        details = f"客戶 {client_name} 保險即將於 {expiry_date_str} 到期，請準備續保文件。"
        
        base_url = "https://calendar.google.com/calendar/render"
        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{start}/{end}",
            "details": details
        }
        return f"{base_url}?{urllib.parse.urlencode(params)}"
    except:
        return "#"

# --- 3. 資料庫操作函數 (CRUD) ---

def register_user(username, name, password):
    """註冊新業務員"""
    # 檢查帳號是否存在
    existing = supabase.table("users").select("username").eq("username", username).execute()
    if existing.data:
        return False, "帳號已存在"
    
    # 寫入資料庫
    pw_hash = hash_password(password)
    data = {"username": username, "full_name": name, "password_hash": pw_hash}
    try:
        supabase.table("users").insert(data).execute()
        return True, "註冊成功！請登入"
    except Exception as e:
        return False, f"註冊失敗: {str(e)}"

def login_user(username, password):
    """登入驗證"""
    response = supabase.table("users").select("*").eq("username", username).execute()
    if not response.data:
        return False, None
    
    user_data = response.data[0]
    if check_password(password, user_data["password_hash"]):
        return True, user_data
    else:
        return False, None

def add_client(agent_user, name, plate, phone, expiry, notes):
    """新增加密客戶資料"""
    enc_name = encrypt_text(name)
    enc_plate = encrypt_text(plate)
    
    payload = {
        "agent_username": agent_user,
        "encrypted_name": enc_name,
        "encrypted_plate": enc_plate,
        "phone_number": phone,
        "expiry_date": str(expiry),
        "notes": notes
    }
    try:
        supabase.table("clients").insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

def get_clients(agent_user):
    """讀取並解密客戶資料"""
    try:
        # RLS 邏輯：只抓取 agent_username 等於當前使用者的資料
        response = supabase.table("clients").select("*").eq("agent_username", agent_user).order("expiry_date").execute()
        data = response.data
        
        if not data:
            return pd.DataFrame()

        processed_data = []
        for row in data:
            processed_data.append({
                "ID": row["id"],
                "姓名": decrypt_text(row["encrypted_name"]), # 解密
                "車牌": decrypt_text(row["encrypted_plate"]), # 解密
                "電話": row["phone_number"],
                "到期日": row["expiry_date"],
                "備註": row["notes"]
            })
        return pd.DataFrame(processed_data)
    except Exception as e:
        st.error(f"讀取失敗: {e}")
        return pd.DataFrame()

def delete_client(client_id):
    supabase.table("clients").delete().eq("id", client_id).execute()

# --- 4. 介面邏輯 (UI) ---

def main():
    # Session State 初始化
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_info"] = {}

    # --- 登入前畫面 ---
    if not st.session_state["logged_in"]:
        st.header("🛡️ 保險業務 CRM 系統")
        
        tab1, tab2 = st.tabs(["🔑 登入", "📝 註冊新帳號"])
        
        with tab1:
            with st.form("login_form"):
                u_name = st.text_input("帳號 (Username)")
                p_word = st.text_input("密碼", type="password")
                submit = st.form_submit_button("登入")
                
                if submit:
                    success, user_data = login_user(u_name, p_word)
                    if success:
                        st.session_state["logged_in"] = True
                        st.session_state["user_info"] = user_data
                        st.success("登入成功！")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("帳號或密碼錯誤")

        with tab2:
            st.warning("⚠️ 新註冊的帳號將獨立擁有自己的資料庫空間，無法查看其他人的資料。")
            with st.form("signup_form"):
                new_u = st.text_input("設定帳號")
                new_n = st.text_input("您的姓名")
                new_p = st.text_input("設定密碼", type="password")
                new_p2 = st.text_input("確認密碼", type="password")
                reg_submit = st.form_submit_button("註冊")
                
                if reg_submit:
                    if new_p != new_p2:
                        st.error("兩次密碼不符")
                    elif len(new_p) < 6:
                        st.error("密碼長度需大於 6 位數")
                    elif new_u and new_n:
                        ok, msg = register_user(new_u, new_n, new_p)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.error("請填寫完整資訊")

    # --- 登入後畫面 ---
    else:
        user = st.session_state["user_info"]
        
        # 側邊欄
        with st.sidebar:
            st.title(f"👋 歡迎，{user['full_name']}")
            st.info(f"帳號：{user['username']}")
            if st.button("登出"):
                st.session_state["logged_in"] = False
                st.session_state["user_info"] = {}
                st.rerun()
            st.divider()
            st.markdown("🔒 **資料安全連線中**\n\n您的資料在傳輸與儲存時皆經過加密處理。")

        # 主畫面
        st.title("💼 客戶管理儀表板")
        
        # 功能分頁
        action_tab, list_tab = st.tabs(["➕ 新增客戶", "📋 客戶名單與提醒"])
        
        with action_tab:
            st.subheader("建立新保單資料")
            with st.form("add_client_form"):
                col1, col2 = st.columns(2)
                with col1:
                    c_name = st.text_input("客戶姓名 (將加密)")
                    c_phone = st.text_input("電話號碼")
                    c_expiry = st.date_input("保險到期日")
                with col2:
                    c_plate = st.text_input("車牌號碼 (將加密)")
                    c_notes = st.text_area("備註 (車型、險種需求...)")
                
                submitted = st.form_submit_button("🔒 加密並儲存")
                
                if submitted:
                    if c_name and c_plate:
                        with st.spinner("正在加密並寫入雲端..."):
                            success = add_client(user["username"], c_name, c_plate, c_phone, c_expiry, c_notes)
                        if success:
                            st.success(f"已成功新增客戶：{c_name}")
                    else:
                        st.error("姓名與車牌為必填欄位")

        with list_tab:
            st.subheader("我的客戶列表")
            
            # 獲取資料
            df = get_clients(user["username"])
            
            if not df.empty:
                # 簡單的統計
                expiring_soon = len(df[pd.to_datetime(df["到期日"]) < pd.to_datetime("today") + pd.DateOffset(days=30)])
                if expiring_soon > 0:
                    st.warning(f"🔔 注意：有 {expiring_soon} 位客戶即將在 30 天內到期！")
                
                # 顯示資料表
                st.dataframe(df, use_container_width=True)
                
                st.markdown("---")
                st.subheader("⚡ 快速操作中心")
                
                # 以卡片形式顯示每個客戶的操作按鈕
                for idx, row in df.iterrows():
                    with st.expander(f"🚗 {row['姓名']} ({row['車牌']}) - 到期日: {row['到期日']}"):
                        col1, col2, col3 = st.columns([1, 1, 2])
                        
                        with col1:
                            # 魔法連結：加入 Google 日曆
                            cal_link = generate_calendar_link(row['姓名'], str(row['到期日']))
                            st.link_button("📅 加入行事曆", cal_link)
                            
                        with col2:
                            # 撥打電話 (注意：這通常在手機版網頁才有效)
                            if row['電話']:
                                st.markdown(f'<a href="tel:{row["電話"]}" style="text-decoration:none;"><button style="width:100%; padding: 0.5rem; background-color: #f0f2f6; border: 1px solid #dce4ef; border-radius: 8px;">📞 撥打電話</button></a>', unsafe_allow_html=True)
                        
                        with col3:
                            # 刪除功能
                            if st.button("🗑️ 刪除資料", key=f"del_{row['ID']}"):
                                delete_client(row['ID'])
                                st.warning("已刪除，請重新整理頁面。")
                                time.sleep(1)
                                st.rerun()
                        
                        # 顯示備註
                        if row['備註']:
                            st.info(f"📝 備註：{row['備註']}")

            else:
                st.info("尚無資料，請至「新增客戶」分頁建立資料。")

if __name__ == '__main__':

    main()

