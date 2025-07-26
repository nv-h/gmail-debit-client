import argparse
import base64
import csv
import datetime
import glob
import logging
import os.path
import pickle
import re

import chardet
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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
            encoding = detected.get("encoding", "utf-8")
            confidence = detected.get("confidence", 0)

            if confidence > 0.7:  # 信頼度が70%以上の場合
                body = raw_data.decode(encoding)
            else:
                # フォールバック: 一般的な日本語エンコーディングを試す
                for enc in ["utf-8", "iso-2022-jp", "shift_jis", "euc-jp"]:
                    try:
                        body = raw_data.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"文字コード判定エラー: {e}")
            # 最終フォールバック
            try:
                body = raw_data.decode("utf-8", errors="ignore")
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


def filter_zero_amount_rows(rows):
    """金額が0の行を除外する"""
    filtered_rows = []
    for row in rows:
        try:
            if float(row["金額"]) > 0:
                filtered_rows.append(row)
        except (ValueError, TypeError):
            # 金額が不正な場合はスキップ
            pass
    return filtered_rows


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


def load_existing_cache_data(year_month, year_mode=False):
    """既存のキャッシュデータを読み込む"""
    result_files = sorted(glob.glob(f"{RESULT_FILE_PREFIX}*.csv"), reverse=True)
    result_file = result_files[0] if result_files else None
    result_created_at = None
    result_rows = []

    if result_file and os.path.exists(result_file):
        logger.info(f"既存の結果ファイルを確認: {result_file}")
        with open(result_file, encoding=CSV_ENCODING) as f:
            first_line = f.readline()
            if first_line.startswith("# cached_at:"):
                result_created_at = first_line.strip().split(":", 1)[1].strip()
            reader = csv.DictReader(f)
            if year_mode:
                # 年間モードの場合、全てのデータを取得
                result_rows = list(reader)
            else:
                # 月間モードの場合、指定した年月のみ
                result_rows = [row for row in reader if row["年月"] == year_month]

    return result_file, result_created_at, result_rows, result_files


def display_cached_results(result_file, result_rows, summary_only=False, year_mode=False):
    """キャッシュされた結果を表示する（金額0の行を除外）"""
    # 金額0の行を除外
    result_rows_filtered = filter_zero_amount_rows(result_rows)

    logger.info(f"{len(result_rows)}件の既存データが見つかりました（金額0を除外後: {len(result_rows_filtered)}件）")
    total = sum(float(row["金額"]) for row in result_rows_filtered)

    if summary_only:
        print(f"¥{total:,.0f}")
    elif year_mode:
        print(f"結果({result_file})から取得:")
        # 年月別にグループ化して表示
        from collections import defaultdict
        by_month = defaultdict(list)
        for row in result_rows_filtered:
            by_month[row["年月"]].append(row)

        for month in sorted(by_month.keys()):
            month_total = sum(float(row["金額"]) for row in by_month[month])
            print(f"\n{month} (¥{month_total:,.0f})")
            for row in by_month[month]:
                print(f"  {row['振替先']} ¥{float(row['金額']):,.0f}")
        print(f"\n過去1年分の口座振替合計：¥{total:,.0f}")
    else:
        print(f"結果({result_file})から取得:")
        for row in result_rows_filtered:
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


def get_missing_months_from_cache(result_rows, start_date, end_date):
    """キャッシュデータから欠けている月のリストを取得する（2025年1月以降のみ）"""
    # キャッシュされている年月のセット
    cached_months = set(row["年月"] for row in result_rows)

    # 過去1年分の全ての月を生成
    all_months = []
    current = start_date.replace(day=1)  # 月初にする
    end = end_date.replace(day=1)

    # 2025年1月以前の月をカウント
    excluded_months = []

    while current <= end:
        month_str = current.strftime("%Y-%m")

        # 2025年1月以前は除外（金額データなし）
        if current < datetime.date(2025, 1, 1):
            excluded_months.append(month_str)
        else:
            all_months.append(month_str)

        # 次の月へ
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # 除外された月について警告
    if excluded_months:
        logger.warning(f"2025年1月以前の{len(excluded_months)}ヶ月は金額データがないため検索対象外: {', '.join(excluded_months)}")

    # キャッシュにない月を特定（2025年1月以降のみ）
    missing_months = [month for month in all_months if month not in cached_months]

    logger.info(f"検索対象{len(all_months)}ヶ月中、キャッシュ済み: {len([m for m in cached_months if m >= '2025-01'])}ヶ月、未取得: {len(missing_months)}ヶ月")
    if missing_months:
        logger.info(f"未取得の月: {', '.join(missing_months)}")

    return missing_months


def search_gmail_messages(service, query_date):
    """Gmailからメッセージを検索する"""
    query = f"after:{query_date} subject:({SEARCH_SUBJECT})"
    logger.info(f"Gmail検索クエリ: {query}")

    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])
    logger.info(f"{len(messages)}件のメールが見つかりました")

    return messages


def search_gmail_messages_for_month(service, year_month):
    """指定した年月のメッセージを検索する"""
    try:
        year, month = map(int, year_month.split("-"))

        # 月の開始日と終了日を計算
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        # Gmail検索クエリ（指定月の範囲）
        start_str = start_date.strftime("%Y/%m/%d")
        end_str = end_date.strftime("%Y/%m/%d")
        query = f"after:{start_str} before:{end_str} subject:({SEARCH_SUBJECT})"

        logger.info(f"Gmail検索クエリ ({year_month}): {query}")

        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])
        logger.info(f"{year_month}: {len(messages)}件のメールが見つかりました")

        return messages

    except (ValueError, TypeError):
        logger.error(f"年月フォーマットエラー: {year_month}")
        return []


def is_valid_sender(headers):
    """送信者が有効かどうかをチェックする関数"""
    for header in headers:
        if header["name"].lower() == "from":
            from_address = header["value"].lower()
            for valid_sender in VALID_SENDERS:
                if valid_sender in from_address:
                    return True
    return False


def extract_debit_info_from_message(service, msg, year_month, year_mode=False):
    """メッセージから口座振替情報を抽出する関数（送信者フィルタ付き）"""
    try:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()

        # 送信者チェック
        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])
        if not is_valid_sender(headers):
            logger.debug(f"送信者が無効なためスキップ: {msg['id']}")
            return None

        # 年間モードの場合、メールの日付から年月を取得
        if year_mode:
            internal_date = int(msg_data.get("internalDate", 0)) / 1000
            msg_date = datetime.datetime.fromtimestamp(internal_date)
            year_month = msg_date.strftime("%Y-%m")

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


def extract_debit_info_from_messages(service, messages, year_month, year_mode=False):
    """複数のメッセージから口座振替情報を抽出する"""
    extracted = []
    for i, msg in enumerate(messages, 1):
        logger.debug(f"メール {i}/{len(messages)} を処理中...")
        debit_info = extract_debit_info_from_message(service, msg, year_month, year_mode)
        if debit_info:
            extracted.append(debit_info)
            logger.debug(f"抽出完了: {debit_info['振替先']} - ¥{debit_info['金額']}")

    logger.info(f"{len(extracted)}件のメールを処理しました")
    return extracted


def save_results_to_csv(extracted, result_file, result_files):
    """結果をCSVファイルに保存する（金額0の行を除外）"""
    fieldnames = ["年月", "振替先", "金額"]
    if not extracted:
        return None

    # 新しい結果ファイル名
    result_time = datetime.date.today().strftime("%Y-%m-%d")
    new_result_file = f"{RESULT_FILE_PREFIX}{result_time}.csv"

    # 既存データを残して追記
    old_rows = []
    if result_file and os.path.exists(result_file):
        with open(result_file, encoding=CSV_ENCODING) as f:
            lines = f.readlines()
            if lines and lines[0].startswith("# cached_at:"):
                old_rows = list(csv.DictReader(lines[1:]))
            else:
                old_rows = list(csv.DictReader(lines))

    # マージ前に金額0の行を除外
    old_rows_filtered = filter_zero_amount_rows(old_rows)
    extracted_filtered = filter_zero_amount_rows(extracted)

    all_rows = old_rows_filtered + extracted_filtered

    # 除外された行数をログに出力
    old_excluded = len(old_rows) - len(old_rows_filtered)
    new_excluded = len(extracted) - len(extracted_filtered)
    if old_excluded > 0 or new_excluded > 0:
        logger.info(f"金額0の行を除外: 既存データ {old_excluded}行, 新規データ {new_excluded}行")

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


def display_merged_results(cached_rows, new_rows, summary_only=False):
    """キャッシュデータと新規データをマージして表示する（金額0の行を除外）"""
    # 金額0の行を除外
    cached_rows_filtered = filter_zero_amount_rows(cached_rows)
    new_rows_filtered = filter_zero_amount_rows(new_rows)

    all_rows = cached_rows_filtered + new_rows_filtered
    total = sum(float(row["金額"]) for row in all_rows)

    if summary_only:
        print(f"¥{total:,.0f}")
    else:
        # 年月別にグループ化して表示
        from collections import defaultdict
        by_month = defaultdict(list)
        for row in all_rows:
            by_month[row["年月"]].append(row)

        cached_months = set(row["年月"] for row in cached_rows_filtered)

        print("過去1年分の口座振替情報:")
        for month in sorted(by_month.keys()):
            month_total = sum(float(row["金額"]) for row in by_month[month])
            status = " (キャッシュ)" if month in cached_months else " (新規取得)"
            print(f"\n{month} (¥{month_total:,.0f}){status}")
            for row in by_month[month]:
                print(f"  {row['振替先']} ¥{float(row['金額']):,.0f}")

        print(f"\n過去1年分の口座振替合計：¥{total:,.0f}")
        if new_rows_filtered:
            new_total = sum(float(row["金額"]) for row in new_rows_filtered)
            print(f"新規取得分：¥{new_total:,.0f}")


def display_new_results(extracted, summary_only=False, year_mode=False):
    """新規取得した結果を表示する（金額0の行を除外）"""
    # 金額0の行を除外
    extracted_filtered = filter_zero_amount_rows(extracted)

    if extracted_filtered:
        total = sum(float(row["金額"]) for row in extracted_filtered)
        if summary_only:
            print(f"¥{total:,.0f}")
        elif year_mode:
            print("過去1年分の口座振替情報:")
            # 年月別にグループ化して表示
            from collections import defaultdict
            by_month = defaultdict(list)
            for row in extracted_filtered:
                by_month[row["年月"]].append(row)

            for month in sorted(by_month.keys()):
                month_total = sum(float(row["金額"]) for row in by_month[month])
                print(f"\n{month} (¥{month_total:,.0f})")
                for row in by_month[month]:
                    print(f"  {row['振替先']} ¥{float(row['金額']):,.0f}")
            print(f"\n過去1年分の口座振替合計：¥{total:,.0f}")
        else:
            print("新規取得した口座振替情報:")
            for row in extracted_filtered:
                print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
            print(f"今月の新規口座振替合計：¥{total:,.0f}")
    elif not summary_only:
        if year_mode:
            print("過去1年分の口座振替情報は見つかりませんでした")
        else:
            print("新しい口座振替情報は見つかりませんでした")
    else:
        print("¥0")


def get_current_month_info():
    """現在の月情報を取得する"""
    today = datetime.date.today()
    first_day = today.replace(day=1)
    year_month = today.strftime("%Y-%m")
    return today, first_day, year_month


def get_one_year_info():
    """過去1年分の情報を取得する"""
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    return today, one_year_ago, "all"


def fetch_mail_and_extract_info(service, summary_only=False, year_mode=False):
    """メールから口座振替情報を取得し、CSVに保存する"""
    try:
        if not summary_only:
            if year_mode:
                logger.info("過去1年分の口座振替情報の取得を開始します")
            else:
                logger.info("口座振替情報の取得を開始します")

        if year_mode:
            _, start_date, year_month = get_one_year_info()
        else:
            _, start_date, year_month = get_current_month_info()

        # 既存のキャッシュデータを確認
        result_file, result_created_at, result_rows, result_files = (
            load_existing_cache_data(year_month, year_mode)
        )

        if year_mode:
            # 年間モードの場合、欠けている月を特定
            today = datetime.date.today()
            missing_months = get_missing_months_from_cache(result_rows, start_date, today)

            # 全ての月がキャッシュにある場合はそのまま表示
            if not missing_months:
                if result_rows:
                    display_cached_results(result_file, result_rows, summary_only, year_mode=True)
                return

            # 欠けている月のメッセージを取得
            extracted = []
            for missing_month in missing_months:
                logger.info(f"{missing_month} のメッセージを検索中...")
                monthly_messages = search_gmail_messages_for_month(service, missing_month)
                monthly_extracted = extract_debit_info_from_messages(service, monthly_messages, missing_month, year_mode=True)
                extracted.extend(monthly_extracted)

        else:
            # 月間モードの従来処理
            if result_rows:
                display_cached_results(result_file, result_rows, summary_only)
                return

            # Gmail検索用の日付を取得
            query_date = get_search_query_date(result_created_at, start_date)

            # Gmailからメッセージを検索
            messages = search_gmail_messages(service, query_date)

            # メッセージから口座振替情報を抽出
            extracted = extract_debit_info_from_messages(service, messages, year_month, year_mode)

        # 結果をCSVに保存
        save_results_to_csv(extracted, result_file, result_files)

        # キャッシュデータと新規データをマージして表示
        if year_mode and result_rows:
            display_merged_results(result_rows, extracted, summary_only)
        else:
            display_new_results(extracted, summary_only, year_mode)

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
    parser.add_argument(
        "--year", "-y",
        action="store_true",
        help="過去1年分のメールを取得して集計"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    service = authenticate_gmail()
    fetch_mail_and_extract_info(service, summary_only=args.summary_only, year_mode=args.year)
