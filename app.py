import streamlit as st
import datetime
from utils import GoogleServices
# Initialize Google Services
# We cache this to avoid re-authenticating on every re-run
# Determine if cached or not - removing cache for now
def get_google_services():
    try:
        instance = GoogleServices()
        st.sidebar.write(f"Debug: Service Instance Created: {type(instance)}")
        return instance
    except Exception as e:
        import traceback
        st.sidebar.error(f"Debug: Init Exception: {e}")
        st.sidebar.text(traceback.format_exc())
        return str(e)
def main():
    st.set_page_config(page_title="Meta 廣告上刊系統", page_icon="📝")
    
    # --- Sidebar (Always show for debugging) ---
    with st.sidebar:
        # Debug info kept minimal or removed as per request "拿掉管理功能"
        # Letting standard debug info remains if needed, but removing the Admin Zone.
        st.caption("版本: v1.1.0")
    st.title("Meta 廣告上刊資訊填寫")
    services = get_google_services()
    # Debug: Print boolean evaluation
    # st.write(f"Debug Main: type(services)={type(services)}")
    # st.write(f"Debug Main: bool(services)={bool(services)}")
    # Check for service account
    if not services or isinstance(services, str):
        st.error(f"無法連接 Google 服務。")
        st.error(f"變數狀態: services={services}, type={type(services)}")
        if isinstance(services, str):
            st.error(f"錯誤詳情: {services}")
        
        if st.button("清除快取並重試"):
            st.cache_resource.clear()
            st.rerun()
            
        return
    # Sidebar Actions that require services (only if services exist)
    # Sidebar Actions removed
    # with st.sidebar:
    #    if st.button("檢查雲端空間 & 檔案"):
    # ...
    # Session state initialization
    if 'step' not in st.session_state:
        st.session_state.step = 1
    if 'case_id' not in st.session_state:
        st.session_state.case_id = None
    if 'email' not in st.session_state:
        st.session_state.email = ""
    if 'doc_id' not in st.session_state:
        st.session_state.doc_id = None
    # Step 1: Email Verification
    if st.session_state.step == 1:
        st.header("Step 1: 身份驗證")
        email_input = st.text_input("請輸入您的 Email (帳號)", value=st.session_state.email)
        password_input = st.text_input("請輸入密碼", type="password")
        
        if st.button("登入並查詢案件"):
            if not email_input or not password_input:
                st.warning("請輸入 Email 與 密碼")
            else:
                with st.spinner("驗證中..."):
                    case_id = services.verify_user(email_input, password_input)
                    if case_id:
                        st.session_state.case_id = case_id
                        st.session_state.email = email_input
                        
                        # Pre-check/Create Document immediately
                        try:
                            with st.spinner("正在確認雲端共享文件..."):
                                doc_id = services.ensure_doc_exists_and_share(case_id, email_input)
                                st.session_state.doc_id = doc_id
                        except Exception as e:
                            st.error(f"建立文件失敗: {e}")
                            # Optional: Fail hard or allow continue?
                            # For now, let's allow them to continue but they might face issues if doc_id is None
                        
                        st.session_state.step = 2
                        st.success(f"找到案件編號: {case_id}")
                        st.rerun()
                    else:
                        st.error("登入失敗：Email 或 密碼錯誤，或者找不到對應的案件編號。")
    # Step 2: Ad Information Form
    elif st.session_state.step == 2:
        st.header(f"Step 2: 填寫上刊資訊 (案件: {st.session_state.case_id})")
        
        with st.form("ad_submission_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                # fill_time removed as per request (auto-generated on submit)
                ad_name_id = st.text_input("廣告名稱/編號 (必填)")
                image_name_id = st.text_input("對應圖片名稱/編號 (必填)")
                headline = st.text_input("廣告標題")
            
            with col2:
                # Changed to File Uploader
                image_file = st.file_uploader("上傳廣告圖片 (必填)", type=['png', 'jpg', 'jpeg'])
                landing_url = st.text_input("廣告到達網址")
                main_copy = st.text_area("廣告主文案", height=150)
            submitted = st.form_submit_button("送出並建立文件")
            
            if submitted:
                if not ad_name_id or not image_name_id:
                    st.error("請填寫 '廣告名稱/編號' 與 '對應圖片名稱/編號'")
                elif not image_file:
                    st.error("請上傳廣告圖片")
                else:
                    try:
                        with st.spinner("處理中...建立/更新文件中..."):
                            # 1. Use existing Doc ID
                            doc_id = st.session_state.doc_id
                            
                            # Fallback if for some reason it's missing (e.g. dev restart)
                            if not doc_id:
                                doc_id = services.ensure_doc_exists_and_share(st.session_state.case_id, st.session_state.email)
                                st.session_state.doc_id = doc_id
                            
                            # 2. Prepare Data
                            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            ad_data = {
                                'fill_time': current_time,
                                'ad_name_id': ad_name_id,
                                'image_name_id': image_name_id,
                                'image_file': image_file, # Pass file object
                                'headline': headline,
                                'main_copy': main_copy,
                                'landing_url': landing_url
                            }
                            
                            # 3. Append Logic
                            block_name = services.append_ad_data_to_doc(doc_id, ad_data)
                            
                        st.success(f"成功! 資料已寫入文件。")
                        st.info(f"產生的廣告組合名稱: {block_name}")
                        st.info(f"文件 ID: {doc_id} (已分享給您)")
                        
                        # 4. Send Email Notification
                        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
                        admin_email = "rhk9903@gmail.com"
                        
                        try:
                            st.info("📨 正在寄送確認信...")
                            services.send_confirmation_email(st.session_state.email, ad_data, doc_url)
                            if st.session_state.email != admin_email:
                                services.send_confirmation_email(admin_email, ad_data, doc_url)
                            st.success(f"✅ 確認信已寄出！")
                        except Exception as e:
                            st.error(f"信件寄送失敗，但資料已存檔。錯誤: {e}")
                        
                        # Button removed to fix st.form error
                        st.info("您可以直接修改上方內容並再次送出。")
                            
                    except Exception as e:
                        st.error(f"發生錯誤: {e}")
        if st.button("回上一步 (重新查詢)"):
            st.session_state.step = 1
            st.session_state.case_id = None
            st.rerun()
if __name__ == "__main__":
    main()
