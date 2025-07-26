import re
import datetime
import csv
import glob
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


def fetch_mail_and_extract_info(service):
    today = datetime.date.today()
    first_day = today.replace(day=1)
    year_month = today.strftime("%Y-%m")

    # 最新結果ファイルを判別
    result_files = sorted(glob.glob("result_debit_*.csv"), reverse=True)
    result_file = result_files[0] if result_files else None
    result_created_at = None
    result_rows = []
    if result_file and os.path.exists(result_file):
        with open(result_file, "r", encoding="utf-8") as f:
            first_line = f.readline()
            if first_line.startswith("# cached_at:"):
                result_created_at = first_line.strip().split(":", 1)[1].strip()
            reader = csv.DictReader(f)
            result_rows = [row for row in reader if row["年月"] == year_month]
        if result_rows:
            print(f"結果({result_file})から取得:")
            for row in result_rows:
                print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
            total = sum(float(row["金額"]) for row in result_rows)
            print(f"今月の口座振替合計：¥{total:,.0f}")
            return

    # Gmailクエリ（結果ファイル作成日時以降 or 今月の開始日以降）
    if result_created_at:
        query_date = result_created_at.replace("-", "/")
    else:
        query_date = first_day.strftime('%Y/%m/%d')
    query = f"after:{query_date} subject:(口座振替)"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    extracted = []
    for msg in messages:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        # 本文取得（snippetだと短い場合があるのでpayload/bodyも検討）
        payload = msg_data.get("snippet", "")
        # 振替先（例: 口座名義: ○○○○）
        m_name = re.search(r"口座名義[:：]\s*([\w\W]+?)\n", payload)
        name = m_name.group(1).strip() if m_name else "[不明]"
        # 金額抽出（例：¥12,345）
        m_amt = re.search(r"振替金額[:：]\s*([¥\d,]+)", payload)
        amt = m_amt.group(1).replace("¥", "").replace(",", "") if m_amt else "0"
        # 年月
        extracted.append({"年月": year_month, "振替先": name, "金額": amt})

    # CSV保存
    fieldnames = ["年月", "振替先", "金額"]
    if extracted:
        # 新しい結果ファイル名
        result_time = datetime.date.today().strftime("%Y-%m-%d")
        new_result_file = f"result_debit_{result_time}.csv"
        # 既存データを残して追記
        old_rows = []
        if result_file and os.path.exists(result_file):
            with open(result_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines and lines[0].startswith("# cached_at:"):
                    old_rows = list(csv.DictReader(lines[1:]))
                else:
                    old_rows = list(csv.DictReader(lines))
        all_rows = old_rows + extracted
        with open(new_result_file, "w", encoding="utf-8", newline="") as f:
            f.write(f"# cached_at: {result_time}\n")
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        # 古い結果ファイルを削除
        for old_file in result_files:
            if old_file != new_result_file:
                try:
                    os.remove(old_file)
                except Exception:
                    pass

    # 結果表示
    total = sum(float(row["金額"]) for row in extracted)
    for row in extracted:
        print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
    print(f"今月の口座振替合計：¥{total:,.0f}")


if __name__ == "__main__":
    service = authenticate_gmail()
    fetch_mail_and_extract_info(service)
