import re
import datetime
import csv
import glob
import base64
import logging
import argparse
import chardet
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
VALID_SENDERS = [
    "post_master@netbk.co.jp",  # 住信SBIネット銀行
    "@netbk.co.jp",  # 住信SBIネット銀行（ドメイン）
]

# 正規表現パターン
ACCOUNT_NAME_PATTERN = r"口座振替先[:：]\s*([\w\W]+?)(?:\n|お申込先)"
AMOUNT_PATTERN = r"引落金額\s*[:：]\s*([¥\d,]+)円"

# ファイル設定
RESULT_FILE_PREFIX = "result_debit_"
CSV_ENCODING = "utf-8"


def get_message_body(payload):
    """メールの本文を取得する関数（文字コード自動判定付き）"""
    body = ""
    raw_data = None
    
    if payload.get("body") and payload["body"].get("data"):
        raw_data = base64.urlsafe_b64decode(payload["body"]["data"])
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                if part["body"].get("data"):
                    raw_data = base64.urlsafe_b64decode(part["body"]["data"])
                    break
    
    if raw_data:
        # 文字コード自動判定
        try:
            detected = chardet.detect(raw_data)
            encoding = detected.get('encoding', 'utf-8')
            confidence = detected.get('confidence', 0)
            
            if confidence > 0.7:  # 信頼度が70%以上の場合
                body = raw_data.decode(encoding)
            else:
                # フォールバック: 一般的な日本語エンコーディングを試す
                for enc in ['utf-8', 'iso-2022-jp', 'shift_jis', 'euc-jp']:
                    try:
                        body = raw_data.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"文字コード判定エラー: {e}")
            # 最終フォールバック
            try:
                body = raw_data.decode('utf-8', errors='ignore')
            except:
                body = ""
    
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


def display_cached_results(result_file, result_rows, summary_only=False):
    """キャッシュされた結果を表示する"""
    logger.info(f"{len(result_rows)}件の既存データが見つかりました")
    total = sum(float(row["金額"]) for row in result_rows)
    
    if summary_only:
        print(f"¥{total:,.0f}")
    else:
        print(f"結果({result_file})から取得:")
        for row in result_rows:
            print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
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


def is_valid_sender(headers):
    """送信者が有効かどうかをチェックする関数"""
    for header in headers:
        if header["name"].lower() == "from":
            from_address = header["value"].lower()
            for valid_sender in VALID_SENDERS:
                if valid_sender in from_address:
                    return True
    return False


def extract_debit_info_from_message(service, msg, year_month):
    """メッセージから口座振替情報を抽出する関数（送信者フィルタ付き）"""
    try:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()

        # 送信者チェック
        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])
        if not is_valid_sender(headers):
            logger.debug(f"送信者が無効なためスキップ: {msg['id']}")
            return None

        # メール本文の取得
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


def display_new_results(extracted, summary_only=False):
    """新規取得した結果を表示する"""
    if extracted:
        total = sum(float(row["金額"]) for row in extracted)
        if summary_only:
            print(f"¥{total:,.0f}")
        else:
            print("新規取得した口座振替情報:")
            for row in extracted:
                print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
            print(f"今月の新規口座振替合計：¥{total:,.0f}")
    else:
        if not summary_only:
            print("新しい口座振替情報は見つかりませんでした")
        else:
            print("¥0")


def fetch_mail_and_extract_info(service, summary_only=False):
    """メールから口座振替情報を取得し、CSVに保存する"""
    try:
        if not summary_only:
            logger.info("口座振替情報の取得を開始します")
        today = datetime.date.today()
        first_day = today.replace(day=1)
        year_month = today.strftime("%Y-%m")

        # 既存のキャッシュデータを確認
        result_file, result_created_at, result_rows, result_files = (
            load_existing_cache_data(year_month)
        )

        if result_rows:
            display_cached_results(result_file, result_rows, summary_only)
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
        display_new_results(extracted, summary_only)

    except Exception as e:
        logger.error(f"Gmail API エラー: {e}")
        if not summary_only:
            print(f"エラーが発生しました: {e}")
        return


def parse_arguments():
    """コマンドライン引数を解析する"""
    parser = argparse.ArgumentParser(description="Gmailから口座振替情報を取得して集計します")
    parser.add_argument(
        "--summary-only", "-s",
        action="store_true",
        help="合計金額のみを表示（詳細な情報を省略）"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    service = authenticate_gmail()
    fetch_mail_and_extract_info(service, summary_only=args.summary_only)
