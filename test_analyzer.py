import csv
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from analyzer import DebitAnalyzer


class TestDebitAnalyzer:
    def create_test_csv(self, data, include_cache_header=True):
        """テスト用のCSVファイルを作成する"""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv", encoding="utf-8"
        ) as temp_file:
            if include_cache_header:
                temp_file.write("# cached_at: 2024-01-15\n")

            writer = csv.DictWriter(temp_file, fieldnames=["年月", "振替先", "金額"])
            writer.writeheader()
            writer.writerows(data)

            return temp_file.name

    def test_init_with_csv_file_path(self):
        """CSVファイルパスを指定してインスタンス化"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            assert analyzer.csv_file_path == csv_file
            assert len(analyzer.data) == 2
            assert analyzer.data[0]["振替先"] == "テスト会社A"
        finally:
            Path(csv_file).unlink()

    @patch("analyzer.sorted")
    @patch("analyzer.Path.glob")
    @patch("analyzer.Path.mkdir")
    def test_find_latest_csv_success(self, mock_mkdir, mock_glob, mock_sorted):
        """最新のCSVファイルを正常に見つける"""
        # Pathオブジェクトのモック
        mock_path = Mock()
        mock_path.__str__ = Mock(return_value="result_debit_2024-01-20.csv")

        mock_glob.return_value = [mock_path]
        mock_sorted.return_value = [mock_path]  # sortedの結果をモック

        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        result = analyzer._find_latest_csv()

        assert result == "result_debit_2024-01-20.csv"

    @patch("analyzer.Path.glob")
    @patch("analyzer.Path.mkdir")
    def test_find_latest_csv_no_files(self, mock_mkdir, mock_glob):
        """CSVファイルが見つからない場合のエラー"""
        mock_glob.return_value = []

        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)

        with pytest.raises(
            FileNotFoundError, match="result_debit_.*csvファイルが見つかりません"
        ):
            analyzer._find_latest_csv()

    def test_load_data_with_valid_data(self):
        """有効なデータの読み込み"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
            {"年月": "2024-01", "振替先": "テスト会社C", "金額": "0"},  # 除外される
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
            analyzer.csv_file_path = csv_file
            data = analyzer._load_data()

            # 金額0の行は除外される
            assert len(data) == 2
            assert data[0]["振替先"] == "テスト会社A"
            assert data[1]["振替先"] == "テスト会社B"
        finally:
            Path(csv_file).unlink()

    def test_load_data_with_comments(self):
        """コメント行があるデータの読み込み"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
        ]

        csv_file = self.create_test_csv(test_data, include_cache_header=True)

        try:
            analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
            analyzer.csv_file_path = csv_file
            data = analyzer._load_data()

            assert len(data) == 1
            assert data[0]["振替先"] == "テスト会社A"
        finally:
            Path(csv_file).unlink()

    def test_get_summary_with_data(self):
        """データありの場合のサマリ取得"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
            {"年月": "2024-02", "振替先": "テスト会社A", "金額": "12000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            summary = analyzer.get_summary()

            assert summary["total_amount"] == 27000
            assert summary["total_count"] == 3
            assert summary["month_count"] == 2
            assert summary["company_count"] == 2
            assert summary["date_range"] == "2024-01 ~ 2024-02"
        finally:
            Path(csv_file).unlink()

    def test_get_summary_empty_data(self):
        """データなしの場合のサマリ取得"""
        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        analyzer.data = []

        summary = analyzer.get_summary()

        assert summary["total_amount"] == 0
        assert summary["total_count"] == 0
        assert summary["month_count"] == 0
        assert summary["company_count"] == 0
        assert summary["date_range"] is None

    @patch("builtins.print")
    def test_print_summary_with_data(self, mock_print):
        """データありの場合のサマリ表示"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            analyzer.print_summary()

            # print が複数回呼ばれることを確認
            assert mock_print.call_count > 5
        finally:
            Path(csv_file).unlink()

    @patch("builtins.print")
    def test_print_summary_summary_only(self, mock_print):
        """サマリのみ表示モード"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            analyzer.print_summary(summary_only=True)

            mock_print.assert_called_once_with("¥15,000")
        finally:
            Path(csv_file).unlink()

    def test_get_monthly_summary(self):
        """月別サマリの取得"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
            {"年月": "2024-02", "振替先": "テスト会社A", "金額": "12000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            monthly_summary = analyzer._get_monthly_summary()

            assert monthly_summary["2024-01"]["total"] == 15000
            assert monthly_summary["2024-01"]["count"] == 2
            assert monthly_summary["2024-02"]["total"] == 12000
            assert monthly_summary["2024-02"]["count"] == 1
        finally:
            Path(csv_file).unlink()

    def test_get_company_summary(self):
        """会社別サマリの取得"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-01", "振替先": "テスト会社B", "金額": "5000"},
            {"年月": "2024-02", "振替先": "テスト会社A", "金額": "12000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            company_summary = analyzer._get_company_summary()

            assert company_summary["テスト会社A"]["total"] == 22000
            assert company_summary["テスト会社A"]["count"] == 2
            assert company_summary["テスト会社B"]["total"] == 5000
            assert company_summary["テスト会社B"]["count"] == 1
        finally:
            Path(csv_file).unlink()

    @patch("builtins.print")
    def test_print_detailed_results_empty_data(self, mock_print):
        """空データの詳細結果表示"""
        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        analyzer.data = []

        analyzer.print_detailed_results(year_mode=False)
        mock_print.assert_called_once_with("口座振替情報は見つかりませんでした")

        mock_print.reset_mock()
        analyzer.print_detailed_results(year_mode=True)
        mock_print.assert_called_once_with(
            "過去1年分の口座振替情報は見つかりませんでした"
        )

    @patch("builtins.print")
    def test_print_detailed_results_with_data(self, mock_print):
        """データありの詳細結果表示"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-02", "振替先": "テスト会社B", "金額": "5000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            analyzer.print_detailed_results(year_mode=False)

            # 複数回のprint呼び出しを確認
            assert mock_print.call_count > 0
        finally:
            Path(csv_file).unlink()

    @patch("plotly.express.bar")
    @patch("pandas.DataFrame")
    def test_create_monthly_stacked_bar_chart_empty_data(self, mock_df, mock_bar):
        """空データでの棒グラフ作成"""
        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        analyzer.data = []

        with patch("builtins.print") as mock_print:
            result = analyzer.create_monthly_stacked_bar_chart(show_chart=False)

            assert result is None
            mock_print.assert_called_once_with("データがありません")

    @patch("plotly.express.bar")
    def test_create_monthly_stacked_bar_chart_with_data(self, mock_bar):
        """データありでの棒グラフ作成"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-02", "振替先": "テスト会社B", "金額": "5000"},
        ]

        # mock figure オブジェクト
        mock_fig = Mock()
        mock_bar.return_value = mock_fig

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            result = analyzer.create_monthly_stacked_bar_chart(show_chart=False)

            assert result == mock_fig
            mock_bar.assert_called_once()
        finally:
            Path(csv_file).unlink()

    @patch("plotly.graph_objects.Figure")
    def test_create_company_pie_chart_empty_data(self, mock_figure):
        """空データでの円グラフ作成"""
        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        analyzer.data = []

        with patch("builtins.print") as mock_print:
            result = analyzer.create_company_pie_chart(show_chart=False)

            assert result is None
            mock_print.assert_called_once_with("データがありません")

    @patch("plotly.graph_objects.Figure")
    def test_create_company_pie_chart_with_data(self, mock_figure):
        """データありでの円グラフ作成"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-02", "振替先": "テスト会社B", "金額": "5000"},
        ]

        # mock figure オブジェクト
        mock_fig = Mock()
        mock_figure.return_value = mock_fig

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            result = analyzer.create_company_pie_chart(show_chart=False)

            assert result == mock_fig
            mock_figure.assert_called_once()
        finally:
            Path(csv_file).unlink()

    @patch("plotly.subplots.make_subplots")
    def test_create_combined_dashboard_empty_data(self, mock_subplots):
        """空データでのダッシュボード作成"""
        analyzer = DebitAnalyzer.__new__(DebitAnalyzer)
        analyzer.data = []

        with patch("builtins.print") as mock_print:
            result = analyzer.create_combined_dashboard(show_chart=False)

            assert result is None
            mock_print.assert_called_once_with("データがありません")

    def test_create_combined_dashboard_with_data(self):
        """データありでのダッシュボード作成"""
        test_data = [
            {"年月": "2024-01", "振替先": "テスト会社A", "金額": "10000"},
            {"年月": "2024-02", "振替先": "テスト会社B", "金額": "5000"},
        ]

        csv_file = self.create_test_csv(test_data)

        try:
            analyzer = DebitAnalyzer(csv_file)
            result = analyzer.create_combined_dashboard(show_chart=False)

            # 実際のFigureオブジェクトが返されることを確認
            assert result is not None
            assert hasattr(result, "show")  # plotly figure の特徴的なメソッドをチェック
            assert hasattr(result, "data")  # figureのdataプロパティが存在することを確認
        finally:
            Path(csv_file).unlink()


if __name__ == "__main__":
    pytest.main([__file__])
