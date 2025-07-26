import re
import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os.path
import pickle

# スコープ設定（読み取りのみ）
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def authenticate_gmail():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def fetch_mail_and_extract_amounts(service):
    # 今月の開始日（1日）を設定
    today = datetime.date.today()
    first_day = today.replace(day=1)

    # Gmailクエリ（口座振替通知に関連する語句＋今月の日付）
    query = f"after:{first_day.strftime('%Y/%m/%d')} subject:(口座振替 引き落とし通知)"

    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    total = 0.0
    for msg in messages:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        payload = msg_data.get("snippet", "")  # 短い本文の取得
        # 金額抽出（例：¥12,345）
        amounts = re.findall(r"¥[\d,]+", payload)
        for amt in amounts:
            cleaned = amt.replace("¥", "").replace(",", "")
            total += float(cleaned)

    return total


if __name__ == "__main__":
    # 認証とサービスの構築
    service = authenticate_gmail()

    # メールを取得して金額を抽出
    total_amount = fetch_mail_and_extract_amounts(service)

    # 結果の表示
    print(f"今月の口座振替合計：¥{total_amount:,.0f}")
