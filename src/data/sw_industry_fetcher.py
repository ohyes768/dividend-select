"""
申万行业数据获取器
数据源：pywencai 问财 API
"""
import os
from typing import Optional

import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger

logger = setup_logger(__name__)


def _smart_column_rename(df: pd.DataFrame) -> pd.DataFrame:
    """智能列名重命名，处理各种格式的列名"""
    new_columns = {}
    used_names = set()

    for col in df.columns:
        original_col = col
        new_name = None

        if '股票代码' in col or 'code' in col.lower():
            if '股票代码' not in used_names:
                new_name = '股票代码'
        elif '股票简称' in col or 'name' in col.lower():
            if '股票简称' not in used_names:
                new_name = '股票简称'
        elif '所属申万行业' in col or '申万行业' in col:
            if '申万行业' not in used_names:
                new_name = '申万行业'
        elif '总股本' in col:
            if '总股本' not in used_names:
                new_name = '总股本'
        elif '收盘价' in col or '最新价' in col or '现价' in col:
            if '最新价' not in used_names:
                new_name = '最新价'
        else:
            new_name = col
            if new_name in used_names:
                new_name = f"{col}_{id(col)}"

        if new_name:
            new_columns[col] = new_name
            used_names.add(new_name)

    df = df.rename(columns=new_columns)

    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    return df


def _parse_hierarchy(industry_str: str) -> tuple[str, str, str]:
    """解析申万行业层级字符串"""
    parts = str(industry_str).split("--")
    return (parts + ["", "", ""])[:3]


class SwIndustryFetcher:
    """申万行业数据获取器"""

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or os.getenv("PYWENCAI_COOKIE", "")
        from ..api.helpers.aux_data import aux_file_path
        self.output_file = aux_file_path("个股申万行业映射")

    def fetch_all(self) -> pd.DataFrame:
        """从问财 API 获取所有 A 股的申万行业分类"""
        if not self.cookie:
            logger.error("未配置 PYWENCAI_COOKIE 环境变量")
            raise RuntimeError("未配置 pywencai cookie，请在环境变量中设置 PYWENCAI_COOKIE")

        import pywencai

        logger.info("开始从问财 API 获取申万行业数据...")

        try:
            result = pywencai.get(
                query="股票代码,股票简称,所属申万行业",
                cookie=self.cookie,
                loop=True,
                perpage=100,
                sleep=1,
                log=True,
            )
        except Exception as e:
            raise RuntimeError(
                f"问财 API 请求失败: {e}。"
                "可能原因：1) PYWENCAI_COOKIE 失效或未配置 2) 容器网络不通 iwencai.com"
            ) from e

        if result is None:
            raise RuntimeError("问财 API 返回空数据")

        if isinstance(result, pd.DataFrame):
            df = result
        elif isinstance(result, dict):
            df = None
            for key, value in result.items():
                if isinstance(value, pd.DataFrame):
                    df = value
                    break
            if df is None:
                raise RuntimeError("问财 API 返回字典但未找到 DataFrame")
        else:
            raise RuntimeError(f"问财 API 返回不支持的类型: {type(result)}")

        df = _smart_column_rename(df)

        required_columns = ['股票代码', '股票简称']
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            raise RuntimeError(f"缺少必需列: {missing}")

        df = df[df['股票代码'].notna()]
        df = df.drop_duplicates(subset=['股票代码'])
        df = df.reset_index(drop=True)

        logger.info(f"获取到 {len(df)} 条申万行业数据")

        if '申万行业' in df.columns:
            df['一级行业'], df['二级行业'], df['三级行业'] = zip(
                *df['申万行业'].apply(_parse_hierarchy)
            )

        df['股票代码'] = df['股票代码'].astype(str).str.replace(r'\.(SZ|SH)$', '', regex=True)

        from ..api.helpers.aux_data import current_quarter
        quarter = current_quarter()
        df['数据季度'] = quarter

        output_cols = ['股票代码', '股票简称', '一级行业', '二级行业', '三级行业', '数据季度']
        available = [c for c in output_cols if c in df.columns]
        df = df[available]

        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.output_file, index=False, encoding="utf-8-sig")
        logger.info(f"申万行业数据已保存到: {self.output_file}，共 {len(df)} 条")

        return df