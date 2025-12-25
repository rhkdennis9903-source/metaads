import os
import hashlib
import re
import datetime
import json
import gspread
import base64
import requests
import io
import time
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import streamlit as st

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/gmail.send' 
]

MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1zXHavJqhOBq1-m_VR7sxMkeOHdXoD9EmQCEM1Nl816I/edit?usp=sharing"
ADMIN_EMAIL = "rhk9903@gmail.com"

class GoogleServices:
    def __init__(self, service_account_file='gen-lang-client-0057298651-12025f130563.json'):
        self.creds = None
        # st.sidebar.write("Debug: Initializing GoogleServices...")
        self.auth_mode = "service_account"
        self.email_map = None 
        
        # 憑證載入邏輯
        if "oauth" in st.secrets:
            try:
                oauth_info = st.secrets["oauth"]
                self.creds = UserCredentials(
                    None,
                    refresh_token=oauth_info["refresh_token"],
                    token_uri=oauth_info["token_uri"],
                    client_id=oauth_info["client_id"],
                    client_secret=oauth_info["client_secret"],
                    scopes=SCOPES
                )
                self.auth_mode = "oauth"
                # st.sidebar.success("Debug: Auth with OAuth Success!")
            except Exception as e:
                st.sidebar.error(f"Debug: OAuth Error {e}")
                raise e
        elif "gcp_service_account" in st.secrets:
            service_account_info = dict(st.secrets["gcp_service_account"])
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        elif "gcp_json" in st.secrets:
            service_account_info = json.loads(st.secrets["gcp_json"])
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        elif "private_key" in st.secrets:
            service_account_info = dict(st.secrets)
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        elif os.path.exists(service_account_file):
            self.creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
            
        if not self.creds:
            raise FileNotFoundError("Could not find valid credentials.")

        self.gc = gspread.authorize(self.creds)
        self.drive_service = build('drive', 'v3', credentials=self.creds)
        self.docs_service = build('docs', 'v1', credentials=self.creds)

    def verify_user(self, email, password):
        """驗證使用者並回傳 Case ID"""
        try:
            sh = self.gc.open_by_url(MASTER_SHEET_URL)
            worksheet = sh.get_worksheet(0)
            all_values = worksheet.get_all_values()
            if not all_values: return None
            
            # Fixed Column Mapping: Email=A(0), Password=AB(27), CaseID=B(1)
            email_col = 0
            case_id_col = 1
            pass_col = 27 
            
            for row in all_values[1:]:
                if len(row) <= max(email_col, pass_col): continue
                
                stored_password = row[pass_col].strip()
                hashed_password = hashlib.sha256(password.strip().encode()).hexdigest()
                
                # Check Email match first
                if row[email_col].strip().lower() == email.strip().lower():
                    # st.write(f"Debug: Email Matched! Sheet Pass: '{stored_password}' vs Input: '{password}'")
                    # Check Password (Hashed OR Plain Text)
                    if stored_password == hashed_password or stored_password == password.strip():
                        return str(row[case_id_col]).strip()
                    else:
                        st.error(f"Debug: 密碼不符。Excel內的密碼: '{stored_password}' vs 輸入密碼: '{password}' (雜湊: {hashed_password})")
            return None
        except Exception as e:
            st.error(f"Error validating user: {e}")
            return None

    def get_case_id_by_email(self, email):
        """舊版備援查詢"""
        try:
            sh = self.gc.open_by_url(MASTER_SHEET_URL)
            worksheet = sh.get_worksheet(0)
            all_values = worksheet.get_all_values()
            for row in all_values[1:]:
                if len(row) > 1 and row[1].strip() == email.strip():
                    return str(row[2]).strip()
            return None
        except Exception as e:
            st.error(f"Error reading Sheet: {e}")
            return None

    def update_password(self, email, new_password):
        """更新使用者密碼"""
        try:
            sh = self.gc.open_by_url(MASTER_SHEET_URL)
            worksheet = sh.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            # Fixed Column Mapping: Email=A(0), Password=AB(27)
            email_col = 0
            pass_col = 27
            
            # Find row to update
            cell_row = -1
            for idx, row in enumerate(all_values):
                if idx == 0: continue # Skip header
                # Ensure row has enough columns for Email check
                if len(row) > email_col and row[email_col].strip().lower() == email.strip().lower():
                    cell_row = idx + 1 # 1-based index
                    break
            
            if cell_row != -1:
                hashed_password = hashlib.sha256(new_password.strip().encode()).hexdigest()
                # Ensure we are updating the correct column. 
                # gspread update_cell takes (row, col) 1-based.
                # pass_col is 27 (0-based) -> 28 (1-based) which is Column AB
                worksheet.update_cell(cell_row, pass_col + 1, hashed_password) 
                return True
            return False
            
        except Exception as e:
            st.error(f"Error updating password: {e}")
            return False

    def find_file_in_drive(self, name, parent_id=None):
        query = f"name = '{name}' and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id: query += f" and '{parent_id}' in parents"
        results = self.drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        return files[0]['id'] if files else None

    def find_folder_in_drive(self, name, parent_id=None):
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id: query += f" and '{parent_id}' in parents"
        results = self.drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        return files[0]['id'] if files else None

    def get_root_folder_id(self):
        return self.find_folder_in_drive("Meta_Ads_System")

    def create_folder(self, name, parent_id=None):
        file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id: file_metadata['parents'] = [parent_id]
        file = self.drive_service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return file.get('id')

    def create_doc(self, title, folder_id=None):
        doc_metadata = {'name': title, 'mimeType': 'application/vnd.google-apps.document'}
        if folder_id: doc_metadata['parents'] = [folder_id]
        doc = self.drive_service.files().create(body=doc_metadata, fields='id', supportsAllDrives=True).execute()
        return doc.get('id')

    def share_file(self, file_id, email, role='writer'):
        user_permission = {'type': 'user', 'role': role, 'emailAddress': email}
        self.drive_service.permissions().create(fileId=file_id, body=user_permission, fields='id').execute()

    def ensure_doc_exists_and_share(self, case_id, customer_email):
        doc_name = f"{case_id}_meta廣告上刊文件"
        existing_doc_id = self.find_file_in_drive(doc_name)
        if existing_doc_id: return existing_doc_id
        
        root_id = self.get_root_folder_id()
        if not root_id:
            raise FileNotFoundError("請先在雲端建立 'Meta_Ads_System' 資料夾並分享給機器人帳號。")
        
        folder_name = str(case_id).split("_")[0] if "_" in str(case_id) else str(case_id)
        folder_id = self.find_folder_in_drive(folder_name, parent_id=root_id)
        if not folder_id:
            folder_id = self.create_folder(folder_name, parent_id=root_id)
        
        new_doc_id = self.create_doc(doc_name, folder_id=folder_id)
        self.share_file(new_doc_id, customer_email)
        self.share_file(new_doc_id, ADMIN_EMAIL)
        return new_doc_id

    def upload_image_to_drive(self, image_file, filename, parent_id, folder_name="Images_圖檔"):
        """上傳檔案 (支援 GIF/JPG/PNG) 到雲端"""
        try:
            img_folder_id = self.find_folder_in_drive(folder_name, parent_id=parent_id)
            if not img_folder_id:
                img_folder_id = self.create_folder(folder_name, parent_id=parent_id)
            
            image_file.seek(0)
            # 自動偵測 MIME 類型
            mime_type = image_file.type if hasattr(image_file, 'type') else 'image/jpeg'
            
            file_metadata = {'name': filename, 'parents': [img_folder_id]}
            media = MediaIoBaseUpload(image_file, mimetype=mime_type, resumable=True)
            
            new_file = self.drive_service.files().create(
                body=file_metadata, media_body=media,
                fields='id, webContentLink, thumbnailLink',
                supportsAllDrives=True
            ).execute()
            
            self.drive_service.permissions().create(
                fileId=new_file.get('id'), body={'role': 'reader', 'type': 'anyone'}
            ).execute()
            
            time.sleep(1) # 等待權限生效
            
            thumb_link = new_file.get('thumbnailLink')
            if thumb_link:
                return thumb_link.replace('=s220', '=s1600'), new_file.get('webContentLink')
            return new_file.get('webContentLink'), new_file.get('webContentLink')
        except Exception as e:
            st.warning(f"⚠️ 素材上傳失敗: {e}")
            return None, None

    def append_ad_data_to_doc(self, doc_id, ad_data, case_id):
        """將廣告資料寫入 Google Doc，標題粗體且內容換行"""
        block_name = f"{ad_data.get('ad_name_id')}_{ad_data.get('image_name_id')}"
        
        try:
            doc_info = self.drive_service.files().get(fileId=doc_id, fields='parents', supportsAllDrives=True).execute()
            parent_id = doc_info.get('parents', [None])[0]
        except:
            parent_id = None

        # --- 素材處理 ---
        image_file = ad_data.get('image_file')
        image_insert_link = None
        if image_file and parent_id:
            ext = os.path.splitext(image_file.name)[1].lower()
            if not ext:
                mime_map = {'image/gif': '.gif', 'image/png': '.png', 'image/jpeg': '.jpg'}
                ext = mime_map.get(getattr(image_file, 'type', ''), '.jpg')
            
            final_filename = f"{ad_data.get('image_name_id')}{ext}"
            customer_prefix = str(case_id).split("_")[0] if "_" in str(case_id) else str(case_id)
            thumb, web = self.upload_image_to_drive(image_file, final_filename, parent_id, folder_name=f"{customer_prefix}_img")
            ad_data['image_url'] = web
            image_insert_link = thumb

        # --- 建立資料對應表 (標題已修正) ---
        data_fields = [
            ("【廣告組合 ID】", block_name),
            ("【送出時間】", ad_data.get('fill_time', '')),
            ("【廣告名稱】", ad_data.get('ad_name_id', '')),
            ("【圖片名稱】", ad_data.get('image_name_id', '')), # 修正處
            ("【素材網址】", ad_data.get('image_url', '')),
            ("【廣告標題】", ad_data.get('headline', '')),
            ("【到達網址】", ad_data.get('landing_url', '')),
            ("【廣告文案】", ad_data.get('main_copy', ''))
        ]

        # 組合字串並計算粗體位置
        full_text = ""
        bold_ranges = []
        current_offset = 0

        for label, value in data_fields:
            line_label = f"{label}\n"
            line_value = f"{value}\n\n"
            
            bold_ranges.append({
                'start': current_offset,
                'end': current_offset + len(label)
            })
            
            full_text += line_label + line_value
            current_offset += len(line_label) + len(line_value)

        # --- 寫入表格 ---
        self.docs_service.documents().batchUpdate(
            documentId=doc_id, 
            body={'requests': [{'insertTable': {'rows': 1, 'columns': 2, 'location': {'index': 1}}}]}
        ).execute()
        
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        # 尋找剛插入的表格 (假設在最前面)
        table = None
        for el in doc.get('body').get('content'):
             if 'table' in el:
                 table = el['table']
                 break
        
        if table:
            left_idx = table['tableRows'][0]['tableCells'][0]['content'][0]['startIndex']
            right_idx = table['tableRows'][0]['tableCells'][1]['content'][0]['startIndex']
            
            batch_reqs = []
            
            # 插入圖片
            if image_insert_link:
                batch_reqs.append({
                    'insertInlineImage': {
                        'uri': image_insert_link,
                        'location': {'index': right_idx},
                        'objectSize': {'width': {'magnitude': 180, 'unit': 'PT'}}
                    }
                })
            
            # 插入文字
            batch_reqs.append({
                'insertText': {'location': {'index': left_idx}, 'text': full_text}
            })
            
            # 套用粗體
            for r in bold_ranges:
                batch_reqs.append({
                    'updateTextStyle': {
                        'range': {
                            'startIndex': left_idx + r['start'],
                            'endIndex': left_idx + r['end']
                        },
                        'textStyle': {'bold': True},
                        'fields': 'bold'
                    }
                })
                
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': batch_reqs}).execute()
        
        return block_name

    def send_confirmation_email(self, to_email, ad_data, doc_url):
        if self.auth_mode != "oauth":
            st.info("ℹ️ Service Account 模式不支援寄信。")
            return False
        try:
            service = build('gmail', 'v1', credentials=self.creds)
            case_id = ad_data.get('case_id', 'N/A')
            msg_text = f"素材提交成功！\n案號: {case_id}\n廣告: {ad_data.get('ad_name_id')}\n圖片名稱: {ad_data.get('image_name_id')}\n文件連結: {doc_url}"
            message = MIMEText(msg_text)
            message['to'] = to_email
            message['from'] = 'me'
            message['subject'] = f"✅ [{case_id}] 素材提交確認"
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            service.users().messages().send(userId='me', body={'raw': raw}).execute()
            return True
        except Exception as e:
            st.error(f"⚠️ Email 寄送失敗: {e}")
            return False
