"""
股息率计算器单元测试
"""
import json
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# Python 3 uses urllib.request, Python 2 uses urllib2
if sys.version_info[0] >= 3:
    import urllib.request as urllib2
else:
    import urllib2

from src.core.calculator import DividendCalculator, ALIYUN_API_HOST, ALIYUN_API_PATH, ALIYUN_API_APPCODE
from src.data.models import StockBasicInfo

import pandas as pd


class TestDividendCalculator:
    """DividendCalculator 单元测试"""

    @pytest.fixture
    def calculator(self):
        """创建计算器实例"""
        return DividendCalculator()

    @pytest.fixture
    def sample_stock(self):
        """示例股票"""
        return StockBasicInfo(
            code="000157",
            name="中联重科",
            exchange="SZ",
            source_index="中证A500",
            dividend_count=25,
        )

    def test_get_price_from_aliyun_success(self, calculator):
        """测试阿里云API成功获取数据"""
        mock_response = {
            "Code": 0,
            "Msg": "",
            "Obj": [
                {"C": 8.7, "D": "2026-04-13 00:00:00", "O": 8.7, "H": 8.76, "L": 8.6, "V": 581357},
                {"C": 8.76, "D": "2026-04-10 00:00:00", "O": 8.83, "H": 8.93, "L": 8.71, "V": 627640},
                {"C": 8.76, "D": "2026-04-09 00:00:00", "O": 8.7, "H": 8.84, "L": 8.65, "V": 618549},
            ]
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            df = calculator._get_price_from_aliyun("000157")

            assert df is not None
            assert len(df) == 3
            assert "日期" in df.columns
            assert "开盘" in df.columns
            assert "收盘" in df.columns
            assert "最高" in df.columns
            assert "最低" in df.columns
            assert "成交量" in df.columns

    def test_get_price_from_aliyun_pagination(self, calculator):
        """测试阿里云API翻页获取数据 - 第一页满500条且未达目标日期，继续翻页"""
        # 构造500条记录模拟满页
        page1_records = [{"C": 8.7 - i*0.01, "D": f"2025-{(i%12)+1:02d}-{(i%28)+1:02d} 00:00:00", "O": 8.7 - i*0.01, "H": 8.8 - i*0.01, "L": 8.6 - i*0.01, "V": 581357 + i*1000} for i in range(500)]
        # 最后一条日期为2025-01-28，未达到2023-01-01目标
        page1_records[-1] = {"C": 5.0, "D": "2025-01-28 00:00:00", "O": 5.0, "H": 5.1, "L": 4.9, "V": 100000}
        page1 = {
            "Code": 0,
            "Msg": "",
            "Obj": page1_records
        }
        # 第二页返回剩余数据，最后一条到达2023-01-01目标日期
        page2 = {
            "Code": 0,
            "Msg": "",
            "Obj": [
                {"C": 5.0, "D": "2023-12-01 00:00:00", "O": 5.0, "H": 5.1, "L": 4.9, "V": 100000},
                {"C": 4.5, "D": "2023-01-01 00:00:00", "O": 4.5, "H": 4.6, "L": 4.4, "V": 90000},
            ]
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj1 = MagicMock()
            mock_response_obj1.read.return_value = json.dumps(page1).encode()
            mock_response_obj2 = MagicMock()
            mock_response_obj2.read.return_value = json.dumps(page2).encode()
            mock_urlopen.side_effect = [mock_response_obj1, mock_response_obj2]

            df = calculator._get_price_from_aliyun("000157")

            assert df is not None
            # 翻页获取了502条数据 (500 + 2)
            assert len(df) == 502
            # 验证翻页参数 psize=500
            calls = mock_urlopen.call_args_list
            assert "psize=500" in calls[0][0][0].full_url
            assert "pidx=1" in calls[0][0][0].full_url
            assert "pidx=2" in calls[1][0][0].full_url

    def test_get_price_from_aliyun_api_error(self, calculator):
        """测试阿里云API返回错误"""
        mock_response = {
            "Code": 1001,
            "Msg": "接口调用超限",
            "Obj": []
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            df = calculator._get_price_from_aliyun("000157")

            assert df is None

    def test_get_price_from_aliyun_empty_response(self, calculator):
        """测试空响应"""
        mock_response = {"Code": 0, "Msg": "", "Obj": []}

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            df = calculator._get_price_from_aliyun("000157")

            assert df is None

    def test_get_price_from_aliyun_network_error(self, calculator):
        """测试网络错误 - 使用通用Exception验证异常处理"""
        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")

            df = calculator._get_price_from_aliyun("000157")

            assert df is None

    def test_get_price_cache(self, calculator):
        """测试价格缓存 - 缓存在_get_stock_price层，_get_price_from_aliyun直接调用不使用缓存"""
        mock_response = {
            "Code": 0,
            "Msg": "",
            "Obj": [
                {"C": 8.7, "D": "2026-04-13 00:00:00", "O": 8.7, "H": 8.76, "L": 8.6, "V": 581357},
            ]
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            # 通过 _get_stock_price 调用（会检查缓存）
            df1 = calculator._get_stock_price("000157")
            # 第二次调用应该使用缓存
            df2 = calculator._get_stock_price("000157")

            assert df1 is not None
            assert df2 is not None
            # urlopen 只应该被调用一次（第二次从缓存获取）
            assert mock_urlopen.call_count == 1

    def test_calc_yearly_avg_price(self, calculator):
        """测试年度平均股价计算"""
        import pandas as pd

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-01", "2025-06-01", "2025-12-01"]),
            "收盘": [10.0, 12.0, 14.0],
        })

        avg_price = calculator.calc_yearly_avg_price(df, 2025)

        assert avg_price == 12.0

    def test_calc_yearly_avg_price_no_data(self, calculator):
        """测试无数据时的年度平均股价"""
        import pandas as pd

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2024-01-01", "2024-06-01"]),
            "收盘": [10.0, 12.0],
        })

        avg_price = calculator.calc_yearly_avg_price(df, 2025)

        assert avg_price == 0.0

    def test_get_yearly_dividend(self, calculator):
        """测试年度分红数据获取"""
        import pandas as pd

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-15", "2025-07-15"]),
            "每10股派息(元)": [5.0, 3.0],  # 每股0.5 + 0.3 = 0.8
        })

        dividend, count = calculator.get_yearly_dividend(df, 2025)

        assert count == 2
        assert abs(dividend - 0.8) < 0.01

    def test_get_yearly_dividend_no_data(self, calculator):
        """测试无分红数据"""
        import pandas as pd

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2024-01-15", "2024-07-15"]),
            "每10股派息(元)": [5.0, 3.0],
        })

        dividend, count = calculator.get_yearly_dividend(df, 2025)

        assert count == 0
        assert dividend == 0.0

    def test_symbol_conversion_sh(self, calculator):
        """测试沪市代码转换"""
        mock_response = {
            "Code": 0,
            "Msg": "",
            "Obj": []
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            calculator._get_price_from_aliyun("600000")

            # 验证URL包含 SH600000 和 psize=500
            call_args = mock_urlopen.call_args
            url = call_args[0][0].full_url
            assert "symbol=SH600000" in url
            assert "psize=500" in url

    def test_symbol_conversion_sz(self, calculator):
        """测试深市代码转换"""
        mock_response = {
            "Code": 0,
            "Msg": "",
            "Obj": []
        }

        with patch("src.core.calculator.urllib2.urlopen") as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = json.dumps(mock_response).encode()
            mock_urlopen.return_value = mock_response_obj

            calculator._get_price_from_aliyun("000001")

            # 验证URL包含 SZ000001 和 psize=500
            call_args = mock_urlopen.call_args
            url = call_args[0][0].full_url
            assert "symbol=SZ000001" in url
            assert "psize=500" in url


class TestFallbackDetailForRequiredYears:
    """修"cninfo 不收录 0 派息年报 → calculate_stock 误剔除"的 bug

    002714 牧原股份场景：
    - cninfo 缺 2023 年报行（因为 2023 年报 0 派息，公司当时不分红）
    - detail 接口给 2024-04-27 那条"不分配"行，启发式判定为 2023 年报披露
    - fallback 自动补 required_years 缺失的年报行
    """

    @staticmethod
    def _002714_detail_df():
        """002714 真实 detail 接口数据（2026-08-05 实测）"""
        return pd.DataFrame({
            "公告日期": [
                "2026-05-21", "2025-10-10", "2025-06-20", "2024-12-24",
                "2024-04-27", "2023-07-06", "2022-06-01", "2021-05-28",
                "2020-05-28", "2019-06-27", "2018-06-27", "2017-07-04",
                "2016-07-01", "2015-06-03", "2014-06-30",
            ],
            "送股": [0] * 15,
            "转增": [0, 0, 0, 0, 0, 0, 4, 7, 0, 0, 8, 0, 10, 10, 0],
            "派息": [4.27, 9.27521, 5.74269, 8.34793, 0.0, 7.38178,
                     2.48023, 14.61, 5.5, 0.5, 6.9, 6.91, 3.53, 0.61, 2.34],
            "进度": ["实施"] * 4 + ["不分配", "实施"] + ["实施"] * 9,
            "除权除息日": [None] * 15,
            "股权登记日": [None] * 15,
            "红股上市日": [None] * 15,
        })

    def test_fallback_fills_missing_2023_via_detail(self):
        """输入 df 只有 2024+2025，detail 有 2023 年报行（0 派息），
        fallback 后 df 应含 2023 财年记录"""
        calc = DividendCalculator()
        df_existing = pd.DataFrame({
            "财年": [2024, 2025],
            "报告时间": ["2024年报", "2025年报"],
            "派息比例": [3.5, 5.0],
            "_is_cninfo": [True, True],
            "_source": ["cninfo", "cninfo"],
        })

        with patch("src.core.calculator.ak") as mock_ak:
            mock_ak.stock_history_dividend_detail.return_value = self._002714_detail_df()
            new_df, still_missing = calc._fallback_detail_for_required_years(
                "002714", df_existing, [2023, 2024, 2025]
            )

        # 2023 应被补上一条
        assert 2023 in new_df["财年"].tolist(), \
            f"002714 detail fallback 应补 2023 年报记录，实际 cols={new_df['财年'].tolist()}"
        assert 2024 in new_df["财年"].tolist()
        assert 2025 in new_df["财年"].tolist()

        # 2023 补的应该是 0 派息 + 不分配
        row_2023 = new_df[new_df["财年"] == 2023].iloc[0]
        assert row_2023["派息比例"] == 0.0
        assert "不分配" in row_2023["分红类型"]

    def test_fallback_no_trigger_when_cninfo_complete(self):
        """df 已有全部 required_years 时，fallback 不调 detail 接口"""
        calc = DividendCalculator()
        df_existing = pd.DataFrame({
            "财年": [2023, 2024, 2025],
            "报告时间": ["2023年报", "2024年报", "2025年报"],
            "派息比例": [3.0, 3.5, 5.0],
            "_is_cninfo": [True, True, True],
            "_source": ["cninfo"] * 3,
        })

        with patch("src.core.calculator.ak") as mock_ak:
            mock_ak.stock_history_dividend_detail.return_value = pd.DataFrame()
            calc._fallback_detail_for_required_years(
                "000001", df_existing, [2023, 2024, 2025]
            )

        mock_ak.stock_history_dividend_detail.assert_not_called()

    def test_fallback_handles_detail_failure_gracefully(self):
        """detail 接口抛错时 fallback 不 throw，返回原 df 不变"""
        calc = DividendCalculator()
        df_existing = pd.DataFrame({
            "财年": [2024, 2025],
            "报告时间": ["2024年报", "2025年报"],
            "派息比例": [3.5, 5.0],
            "_is_cninfo": [True, True],
            "_source": ["cninfo", "cninfo"],
        })

        with patch("src.core.calculator.ak") as mock_ak:
            mock_ak.stock_history_dividend_detail.side_effect = Exception("接口超时")
            new_df, still_missing = calc._fallback_detail_for_required_years(
                "002714", df_existing, [2023, 2024, 2025]
            )

        # fallback 失败时不应抛错，df 应保留原内容
        assert still_missing == [2023]
        assert 2024 in new_df["财年"].tolist()
        assert 2025 in new_df["财年"].tolist()
