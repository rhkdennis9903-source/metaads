import streamlit as st
import datetime
import time
from utils import GoogleServices

# Initialize Google Services
def get_google_services():
    try:
        instance = GoogleServices()
        # st.sidebar.write(f"Debug: Service Instance Created: {type(instance)}")
        return instance
    except Exception as e:
        import traceback
        st.sidebar.error(f"Debug: Init Exception: {e}")
        st.sidebar.text(traceback.format_exc())
        return str(e)

import io

# Helper class to keep file in memory
class MemoryFile(io.BytesIO):
    def __init__(self, content, name, type):
        super().__init__(content)
        self.name = name
        self.type = type

def main():
    st.set_page_config(page_title="Meta 廣告上刊系統", page_icon="📝", layout="wide")
    
    # --- Sidebar ---
    with st.sidebar:
        st.caption("版本: v1.3.1 (修正上傳問題)")
        if st.session_state.get('case_id'):
            st.info(f"當前案件: {st.session_state.case_id}")
            if st.button("登出 / 切換案件"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            
            with st.expander("🔐 修改密碼"):
                with st.form("pwd_change_form"):
                    new_pwd = st.text_input("新密碼", type="password")
                    confirm_pwd = st.text_input("確認新密碼", type="password")
                    if st.form_submit_button("更新密碼"):
                        if new_pwd != confirm_pwd:
                            st.error("兩次輸入的密碼不一致")
                        elif not new_pwd:
                            st.error("密碼不能為空")
                        else:
                            services = get_google_services()
                            if services.update_password(st.session_state.email, new_pwd):
                                st.success("密碼更新成功！請重新登入。")
                                time.sleep(2)
                                for key in list(st.session_state.keys()):
                                    del st.session_state[key]
                                st.rerun()
                            else:
                                st.error("密碼更新失敗，請稍後再試。")

    st.title("Meta 廣告上刊資訊填寫")
    services = get_google_services()

    if not services or isinstance(services, str):
        st.error(f"無法連接 Google 服務。")
        if st.button("清除快取並重試"):
            st.cache_resource.clear()
            st.rerun()
        return

    # Session state initialization
    if 'step' not in st.session_state: st.session_state.step = 1
    if 'case_id' not in st.session_state: st.session_state.case_id = None
    if 'email' not in st.session_state: st.session_state.email = ""
    if 'doc_id' not in st.session_state: st.session_state.doc_id = None
    if 'ad_queue' not in st.session_state: st.session_state.ad_queue = []

    # Step 1: Email & Password Verification
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
                        try:
                            with st.spinner("正在確認雲端共享文件..."):
                                doc_id = services.ensure_doc_exists_and_share(case_id, email_input)
                                st.session_state.doc_id = doc_id
                        except Exception as e:
                            st.error(f"建立文件失敗: {e}")
                        
                        st.session_state.step = 2
                        st.success(f"登入成功！案件編號: {case_id}")
                        st.rerun()
                    else:
                        st.error("登入失敗：Email 或 密碼錯誤。")

    # Step 2: Ad Information Form (Batch Queue Mode)
    elif st.session_state.step == 2:
        st.header(f"Step 2: 編輯上刊清單 (案件: {st.session_state.case_id})")
        
        # --- A. 新增廣告表單 ---
        with st.expander("➕ 新增廣告素材到清單", expanded=len(st.session_state.ad_queue) == 0):
            with st.form("ad_entry_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    ad_name_id = st.text_input("廣告名稱/編號 (必填)")
                    # 修正處：UI 顯示改為 圖片名稱
                    image_name_id = st.text_input("圖片名稱 (必填)")
                    headline = st.text_input("廣告標題")
                with col2:
                    image_file = st.file_uploader("上傳廣告素材 (支援 PNG, JPG, GIF)", type=['png', 'jpg', 'jpeg', 'gif'])
                    landing_url = st.text_input("廣告到達網址")
                    main_copy = st.text_area("廣告主文案", height=100)
                
                add_button = st.form_submit_button("加入待上傳清單")
                
                if add_button:
                    if not ad_name_id or not image_name_id or not image_file:
                        st.error("請填寫必填欄位並上傳檔案")
                    else:
                        # Convert to MemoryFile immediately
                        file_content = image_file.read()
                        mem_file = MemoryFile(file_content, image_file.name, image_file.type)
                        
                        # 暫存到清單中
                        new_ad = {
                            'ad_name_id': ad_name_id,
                            'image_name_id': image_name_id,
                            'image_file': mem_file,
                            'headline': headline,
                            'main_copy': main_copy,
                            'landing_url': landing_url,
                            'fill_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        st.session_state.ad_queue.append(new_ad)
                        st.toast(f"✅ 已加入清單: {ad_name_id}")
                        st.rerun()

        # --- B. 顯示清單 & 批次處理 ---
        if st.session_state.ad_queue:
            st.subheader(f"📋 待上傳清單 (共 {len(st.session_state.ad_queue)} 則)")
            
            for idx, ad in enumerate(st.session_state.ad_queue):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 5, 1])
                    c1.write(f"**{ad['ad_name_id']}**")
                    # 修正處：預覽也顯示 圖片名稱
                    c1.caption(f"圖片名稱: {ad['image_name_id']}")
                    c2.text(f"文案預覽:\n{ad['main_copy'][:60]}...")
                    if c3.button("移除", key=f"remove_{idx}"):
                        st.session_state.ad_queue.pop(idx)
                        st.rerun()

            st.write("---")
            col_act1, col_act2 = st.columns([1, 4])
            
            if col_act1.button("🚀 開始批次上傳", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(st.session_state.ad_queue)
                
                success_count = 0
                doc_id = st.session_state.doc_id
                
                # 批次循環處理
                for i, ad_data in enumerate(st.session_state.ad_queue):
                    status_text.text(f"正在處理 ({i+1}/{total}): {ad_data['ad_name_id']}...")
                    try:
                        services.append_ad_data_to_doc(doc_id, ad_data, st.session_state.case_id)
                        success_count += 1
                    except Exception as e:
                        st.error(f"第 {i+1} 則處理失敗: {e}")
                    
                    progress_bar.progress((i + 1) / total)
                
                status_text.success(f"🎉 批次處理完成！成功上傳 {success_count} 則廣告。")
                
                # 發送彙總信
                try:
                    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
                    services.send_confirmation_email(
                        st.session_state.email, 
                        {'case_id': st.session_state.case_id, 'ad_name_id': f'批次提交({success_count}則)', 'fill_time': '剛剛'}, 
                        doc_url
                    )
                except:
                    pass
                
                st.session_state.ad_queue = []
                st.balloons()
                st.info("清單已處理完畢，您可以繼續新增或關閉視窗。")

            if col_act2.button("清空所有清單"):
                st.session_state.ad_queue = []
                st.rerun()
        else:
            st.info("目前清單中沒有廣告，請展開上方表單新增。")

if __name__ == "__main__":
    main()
