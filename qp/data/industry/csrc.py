"""CSRC industry classification (via baostock) — 全市场行业映射.

baostock 提供**证监会行业分类**(84 个门类/大类)，覆盖率约 94%，
远好于按股票名称关键词的分类(约 39% 非 Other)。

与 ``qp/data/industry/classifier.py`` 的区别:
    - classifier: 多源(缓存→baostock→akshare→前缀)，输出 SW 风格的 sector/subsector
    - 本模块: 单一 baostock 源，输出证监会行业，专为需要"样本充足"的聚合场景设计

用法:
    mapper = CsrcIndustryMapper()
    mapper.get("600519")          # "酒、饮料和精制茶制造业"
    mapper.get_code("600519")     # "C15"

更新映射(网络操作，几秒):
    n = refresh_csrc_mapping()    # 落盘 data/stock_industry_csrc.json
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from qp.shared.json_io import json_save
from qp.shared.paths import STOCK_INDUSTRY_CSRC


@dataclass
class CsrcIndustry:
    """证监会行业分类的一行。"""

    code: str  # 门类/大类代码，如 "C39"
    name: str  # 行业名，如 "计算机、通信和其他电子设备制造业"
    raw: str  # 原始字符串，如 "C39计算机、通信和其他电子设备制造业"
    update_date: str  # baostock 的 updateDate


def _split(raw: str) -> tuple[str, str]:
    """把 "C39计算机、通信…" 拆成 ("C39", "计算机、通信…")。"""
    if len(raw) > 3 and raw[0].isalpha() and raw[1:3].isdigit():
        return raw[:3], raw[3:]
    return "", raw


class CsrcIndustryMapper:
    """读 ``data/stock_industry_csrc.json``(code → 证监会行业)。

    Args:
        path: 映射文件路径(默认 data/stock_industry_csrc.json)。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else Path(STOCK_INDUSTRY_CSRC)
        self._map: dict[str, CsrcIndustry] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.warning("证监会行业映射不存在: {} — 先运行 qp industry refresh", self._path)
            return
        try:
            data = _json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError) as e:
            logger.warning("证监会行业映射读取失败: {}", e)
            return
        for code, info in data.items():
            self._map[str(code)] = CsrcIndustry(
                code=info.get("code", ""),
                name=info.get("name", ""),
                raw=info.get("raw", ""),
                update_date=info.get("update_date", ""),
            )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """已加载的股票数。"""
        return len(self._map)

    def get(self, symbol: str) -> str:
        """行业名(未分类 → "Other")。"""
        clean = symbol.split(".")[0] if "." in symbol else symbol
        info = self._map.get(clean)
        return info.name if info and info.name else "Other"

    def get_code(self, symbol: str) -> str:
        """行业代码(未分类 → "")。"""
        clean = symbol.split(".")[0] if "." in symbol else symbol
        info = self._map.get(clean)
        return info.code if info else ""

    def symbols_in(self, name: str) -> list[str]:
        """某行业下的所有股票代码。"""
        return [s for s, i in self._map.items() if i.name == name]


def refresh_csrc_mapping(dest: str | Path | None = None) -> int:
    """从 baostock 拉全量证监会行业分类并落盘。

    Returns:
        写入的股票条数(0 表示失败)。
    """
    try:
        import baostock as bs
    except ImportError:
        logger.error("baostock 未安装 — 运行: uv pip install baostock")
        return 0

    lg = bs.login()
    if lg.error_code != "0":
        logger.error("baostock 登录失败: {} {}", lg.error_code, lg.error_msg)
        return 0

    try:
        rs = bs.query_stock_industry()
        if rs.error_code != "0":
            logger.error("baostock 行业查询失败: {} {}", rs.error_code, rs.error_msg)
            return 0

        rows: list[list[str]] = []
        while rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()

    out: dict[str, dict[str, str]] = {}
    for row in rows:
        # 字段: updateDate, code, code_name, industry, industryClassification
        if len(row) < 5:
            continue
        update_date, full_code, _name, industry, _cls = row[0], row[1], row[2], row[3], row[4]
        clean = full_code.split(".")[-1]
        # 只保留有行业分类的(退市/未分类的行业为空)
        if not industry:
            continue
        code, name = _split(industry)
        out[clean] = {
            "code": code,
            "name": name,
            "raw": industry,
            "update_date": update_date,
        }

    dest_path = Path(dest) if dest is not None else Path(STOCK_INDUSTRY_CSRC)
    json_save(dest_path, out)
    logger.info("证监会行业映射已落盘: {} ({} 只股票)", dest_path, len(out))
    return len(out)
