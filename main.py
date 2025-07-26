import re
import datetime
import csv
import glob
import base64
import logging
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os.path
import pickle

# ログ設定
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Gmail API設定
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_FILE = "token.pickle"
CREDENTIALS_FILE = "credentials.json"

# 検索設定
SEARCH_SUBJECT = "口座振替"

# 正規表現パターン
ACCOUNT_NAME_PATTERN = r"口座振替先[:：]\s*([\w\W]+?)(?:\n|お申込先)"
AMOUNT_PATTERN = r"引落金額\s*[:：]\s*([¥\d,]+)円"

# ファイル設定
RESULT_FILE_PREFIX = "result_debit_"
CSV_ENCODING = "utf-8"


def get_message_body(payload):
    """メールの本文を取得する関数"""
    body = ""
    if payload.get("body") and payload["body"].get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                if part["body"].get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8"
                    )
                    break
    return body


def validate_amount(amount_str):
    """金額文字列の検証"""
    try:
        amount = float(amount_str)
        if amount < 0:
            return "0"
        return amount_str
    except (ValueError, TypeError):
        return "0"


def authenticate_gmail():
    """Gmail APIの認証を行う"""
    creds = None
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "rb") as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("認証トークンを更新中...")
                creds.refresh(Request())
            else:
                logger.info("新しい認証を開始...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, "wb") as token:
                pickle.dump(creds, token)
                logger.info("認証トークンを保存しました")

        return build("gmail", "v1", credentials=creds)

    except Exception as e:
        logger.error(f"Gmail認証エラー: {e}")
        raise


def load_existing_cache_data(year_month):
    """既存のキャッシュデータを読み込む"""
    result_files = sorted(glob.glob(f"{RESULT_FILE_PREFIX}*.csv"), reverse=True)
    result_file = result_files[0] if result_files else None
    result_created_at = None
    result_rows = []

    if result_file and os.path.exists(result_file):
        logger.info(f"既存の結果ファイルを確認: {result_file}")
        with open(result_file, "r", encoding=CSV_ENCODING) as f:
            first_line = f.readline()
            if first_line.startswith("# cached_at:"):
                result_created_at = first_line.strip().split(":", 1)[1].strip()
            reader = csv.DictReader(f)
            result_rows = [row for row in reader if row["年月"] == year_month]

    return result_file, result_created_at, result_rows, result_files


def display_cached_results(result_file, result_rows):
    """キャッシュされた結果を表示する"""
    logger.info(f"{len(result_rows)}件の既存データが見つかりました")
    print(f"結果({result_file})から取得:")
    for row in result_rows:
        print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
    total = sum(float(row["金額"]) for row in result_rows)
    print(f"今月の口座振替合計：¥{total:,.0f}")


def get_search_query_date(result_created_at, first_day):
    """検索クエリ用の日付を取得する"""
    if result_created_at:
        try:
            date_obj = datetime.datetime.strptime(result_created_at, "%Y-%m-%d")
            return date_obj.strftime("%Y/%m/%d")
        except ValueError:
            logger.warning("日付フォーマットエラー、今月の開始日を使用します")
    return first_day.strftime("%Y/%m/%d")


def search_gmail_messages(service, query_date):
    """Gmailからメッセージを検索する"""
    query = f"after:{query_date} subject:({SEARCH_SUBJECT})"
    logger.info(f"Gmail検索クエリ: {query}")

    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])
    logger.info(f"{len(messages)}件のメールが見つかりました")

    return messages


def extract_debit_info_from_message(service, msg, year_month):
    """メッセージから口座振替情報を抽出する"""
    try:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()

        # メール本文の取得
        payload = msg_data.get("payload", {})
        body = get_message_body(payload)
        if not body:  # フォールバック
            body = msg_data.get("snippet", "")

        # 振替先の抽出
        m_name = re.search(ACCOUNT_NAME_PATTERN, body)
        name = m_name.group(1).strip() if m_name else "[不明]"

        # 金額の抽出と検証
        m_amt = re.search(AMOUNT_PATTERN, body)
        amt = m_amt.group(1).replace("¥", "").replace(",", "") if m_amt else "0"
        amt = validate_amount(amt)

        return {"年月": year_month, "振替先": name, "金額": amt}

    except Exception as e:
        logger.error(f"メッセージ取得エラー (ID: {msg['id']}): {e}")
        return None


def extract_debit_info_from_messages(service, messages, year_month):
    """複数のメッセージから口座振替情報を抽出する"""
    extracted = []
    for i, msg in enumerate(messages, 1):
        logger.debug(f"メール {i}/{len(messages)} を処理中...")
        debit_info = extract_debit_info_from_message(service, msg, year_month)
        if debit_info:
            extracted.append(debit_info)
            logger.debug(f"抽出完了: {debit_info['振替先']} - ¥{debit_info['金額']}")

    logger.info(f"{len(extracted)}件のメールを処理しました")
    return extracted


def save_results_to_csv(extracted, result_file, result_files):
    """結果をCSVファイルに保存する"""
    fieldnames = ["年月", "振替先", "金額"]
    if not extracted:
        return None

    # 新しい結果ファイル名
    result_time = datetime.date.today().strftime("%Y-%m-%d")
    new_result_file = f"{RESULT_FILE_PREFIX}{result_time}.csv"

    # 既存データを残して追記
    old_rows = []
    if result_file and os.path.exists(result_file):
        with open(result_file, "r", encoding=CSV_ENCODING) as f:
            lines = f.readlines()
            if lines and lines[0].startswith("# cached_at:"):
                old_rows = list(csv.DictReader(lines[1:]))
            else:
                old_rows = list(csv.DictReader(lines))

    all_rows = old_rows + extracted
    with open(new_result_file, "w", encoding=CSV_ENCODING, newline="") as f:
        f.write(f"# cached_at: {result_time}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"結果をファイルに保存しました: {new_result_file}")

    # 古い結果ファイルを削除
    for old_file in result_files:
        if old_file != new_result_file:
            try:
                os.remove(old_file)
                logger.debug(f"古いファイルを削除: {old_file}")
            except Exception as e:
                logger.warning(f"ファイル削除エラー {old_file}: {e}")

    return new_result_file


def display_new_results(extracted):
    """新規取得した結果を表示する"""
    if extracted:
        total = sum(float(row["金額"]) for row in extracted)
        print("新規取得した口座振替情報:")
        for row in extracted:
            print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
        print(f"今月の新規口座振替合計：¥{total:,.0f}")
    else:
        print("新しい口座振替情報は見つかりませんでした")


def fetch_mail_and_extract_info(service):
    """メールから口座振替情報を取得し、CSVに保存する"""
    try:
        logger.info("口座振替情報の取得を開始します")
        today = datetime.date.today()
        first_day = today.replace(day=1)
        year_month = today.strftime("%Y-%m")

        # 既存のキャッシュデータを確認
        result_file, result_created_at, result_rows, result_files = (
            load_existing_cache_data(year_month)
        )

        if result_rows:
            display_cached_results(result_file, result_rows)
            return

        # Gmail検索用の日付を取得
        query_date = get_search_query_date(result_created_at, first_day)

        # Gmailからメッセージを検索
        messages = search_gmail_messages(service, query_date)

        # メッセージから口座振替情報を抽出
        extracted = extract_debit_info_from_messages(service, messages, year_month)

        # 結果をCSVに保存
        save_results_to_csv(extracted, result_file, result_files)

        # 新規取得した結果を表示
        display_new_results(extracted)

    except Exception as e:
        logger.error(f"Gmail API エラー: {e}")
        print(f"エラーが発生しました: {e}")
        return


if __name__ == "__main__":
    service = authenticate_gmail()
    fetch_mail_and_extract_info(service)
