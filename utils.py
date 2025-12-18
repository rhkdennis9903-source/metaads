import os
import re
import datetime
import json
import gspread
import base64
import requests
import io
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
# You might want to move these to environment variables or a config file
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1zXHavJqhOBq1-m_VR7sxMkeOHdXoD9EmQCEM1Nl816I/edit?usp=sharing"
ADMIN_EMAIL = "rhk9903@gmail.com"
# Column Indices (0-based) - Adjust these if the sheet structure changes
# Assuming simple structure for now, but in a real app, searching by header name is better.
# Let's try to find headers dynamically in the code.
class GoogleServices:
    def __init__(self, service_account_file='gen-lang-client-0057298651-12025f130563.json'):
        self.creds = None
        st.sidebar.write("Debug: Initializing GoogleServices...")
        self.auth_mode = "service_account" # Default
        self.email_map = None # Cache for sheet lookups
        
        # Priority 1: Check Streamlit Secrets (Nested Section)
        # 1. Try OAuth Refresh Token (Plan C: User Impersonation - Best for Personal Gmail)
        if "oauth" in st.secrets:
            st.sidebar.write("Debug: Found [oauth] config")
            try:
                oauth_info = st.secrets["oauth"]
                self.creds = UserCredentials(
                    None, # Initial access token is None
                    refresh_token=oauth_info["refresh_token"],
                    token_uri=oauth_info["token_uri"],
                    client_id=oauth_info["client_id"],
                    client_secret=oauth_info["client_secret"],
                    scopes=SCOPES
                )
                self.auth_mode = "oauth"
                st.sidebar.success("Debug: Auth with OAuth (User Mode) Success!")
            except Exception as e:
                st.sidebar.error(f"Debug: OAuth Error {e}")
                raise e
        # 2. Try Service Account (Plan A/B - Fallback)
        elif "gcp_service_account" in st.secrets:
            st.sidebar.write("Debug: Found [gcp_service_account]")
            service_account_info = dict(st.secrets["gcp_service_account"])
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        
        # Priority 1.5: Check Streamlit Secrets (Raw JSON String)
        # This is easier for users: just paste the whole JSON into a string variable
        elif "gcp_json" in st.secrets:
            st.sidebar.write("Debug: Found gcp_json")
            try:
                service_account_info = json.loads(st.secrets["gcp_json"])
                self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
                st.sidebar.success("Debug: loaded creds from gcp_json")
            except json.JSONDecodeError as e:
                st.sidebar.error(f"Debug: JSON Error {e}")
                raise ValueError(f"Invalid JSON in secrets 'gcp_json': {e}")
            except Exception as e:
                st.sidebar.error(f"Debug: Creds Error {e}")
                raise e
        # Priority 1.8: Check Streamlit Secrets (Root Level Fallback)
        elif "private_key" in st.secrets:
            st.sidebar.write("Debug: Found private_key (Root)")
            service_account_info = dict(st.secrets)
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        
        # Priority 2: Check Local File
        elif os.path.exists(service_account_file):
            st.sidebar.write("Debug: Found local file")
            self.creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        
        else:
            st.sidebar.write("Debug: Entering Fallback (Priority 3)")
            # Priority 3: Check for ANY json file that looks like a key in the current dir (Fallback)
            json_files = [f for f in os.listdir('.') if f.endswith('.json')]
            # Filter out client_secret.json as it is NOT a service account key
            json_files = [f for f in json_files if "client_secret" not in f]
            
            for f in json_files:
                try:
                    # quick check if it's a service account file
                    with open(f) as json_file:
                        data = json.load(json_file)
                        if data.get('type') == 'service_account':
                            self.creds = Credentials.from_service_account_file(f, scopes=SCOPES)
                            break
                except:
                    continue
            
        if not self.creds:
            raise FileNotFoundError("Could not find valid credentials (OAuth or Service Account).")
        self.gc = gspread.authorize(self.creds)
        
        # Initialize Sheet Object globally for caching
        try:
             self.sheet = self.gc.open_by_url(MASTER_SHEET_URL).sheet1
        except Exception as e:
             print(f"Warning: Could not open Master Sheet: {e}")
             self.sheet = None
        self.drive_service = build('drive', 'v3', credentials=self.creds)
        self.docs_service = build('docs', 'v1', credentials=self.creds)
    def verify_user(self, email, password):
        """
        Verifies if the email and password match the records in the Master Sheet.
        Assumes Column A is Email/User and Column B is Password.
        Returns the Case ID if successful, None otherwise.
        """
        try:
            sh = self.gc.open_by_url(MASTER_SHEET_URL)
            worksheet = sh.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            if not all_values:
                return None
            
            # Find the user in Column A (Index 0)
            # We skip the header row usually, but let's check all just in case or start from index 1?
            # Let's iterate through all rows.
            
            found_case_id = None
            
            # Identify columns dynamically or strictly A and B as requested?
            # User said: "AB欄 password" -> A=User?, B=Password? 
            # Or maybe A=User, B=Password.
            # Let's assume A=Email, B=Password.
            
            # Also need to find Case ID.
            headers = [h.lower().strip() for h in all_values[0]]
            case_id_col_idx = -1
            for idx, h in enumerate(headers):
                 if "case" in h or "id" in h or "編號" in h or "案件" in h:
                        case_id_col_idx = idx
                        
            # If we can't find Case ID column, we might have an issue.
            # But let's proceed with finding the user first.
            
            for row in all_values:
                # Safe access
                if len(row) < 2:
                    continue
                
                row_email = str(row[0]).strip()
                row_pass = str(row[1]).strip()
                
                if row_email == email.strip() and row_pass == password.strip():
                    # Match found!
                    # Now get Case ID.
                    if case_id_col_idx != -1 and len(row) > case_id_col_idx:
                        found_case_id = str(row[case_id_col_idx]).strip()
                    else:
                        # Fallback: maybe it's column C (Index 2)?
                        if len(row) > 2:
                             found_case_id = str(row[2]).strip()
                    
                    return found_case_id
            
            return None
        except Exception as e:
            st.error(f"Error validating user: {e}")
            return None
    def get_case_id_by_email(self, email):
        """
        Legacy/Backup: Scans the master sheet for the email and returns the associated Case ID.
        """
        try:
            sh = self.gc.open_by_url(MASTER_SHEET_URL)
            worksheet = sh.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            if not all_values:
                return None
            
            headers = [h.lower().strip() for h in all_values[0]]
            
            # Find column indices
            email_col_idx = -1
            case_id_col_idx = -1
            
            for idx, h in enumerate(headers):
                if "email" in h or "信箱" in h:
                    email_col_idx = idx
                if "case" in h or "id" in h or "編號" in h or "案件" in h:
                    case_id_col_idx = idx
            
            # Use index 1 (B) and 2 (C) as fallback if headers fail, assuming A=Time, B=Email, C=CaseID
            if email_col_idx == -1: email_col_idx = 1
            if case_id_col_idx == -1: case_id_col_idx = 2
            
            # Iterate and find
            for row in all_values:
                if len(row) > email_col_idx and str(row[email_col_idx]).strip() == email.strip():
                    if len(row) > case_id_col_idx:
                        return str(row[case_id_col_idx]).strip()
            
            return None
        except Exception as e:
            st.error(f"Error reading Sheet: {e}")
            return None
    def find_file_in_drive(self, name, parent_id=None):
        """Finds a file by name in Drive, strictly under parent_id if provided."""
        query = f"name = '{name}' and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
            
        # Added supportsAllDrives=True to find files in Shared Drives
        results = self.drive_service.files().list(
            q=query, 
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        return None
    def find_folder_in_drive(self, name, parent_id=None):
        """Finds a folder by name in Drive, strictly under parent_id if provided."""
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        # Added supportsAllDrives=True to find folders in Shared Drives
        results = self.drive_service.files().list(
            q=query, 
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        return None
    # Function to find the Root Folder (Shared from User)
    def get_root_folder_id(self):
        # We look for a specific folder that the user MUST satisfy
        # This bypasses the 0-byte limit of the service account itself
        FOLDER_NAME = "Meta_Ads_System" # User must create this
        folder_id = self.find_folder_in_drive(FOLDER_NAME)
        return folder_id
    def create_folder(self, name, parent_id=None):
        """Creates a new folder, optionally inside a parent."""
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
            
        # Added supportsAllDrives=True
        file = self.drive_service.files().create(
            body=file_metadata, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return file.get('id')
    def create_doc(self, title, folder_id=None):
        """Creates a new Google Doc, optionally inside a folder."""
        doc_metadata = {
            'name': title,
            'mimeType': 'application/vnd.google-apps.document'
        }
        if folder_id:
            doc_metadata['parents'] = [folder_id]
            
        # Added supportsAllDrives=True
        doc = self.drive_service.files().create(
            body=doc_metadata, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return doc.get('id')
    def share_file(self, file_id, email, role='writer'):
        """Shares a file with a specific email."""
        def callback(request_id, response, exception):
            if exception:
                print(f"Error sharing with {email}: {exception}")
        batch = self.drive_service.new_batch_http_request(callback=callback)
        user_permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email
        }
        batch.add(self.drive_service.permissions().create(
                fileId=file_id,
                body=user_permission,
                fields='id',
        ))
        batch.execute()
    def ensure_doc_exists_and_share(self, case_id, customer_email):
        """
        Checks if 'CASEID_meta廣告上刊文件' exists.
        Strategy:
        1. Find 'Meta_Ads_System' folder (Shared from User).
        2. If not found -> RAISE ERROR (User must create it).
        3. Find/Create 'CustomerName' folder INSIDE 'Meta_Ads_System'.
        4. Create Doc INSIDE 'CustomerName' folder.
        """
        doc_name = f"{case_id}_meta廣告上刊文件"
        st.sidebar.info(f"Debug: Checking doc '{doc_name}'")
        
        existing_doc_id = self.find_file_in_drive(doc_name)
        if existing_doc_id:
            st.sidebar.success(f"Debug: Doc found ({existing_doc_id})")
            print(f"Document '{doc_name}' already exists. ID: {existing_doc_id}")
            # Optimization: Don't re-share if it already exists to avoid spamming emails.
            # If user lost access, they can contact admin or we can add a specific button for it.
            # try:
            #     self.share_file(existing_doc_id, customer_email)
            #     self.share_file(existing_doc_id, ADMIN_EMAIL)
            # except:
            #     pass 
            return existing_doc_id
        else:
            print(f"Creating new document: {doc_name}")
            st.sidebar.info("Debug: Doc not found, creating...")
            
            # 0. Find Root Folder (CRITICAL FIX for 0 Quota)
            st.sidebar.text("Debug: Searching for 'Meta_Ads_System'...")
            root_id = self.get_root_folder_id()
            
            if not root_id:
                st.sidebar.error("❌ Critical: 'Meta_Ads_System' folder NOT FOUND.")
                st.sidebar.warning("請確保您已在 Google Drive 建立 'Meta_Ads_System' 資料夾並分享給機器人帳號！")
                raise FileNotFoundError("找不到根目錄 'Meta_Ads_System'。請在您的 Google Drive 建立此資料夾並分享給 Service Account。")
            else:
                st.sidebar.success(f"✅ Found Root Folder: {root_id}")
            # 1. Determine Customer Folder Name
            if "_" in str(case_id):
                folder_name = str(case_id).split("_")[0]
            else:
                folder_name = str(case_id)
            
            # 2. Check/Create Customer Folder INSIDE Root (Strict Tree Search)
            st.sidebar.text(f"Debug: Searching/Creating Subfolder '{folder_name}' under Root...")
            # Pass root_id as parent_id to scope the search
            folder_id = self.find_folder_in_drive(folder_name, parent_id=root_id)
            
            if not folder_id:
                st.sidebar.text(f"Debug: Creating '{folder_name}' inside Root...")
                try:
                    folder_id = self.create_folder(folder_name, parent_id=root_id)
                    st.sidebar.success(f"✅ Created Subfolder: {folder_id}")
                except Exception as e:
                     st.sidebar.error(f"❌ Failed to create subfolder: {e}")
                     raise e
            else:
                st.sidebar.info(f"Debug: Found existing subfolder {folder_id} under Root")
            
            # 3. Create Doc inside Customer Folder
            st.sidebar.text("Debug: Creating Document...")
            try:
                new_doc_id = self.create_doc(doc_name, folder_id=folder_id)
                st.sidebar.success(f"✅ Created Document: {new_doc_id}")
            except Exception as e:
                st.sidebar.error(f"❌ Failed to create document: {e}")
                raise e
            
            self.share_file(new_doc_id, customer_email)
            self.share_file(new_doc_id, ADMIN_EMAIL)
            return new_doc_id
    def upload_image_to_drive(self, image_file, filename, parent_id):
        """
        Uploads an image file object to Drive under 'Images' subfolder.
        Returns the High-Res Thumbnail Link.
        """
        try:
            # 1. Ensure 'Images' folder exists
            images_folder_id = self.find_folder_in_drive("Images_圖檔", parent_id=parent_id)
            if not images_folder_id:
                st.sidebar.text("Debug: Creating 'Images_圖檔' folder...")
                images_folder_id = self.create_folder("Images_圖檔", parent_id=parent_id)
            
            # 2. Upload File
            # Reset pointer just in case
            image_file.seek(0)
            
            file_metadata = {
                'name': filename,
                'parents': [images_folder_id]
            }
            media = MediaIoBaseUpload(image_file, mimetype=image_file.type, resumable=True)
            
            new_file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webContentLink, thumbnailLink',
                supportsAllDrives=True
            ).execute()
            
            new_file_id = new_file.get('id')
            st.sidebar.success(f"Debug: Image Upload Success ({new_file_id})")
            # 3. Make Public (Reader)
            self.drive_service.permissions().create(
                fileId=new_file_id,
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
            
            # Wait for permission propagation
            import time
            time.sleep(2)
            
            # 4. Return Direct Link (Prefer Thumbnail for reliability)
            thumb_link = new_file.get('thumbnailLink')
            if thumb_link:
                # Resize to large
                final_link = thumb_link.replace('=s220', '=s1600')
                return final_link, new_file.get('webContentLink')
            
            return new_file.get('webContentLink'), new_file.get('webContentLink')
        except Exception as e:
            print(f"Upload failed: {e}")
            st.warning(f"⚠️ 圖片上傳失敗: {e}")
            return None, None
    def append_ad_data_to_doc(self, doc_id, ad_data):
        """
        Appends the formatted ad data to the Google Doc using a Table Layout.
        Left Column: Text Info
        Right Column: Image Preview
        """
        # Define the block name provided in the request
        block_name = f"{ad_data.get('ad_name_id')}_{ad_data.get('image_name_id')}"
        
        # We need to determine the folder_id of this doc to store the image
        try:
            doc_info = self.drive_service.files().get(fileId=doc_id, fields='parents', supportsAllDrives=True).execute()
            parent_id = doc_info.get('parents', [None])[0]
        except:
            parent_id = None
        # --- Image Upload Logic ---
        image_file = ad_data.get('image_file')
        image_insert_link = None
        
        if image_file and parent_id:
            # 1. Determine Filename
            original_ext = os.path.splitext(image_file.name)[1]
            if not original_ext:
                original_ext = ".jpg"
            
            final_filename = f"{ad_data.get('image_name_id')}{original_ext}"
            
            # 2. Upload
            st.sidebar.text(f"Debug: Uploading image '{final_filename}'...")
            thumb, web = self.upload_image_to_drive(image_file, final_filename, parent_id)
            
            # Update ad_data['image_url'] for text display/email
            ad_data['image_url'] = web
            image_insert_link = thumb
        
        # --- Create Table Layout ---
        # 1. Insert Table (1 Row, 2 Columns) at Index 1 (Top)
        requests_body = [
            {
                'insertTable': {
                    'rows': 1,
                    'columns': 2,
                    'location': {
                        'index': 1
                    }
                }
            }
        ]
        self.docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
        
        # 2. Fetch Document to get Table Cell Indices
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        content = doc.get('body').get('content')
        
        # The newly inserted table should be the second element (Index 0 is usually SectionBreak/Para)
        # We look for the Table at the start.
        # Since we inserted at Index 1, it should be right after the start.
        
        table = None
        for element in content:
            if 'table' in element:
                # We assume the first table found is the one we just created (since we prepended it)
                # Or we can check start indices. 
                # Let's assume the one with the lowest startIndex (>= 1) is ours.
                table = element['table']
                break
        
        if not table:
            st.error("Error: Could not find created table to insert data.")
            return block_name
        # Get Cell 0 (Left) and Cell 1 (Right)
        try:
            row = table['tableRows'][0]
            cell_left = row['tableCells'][0]
            cell_right = row['tableCells'][1]
            
            # Indices to insert text are the 'startIndex' of the cell's content content.
            # But usually we insert at cell['content'][0]['startIndex'] if it exists?
            # Actually simpler: cell['startIndex'] is the start of the cell. 
            # Content starts at cell['startIndex'] + 1 ? No, API says `startIndex` within the content list.
            # actually `content` list has structure.
            # We can just use the index from the API response structure.
            
            # Safest: Use cell['content'][-1]['endIndex'] - 1 to append? 
            # Or just use the cell's `startIndex` + 1?
            # Docs API: "The content of a table cell is a sequence of StructuralElements."
            # We want to insert into the empty cell.
            
            # Let's use the explicit structure found in `content`.
            # If the cell is empty, it usually contains a single empty paragraph (ending with \n).
            
            left_index = cell_left['content'][0]['startIndex']
            right_index = cell_right['content'][0]['startIndex']
            
            # --- Text Content (Left) ---
            text_content = (
                f"廣告組合 ID: {block_name}\n"
                f"送出時間: {ad_data.get('fill_time')}\n"
                f"廣告名稱/編號: {ad_data.get('ad_name_id')}\n"
                f"對應圖片名稱/編號: {ad_data.get('image_name_id')}\n"
                f"對應圖片雲端網址: {ad_data.get('image_url')}\n"
                f"廣告標題: {ad_data.get('headline')}\n"
                f"廣告到達網址: {ad_data.get('landing_url')}\n"
                f"廣告主文案:\n{ad_data.get('main_copy')}\n"
            )
            
            # Requests for Text and Image
            # Note: We must be careful about index shifting if we do one by one.
            # But the cells are separate, so indices inside Cell 2 shouldn't change if we edit Cell 1?
            # WRONG. Steps in a batchUpdate are applied sequentially, and subsequent indices ARE affected.
            # So we should insert the Image (Right) first (higher index) then Text (Left) (lower index)?
            # Yes, standard practice is reverse order of index to avoid shifting issues.
            
            # However, if right_index > left_index is guaranteed?
            # Yes, Left Cell is before Right Cell.
            
            batch_requests = []
            
            # 1. Insert Image into Right Cell (Higher Index)
            if image_insert_link:
                batch_requests.append({
                    'insertInlineImage': {
                        'uri': image_insert_link,
                        'location': {
                            'index': right_index
                        },
                        'objectSize': {
                            'width': {
                                'magnitude': 150, # Smaller preview requested
                                'unit': 'PT'
                            }
                        }
                    }
                })
            # 2. Insert Text into Left Cell (Lower Index)
            batch_requests.append({
                'insertText': {
                    'location': {
                        'index': left_index
                    },
                    'text': text_content
                }
            })
            
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': batch_requests}).execute()
            
            # Optional: Add a spacer line after the table steps it down? 
            # We already inserted table at Index 1.
            
        except Exception as e:
            st.error(f"Error populating table: {e}")
            print(f"Table Error: {e}")
        
        return block_name
    def send_confirmation_email(self, to_email, ad_data, doc_url):
        """
        Sends a confirmation email using Gmail API.
        Only works in OAuth mode.
        """
        if self.auth_mode != "oauth":
            print(f"Skipping email to {to_email} (Not in OAuth mode)")
            st.info("ℹ️ 目前為 Service Account 模式，跳過 Gmail 寄信 (系統紀錄已存檔)。")
            return False
        try:
            service = build('gmail', 'v1', credentials=self.creds)
            message = MIMEText(f"""
            Hi,
            
            您的廣告素材已成功提交！
            
            【提交資訊】
            送出時間: {ad_data.get('fill_time')}
            廣告名稱/編號: {ad_data.get('ad_name_id')}
            對應圖片: {ad_data.get('image_name_id')}
            圖片連結: {ad_data.get('image_url')}
            廣告標題: {ad_data.get('headline')}
            廣告到達網址: {ad_data.get('landing_url')}
            
            【廣告文案】
            {ad_data.get('main_copy')}
            
            【文件連結】
            {doc_url}
            
            這是一封自動發送的確認信。
            """)
            
            message['to'] = to_email
            message['from'] = 'me'
            message['subject'] = f"✅ 素材提交成功：{ad_data.get('ad_name_id')}"
            
            # Encode the message safely
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            body = {'raw': raw_message}
            
            service.users().messages().send(userId='me', body=body).execute()
            print(f"Email sent to {to_email}")
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            st.error(f"⚠️ Email 寄送失敗: {e}")
            return False
