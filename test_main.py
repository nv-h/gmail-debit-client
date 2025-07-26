import base64
import datetime
from unittest.mock import Mock, mock_open, patch

import pytest

from main import (
    display_cached_results,
    display_new_results,
    extract_debit_info_from_message,
    extract_debit_info_from_messages,
    get_current_month_info,
    get_message_body,
    get_search_query_date,
    is_valid_sender,
    load_existing_cache_data,
    save_results_to_csv,
    search_gmail_messages,
    validate_amount,
)


class TestGetMessageBody:
    def test_get_message_body_from_body_data(self):
        # テスト用のペイロード（base64エンコードされたデータ）
        test_text = "テストメール内容"
        encoded_data = base64.urlsafe_b64encode(test_text.encode("utf-8")).decode(
            "ascii"
        )

        payload = {"body": {"data": encoded_data}}

        result = get_message_body(payload)
        assert result == test_text

    def test_get_message_body_from_parts(self):
        test_text = "テストメール内容"
        encoded_data = base64.urlsafe_b64encode(test_text.encode("utf-8")).decode(
            "ascii"
        )

        payload = {
            "parts": [{"mimeType": "text/plain", "body": {"data": encoded_data}}]
        }

        result = get_message_body(payload)
        assert result == test_text

    def test_get_message_body_no_data(self):
        payload = {}
        result = get_message_body(payload)
        assert result == ""

    @patch("chardet.detect")
    def test_get_message_body_with_chardet(self, mock_detect):
        test_text = "テストメール内容"
        test_bytes = test_text.encode("shift_jis")
        encoded_data = base64.urlsafe_b64encode(test_bytes).decode("ascii")

        mock_detect.return_value = {"encoding": "shift_jis", "confidence": 0.8}

        payload = {"body": {"data": encoded_data}}

        result = get_message_body(payload)
        assert result == test_text


class TestValidateAmount:
    def test_validate_amount_valid_integer(self):
        assert validate_amount("1000") == "1000"

    def test_validate_amount_valid_float(self):
        assert validate_amount("1000.50") == "1000.50"

    def test_validate_amount_negative(self):
        assert validate_amount("-100") == "0"

    def test_validate_amount_invalid_string(self):
        assert validate_amount("abc") == "0"

    def test_validate_amount_none(self):
        assert validate_amount(None) == "0"

    def test_validate_amount_empty_string(self):
        assert validate_amount("") == "0"


class TestIsValidSender:
    def test_is_valid_sender_exact_match(self):
        headers = [{"name": "From", "value": "post_master@netbk.co.jp"}]
        assert is_valid_sender(headers) == True

    def test_is_valid_sender_domain_match(self):
        headers = [{"name": "From", "value": "test@netbk.co.jp"}]
        assert is_valid_sender(headers) == True

    def test_is_valid_sender_invalid(self):
        headers = [{"name": "From", "value": "spam@example.com"}]
        assert is_valid_sender(headers) == False

    def test_is_valid_sender_case_insensitive(self):
        headers = [{"name": "FROM", "value": "POST_MASTER@NETBK.CO.JP"}]
        assert is_valid_sender(headers) == True

    def test_is_valid_sender_no_from_header(self):
        headers = [{"name": "Subject", "value": "テスト"}]
        assert is_valid_sender(headers) == False


class TestExtractDebitInfoFromMessage:
    @patch("main.get_message_body")
    def test_extract_debit_info_from_message_success(self, mock_get_body):
        # モックサービスとメッセージデータ
        mock_service = Mock()
        mock_msg_data = {
            "payload": {
                "headers": [{"name": "From", "value": "post_master@netbk.co.jp"}]
            }
        }
        mock_service.users().messages().get().execute.return_value = mock_msg_data

        # メール本文のモック
        test_body = """
        口座振替先：テスト株式会社
        引落金額：¥10,000円
        """
        mock_get_body.return_value = test_body

        msg = {"id": "test_id"}
        year_month = "2024-01"

        result = extract_debit_info_from_message(mock_service, msg, year_month)

        expected = {"年月": "2024-01", "振替先": "テスト株式会社", "金額": "10000"}
        assert result == expected

    @patch("main.get_message_body")
    def test_extract_debit_info_from_message_invalid_sender(self, mock_get_body):
        mock_service = Mock()
        mock_msg_data = {
            "payload": {"headers": [{"name": "From", "value": "spam@example.com"}]}
        }
        mock_service.users().messages().get().execute.return_value = mock_msg_data

        msg = {"id": "test_id"}
        year_month = "2024-01"

        result = extract_debit_info_from_message(mock_service, msg, year_month)
        assert result is None

    @patch("main.get_message_body")
    def test_extract_debit_info_from_message_no_match(self, mock_get_body):
        mock_service = Mock()
        mock_msg_data = {
            "payload": {
                "headers": [{"name": "From", "value": "post_master@netbk.co.jp"}]
            }
        }
        mock_service.users().messages().get().execute.return_value = mock_msg_data

        mock_get_body.return_value = "関係ないメール内容"

        msg = {"id": "test_id"}
        year_month = "2024-01"

        result = extract_debit_info_from_message(mock_service, msg, year_month)

        expected = {"年月": "2024-01", "振替先": "[不明]", "金額": "0"}
        assert result == expected


class TestLoadExistingCacheData:
    @patch("glob.glob")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_load_existing_cache_data_with_cache(
        self, mock_file, mock_exists, mock_glob
    ):
        # ファイルが存在する場合のテスト
        mock_glob.return_value = ["result_debit_2024-01-15.csv"]
        mock_exists.return_value = True

        csv_content = """# cached_at: 2024-01-15
年月,振替先,金額
2024-01,テスト会社,10000
2024-02,別の会社,5000
"""
        mock_file.return_value.readline.return_value = "# cached_at: 2024-01-15\n"
        mock_file.return_value.__iter__.return_value = csv_content.split("\n")[1:]

        with patch("csv.DictReader") as mock_reader:
            mock_reader.return_value = [
                {"年月": "2024-01", "振替先": "テスト会社", "金額": "10000"},
                {"年月": "2024-02", "振替先": "別の会社", "金額": "5000"},
            ]

            result_file, result_created_at, result_rows, result_files = (
                load_existing_cache_data("2024-01")
            )

            assert result_file == "result_debit_2024-01-15.csv"
            assert result_created_at == "2024-01-15"
            assert len(result_rows) == 1
            assert result_rows[0]["年月"] == "2024-01"

    @patch("glob.glob")
    def test_load_existing_cache_data_no_files(self, mock_glob):
        mock_glob.return_value = []

        result_file, result_created_at, result_rows, result_files = (
            load_existing_cache_data("2024-01")
        )

        assert result_file is None
        assert result_created_at is None
        assert result_rows == []
        assert result_files == []


class TestGetSearchQueryDate:
    def test_get_search_query_date_with_valid_cache_date(self):
        first_day = datetime.date(2024, 1, 1)
        result_created_at = "2024-01-15"

        result = get_search_query_date(result_created_at, first_day)
        assert result == "2024/01/15"

    def test_get_search_query_date_invalid_cache_date(self):
        first_day = datetime.date(2024, 1, 1)
        result_created_at = "invalid-date"

        result = get_search_query_date(result_created_at, first_day)
        assert result == "2024/01/01"

    def test_get_search_query_date_no_cache_date(self):
        first_day = datetime.date(2024, 1, 1)
        result_created_at = None

        result = get_search_query_date(result_created_at, first_day)
        assert result == "2024/01/01"


class TestSearchGmailMessages:
    def test_search_gmail_messages_success(self):
        mock_service = Mock()
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}]
        }

        query_date = "2024/01/01"
        messages = search_gmail_messages(mock_service, query_date)

        assert len(messages) == 2
        assert messages[0]["id"] == "msg1"
        assert messages[1]["id"] == "msg2"

        # クエリが正しく構築されているかチェック
        expected_query = "after:2024/01/01 subject:(口座振替)"
        mock_service.users().messages().list.assert_called_with(
            userId="me", q=expected_query
        )

    def test_search_gmail_messages_no_results(self):
        mock_service = Mock()
        mock_service.users().messages().list().execute.return_value = {}

        query_date = "2024/01/01"
        messages = search_gmail_messages(mock_service, query_date)

        assert messages == []


class TestExtractDebitInfoFromMessages:
    @patch("main.extract_debit_info_from_message")
    def test_extract_debit_info_from_messages_success(self, mock_extract):
        mock_service = Mock()
        messages = [{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}]

        # モック関数の戻り値を設定
        mock_extract.side_effect = [
            {"年月": "2024-01", "振替先": "会社A", "金額": "1000"},
            None,  # 無効なメッセージ
            {"年月": "2024-01", "振替先": "会社B", "金額": "2000"},
        ]

        result = extract_debit_info_from_messages(mock_service, messages, "2024-01")

        assert len(result) == 2
        assert result[0]["振替先"] == "会社A"
        assert result[1]["振替先"] == "会社B"


class TestSaveResultsToCsv:
    @patch("datetime.date")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.remove")
    def test_save_results_to_csv_new_file(
        self, mock_remove, mock_file, mock_exists, mock_date
    ):
        mock_date.today.return_value.strftime.return_value = "2024-01-15"
        mock_exists.return_value = False

        extracted = [{"年月": "2024-01", "振替先": "テスト会社", "金額": "10000"}]

        result_file = save_results_to_csv(extracted, None, [])

        assert result_file == "result_debit_2024-01-15.csv"
        mock_file.assert_called()

    def test_save_results_to_csv_empty_data(self):
        result = save_results_to_csv([], None, [])
        assert result is None


class TestDisplayNewResults:
    @patch("builtins.print")
    def test_display_new_results_with_data(self, mock_print):
        extracted = [
            {"年月": "2024-01", "振替先": "会社A", "金額": "1000"},
            {"年月": "2024-01", "振替先": "会社B", "金額": "2000"},
        ]

        display_new_results(extracted, summary_only=False)

        # print が呼ばれたことを確認
        assert mock_print.call_count > 0

    @patch("builtins.print")
    def test_display_new_results_summary_only(self, mock_print):
        extracted = [
            {"年月": "2024-01", "振替先": "会社A", "金額": "1000"},
            {"年月": "2024-01", "振替先": "会社B", "金額": "2000"},
        ]

        display_new_results(extracted, summary_only=True)

        mock_print.assert_called_once_with("¥3,000")

    @patch("builtins.print")
    def test_display_new_results_no_data_summary(self, mock_print):
        display_new_results([], summary_only=True)
        mock_print.assert_called_once_with("¥0")


class TestDisplayCachedResults:
    @patch("builtins.print")
    def test_display_cached_results_summary_only(self, mock_print):
        result_rows = [
            {"年月": "2024-01", "振替先": "会社A", "金額": "1000"},
            {"年月": "2024-01", "振替先": "会社B", "金額": "2000"},
        ]

        display_cached_results("test.csv", result_rows, summary_only=True)

        mock_print.assert_called_once_with("¥3,000")

    @patch("builtins.print")
    def test_display_cached_results_detailed(self, mock_print):
        result_rows = [{"年月": "2024-01", "振替先": "会社A", "金額": "1000"}]

        display_cached_results("test.csv", result_rows, summary_only=False)

        assert mock_print.call_count > 0


class TestGetCurrentMonthInfo:
    def test_get_current_month_info(self):
        with patch("main.datetime.date") as mock_date:
            mock_today = Mock()
            mock_today.replace.return_value = Mock()
            mock_today.strftime.return_value = "2024-01"

            mock_date.today.return_value = mock_today

            today, first_day, year_month = get_current_month_info()

            assert today == mock_today
            assert first_day == mock_today.replace.return_value
            assert year_month == "2024-01"

            mock_today.replace.assert_called_once_with(day=1)
            mock_today.strftime.assert_called_once_with("%Y-%m")


if __name__ == "__main__":
    pytest.main([__file__])
