import csv
from collections import defaultdict
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 設定
OUTPUT_DIR = "outputs"


class DebitAnalyzer:
    """口座振替データの分析・可視化クラス"""

    def __init__(self, csv_file_path: str | None = None):
        """
        初期化

        Args:
            csv_file_path: CSVファイルのパス。Noneの場合は最新のresult_debit_*.csvを使用
        """
        if csv_file_path is None:
            csv_file_path = self._find_latest_csv()

        self.csv_file_path = csv_file_path
        self.data = self._load_data()

    def _find_latest_csv(self) -> str:
        """最新のresult_debit_*.csvファイルを検索"""
        # 出力ディレクトリを作成
        Path(OUTPUT_DIR).mkdir(exist_ok=True)

        result_files = sorted(Path(OUTPUT_DIR).glob("result_debit_*.csv"), reverse=True)
        if not result_files:
            msg = f"{OUTPUT_DIR}/result_debit_*.csvファイルが見つかりません"
            raise FileNotFoundError(msg)
        return str(result_files[0])

    def _load_data(self) -> list[dict[str, str]]:
        """CSVファイルからデータを読み込み"""
        with Path(self.csv_file_path).open(encoding="utf-8") as f:
            lines = f.readlines()
            # コメント行をスキップ
            csv_lines = [line for line in lines if not line.startswith("#")]
            reader = csv.DictReader(csv_lines)
            # 金額0の行を除外してリスト作成
            return [row for row in reader if float(row["金額"]) > 0]

    def get_summary(self) -> dict:
        """データのサマリを取得"""
        if not self.data:
            return {
                "total_amount": 0,
                "total_count": 0,
                "month_count": 0,
                "company_count": 0,
                "date_range": None,
            }

        total_amount = sum(float(row["金額"]) for row in self.data)
        total_count = len(self.data)

        # 月別集計
        months = set(row["年月"] for row in self.data)
        month_count = len(months)

        # 会社別集計
        companies = set(row["振替先"] for row in self.data)
        company_count = len(companies)

        # 期間
        sorted_months = sorted(months)
        date_range = (
            f"{sorted_months[0]} ~ {sorted_months[-1]}" if sorted_months else None
        )

        return {
            "total_amount": total_amount,
            "total_count": total_count,
            "month_count": month_count,
            "company_count": company_count,
            "date_range": date_range,
        }

    def print_summary(self, summary_only=False):
        """サマリを表示"""
        summary = self.get_summary()

        if summary_only:
            print(f"¥{summary['total_amount']:,.0f}")
            return

        print("=== 口座振替データ サマリ ===")
        print(f"データソース: {self.csv_file_path}")
        print(f"期間: {summary['date_range']}")
        print(f"総振替金額: ¥{summary['total_amount']:,.0f}")
        print(f"振替件数: {summary['total_count']}件")
        print(f"対象月数: {summary['month_count']}ヶ月")
        print(f"振替先数: {summary['company_count']}社")

        # 月別サマリ
        monthly_data = self._get_monthly_summary()
        print("\n=== 月別サマリ ===")
        for month, data in sorted(monthly_data.items()):
            print(f"{month}: ¥{data['total']:,.0f} ({data['count']}件)")

        # 会社別サマリ
        company_data = self._get_company_summary()
        print("\n=== 振替先別サマリ ===")
        for company, data in sorted(
            company_data.items(), key=lambda x: x[1]["total"], reverse=True
        ):
            print(f"{company}: ¥{data['total']:,.0f} ({data['count']}件)")

    def print_detailed_results(self, year_mode=False, cached_source=None, new_count=0):
        """詳細な結果表示（main.pyの表示機能を統合）"""
        if not self.data:
            if year_mode:
                print("過去1年分の口座振替情報は見つかりませんでした")
            else:
                print("口座振替情報は見つかりませんでした")
            return

        monthly_data = self._get_monthly_summary()
        total = sum(float(row["金額"]) for row in self.data)

        if cached_source:
            print(f"結果({cached_source})から取得:")

        if year_mode:
            print("過去1年分の口座振替情報:")
            for month in sorted(monthly_data.keys()):
                print(f"\n{month} (¥{monthly_data[month]['total']:,.0f})")
                month_rows = [row for row in self.data if row["年月"] == month]
                for row in month_rows:
                    print(f"  {row['振替先']} ¥{float(row['金額']):,.0f}")
            print(f"\n過去1年分の口座振替合計：¥{total:,.0f}")
        else:
            for row in self.data:
                print(f"{row['年月']} {row['振替先']} ¥{float(row['金額']):,.0f}")
            print(f"今月の口座振替合計：¥{total:,.0f}")

        if new_count > 0:
            print(
                f"新規取得分：¥{sum(float(row['金額']) for row in self.data[-new_count:]):,.0f}"
            )

    def _get_monthly_summary(self) -> dict:
        """月別サマリを取得"""
        monthly_data = defaultdict(lambda: {"total": 0, "count": 0})
        for row in self.data:
            month = row["年月"]
            amount = float(row["金額"])
            monthly_data[month]["total"] += amount
            monthly_data[month]["count"] += 1
        return dict(monthly_data)

    def _get_company_summary(self) -> dict:
        """会社別サマリを取得"""
        company_data = defaultdict(lambda: {"total": 0, "count": 0})
        for row in self.data:
            company = row["振替先"]
            amount = float(row["金額"])
            company_data[company]["total"] += amount
            company_data[company]["count"] += 1
        return dict(company_data)

    def create_monthly_stacked_bar_chart(
        self, save_path: str | None = None, *, show_chart: bool = True
    ):
        """月別振替先ごとの積み上げ棒グラフを作成（Plotly版）"""
        if not self.data:
            print("データがありません")
            return None

        # データをDataFrameに変換
        df = pd.DataFrame(self.data)
        df["金額"] = df["金額"].astype(float)

        # 同一振替先を区別するために、年月+振替先でグループ化し、複数ある場合は番号付け
        df_with_index = df.copy()
        df_with_index["振替先_区別"] = (
            df_with_index.groupby(["年月", "振替先"]).cumcount() + 1
        )
        df_with_index["振替先_表示"] = df_with_index.apply(
            lambda row: f"{row['振替先']} ({row['振替先_区別']})"
            if df_with_index[
                (df_with_index["年月"] == row["年月"])
                & (df_with_index["振替先"] == row["振替先"])
            ].shape[0]
            > 1
            else row["振替先"],
            axis=1,
        )

        # データ期間を取得
        months = sorted(df["年月"].unique())
        period_text = f"{months[0]} ~ {months[-1]} ({len(months)}ヶ月)"

        # Plotlyの積み上げ棒グラフを作成
        fig = px.bar(
            df_with_index,
            x="年月",
            y="金額",
            color="振替先_表示",
            title=f"月別口座振替額（振替先別積み上げ）<br>{period_text}",
            labels={"金額": "振替額（円）", "年月": "年月", "振替先_表示": "振替先"},
        )

        # レイアウトの調整
        fig.update_layout(
            height=600,
            showlegend=True,
            font={"size": 12},
            title={"font": {"size": 16}},
            xaxis={"tickangle": 0},
            yaxis={"tickformat": "¥,.0f"},
        )

        # テキストを表示（金額のみ、フォーマット修正）
        fig.update_traces(
            texttemplate="¥%{y:,.0f}",
            textposition="inside",
            textfont_size=10,
            textfont_color="white",
        )

        # 保存
        if save_path:
            # 出力ディレクトリを作成
            Path(OUTPUT_DIR).mkdir(exist_ok=True)

            # フルパスでない場合はOUTPUT_DIRを付ける
            if not Path(save_path).is_absolute() and not save_path.startswith(
                OUTPUT_DIR
            ):
                save_path = f"{OUTPUT_DIR}/{save_path}"

            if save_path.endswith(".png"):
                fig.write_image(save_path, width=1200, height=600)
                print(f"グラフを保存しました: {save_path}")
            else:
                html_path = save_path
                fig.write_html(html_path)
                print(f"グラフを保存しました: {html_path}")

        # 表示
        if show_chart:
            fig.show()

        return fig

    def create_company_pie_chart(
        self, save_path: str | None = None, *, show_chart: bool = True
    ):
        """振替先別の円グラフを作成（月平均・Plotly版）"""
        if not self.data:
            print("データがありません")
            return None

        company_data = self._get_company_summary()

        # データ期間を取得
        months = set(row["年月"] for row in self.data)
        month_count = len(months)
        sorted_months = sorted(months)
        period_text = f"{sorted_months[0]} ~ {sorted_months[-1]} ({month_count}ヶ月)"

        # データの準備（月平均）
        companies = list(company_data)
        monthly_averages = [
            data["total"] / month_count for data in company_data.values()
        ]

        # Plotlyの円グラフを作成
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=companies,
                    values=monthly_averages,
                    textinfo="label+value+percent",
                    texttemplate="%{label}<br>¥%{value:,.0f}<br>(%{percent})",
                    hovertemplate="<b>%{label}</b><br>月平均額: ¥%{value:,.0f}<br>割合: %{percent}<br><extra></extra>",
                )
            ]
        )

        # レイアウトの調整
        fig.update_layout(
            title={"text": f"振替先別月平均額<br>{period_text}", "font": {"size": 16}},
            height=600,
            font={"size": 12},
        )

        # 保存
        if save_path:
            # 出力ディレクトリを作成
            Path(OUTPUT_DIR).mkdir(exist_ok=True)

            # フルパスでない場合はOUTPUT_DIRを付ける
            if not Path(save_path).is_absolute() and not save_path.startswith(
                OUTPUT_DIR
            ):
                save_path = f"{OUTPUT_DIR}/{save_path}"

            if save_path.endswith(".png"):
                fig.write_image(save_path, width=1200, height=600)
                print(f"グラフを保存しました: {save_path}")
            else:
                html_path = save_path
                fig.write_html(html_path)
                print(f"グラフを保存しました: {html_path}")

        # 表示
        if show_chart:
            fig.show()

        return fig

    def create_combined_dashboard(
        self, save_path: str | None = None, *, show_chart: bool = True
    ):
        """月別棒グラフと円グラフを1画面に表示するダッシュボードを作成"""
        if not self.data:
            print("データがありません")
            return None

        # データの準備
        df = pd.DataFrame(self.data)
        df["金額"] = df["金額"].astype(float)

        # 同一振替先を区別するための処理
        df_with_index = df.copy()
        df_with_index["振替先_区別"] = (
            df_with_index.groupby(["年月", "振替先"]).cumcount() + 1
        )
        df_with_index["振替先_表示"] = df_with_index.apply(
            lambda row: f"{row['振替先']} ({row['振替先_区別']})"
            if df_with_index[
                (df_with_index["年月"] == row["年月"])
                & (df_with_index["振替先"] == row["振替先"])
            ].shape[0]
            > 1
            else row["振替先"],
            axis=1,
        )

        # データ期間を取得
        months = sorted(df["年月"].unique())
        period_text = f"{months[0]} ~ {months[-1]} ({len(months)}ヶ月)"

        # サブプロットを作成（2行1列）
        fig = make_subplots(
            rows=2,
            cols=1,
            specs=[[{"type": "bar"}], [{"type": "pie"}]],
            subplot_titles=("月別口座振替額（振替先別積み上げ）", "振替先別月平均額"),
            vertical_spacing=0.15,
            row_heights=[0.6, 0.4],  # 上のグラフを大きく、下を小さく
        )

        # 棒グラフ用のデータ準備（px.barで使用したデータを手動で追加）
        colors = px.colors.qualitative.Set3
        companies = df_with_index["振替先_表示"].unique()
        color_map = {
            company: colors[i % len(colors)] for i, company in enumerate(companies)
        }

        for company in companies:
            company_data = df_with_index[df_with_index["振替先_表示"] == company]
            # 会社名を短縮（株式会社を除去、番号付きの場合は括弧内を削除）
            short_names = []
            for name in company_data["振替先_表示"]:
                short_name = name.replace("株式会社", "").replace("Co., Ltd.", "")
                if "(" in short_name:
                    short_name = short_name.split("(")[0].strip()
                short_names.append(short_name)

            fig.add_trace(
                go.Bar(
                    x=company_data["年月"],
                    y=company_data["金額"],
                    name=company,
                    text=short_names,
                    textposition="inside",
                    textfont={"size": 9, "color": "white"},
                    marker_color=color_map[company],
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

        # 円グラフ用のデータ準備
        company_data = self._get_company_summary()
        months_set = set(row["年月"] for row in self.data)
        month_count = len(months_set)

        companies_pie = list(company_data.keys())
        monthly_averages = [
            data["total"] / month_count for data in company_data.values()
        ]

        fig.add_trace(
            go.Pie(
                labels=companies_pie,
                values=monthly_averages,
                textinfo="label+value+percent",
                texttemplate="%{label}<br>¥%{value:,.0f}<br>(%{percent})",
                hovertemplate="<b>%{label}</b><br>月平均額: ¥%{value:,.0f}<br>割合: %{percent}<br><extra></extra>",
                showlegend=False,  # 左側の凡例と重複を避ける
            ),
            row=2,
            col=1,
        )

        # レイアウトの調整
        fig.update_layout(
            title={
                "text": f"口座振替データ ダッシュボード<br><span style='font-size:14px'>{period_text}</span>",
                "font": {"size": 18},
                "x": 0.5,
            },
            height=900,
            font={"size": 12},
            barmode="stack",
        )

        # X軸とY軸のフォーマット（棒グラフ用）
        fig.update_xaxes(title_text="年月", row=1, col=1)
        fig.update_yaxes(title_text="振替額（円）", tickformat="¥,.0f", row=1, col=1)

        # 保存
        if save_path:
            # 出力ディレクトリを作成
            Path(OUTPUT_DIR).mkdir(exist_ok=True)

            # フルパスでない場合はOUTPUT_DIRを付ける
            if not Path(save_path).is_absolute() and not save_path.startswith(
                OUTPUT_DIR
            ):
                save_path = f"{OUTPUT_DIR}/{save_path}"

            if save_path.endswith(".png"):
                fig.write_image(save_path, width=1200, height=900)
                print(f"ダッシュボードを保存しました: {save_path}")
            else:
                html_path = save_path
                fig.write_html(html_path)
                print(f"ダッシュボードを保存しました: {html_path}")

        # 表示
        if show_chart:
            fig.show()

        return fig


def main():
    """メイン関数（スタンドアロン実行用）"""
    try:
        # アナライザーの初期化
        analyzer = DebitAnalyzer()

        # サマリ表示
        analyzer.print_summary()

        print("\n" + "=" * 50)
        print("グラフを生成しています...")

        # ダッシュボード（2つのグラフを1画面に表示）
        analyzer.create_combined_dashboard(save_path="dashboard.html", show_chart=True)

    except Exception as e:
        print(f"エラーが発生しました: {e}")


if __name__ == "__main__":
    main()
