"""Module standards (requirement 1: 按文档分类确定格式结构, 分模块定义标准).

Each of the 9 Excel tabs is a *module*. All modules share the same catalog
column structure, but each defines its own *content item standard* — i.e. what
the primary item produced by that module represents (the 数据项标题 in the sheet
header) and which module-specific payload fields are meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModuleKey(str, Enum):
    NEWS = "news"
    EVENTS = "events"
    CALENDAR = "calendar"
    COMPANY = "company"
    MARKET = "market"
    MACRO = "macro"
    OPINION = "opinion"
    CHANNEL = "channel"
    PERSON = "person"


@dataclass(frozen=True)
class ModuleSpec:
    key: ModuleKey
    tab: str                # Excel sheet name
    display_name: str       # human-readable name
    item_title: str         # meaning of a content item's `title` (数据项标题)
    payload_fields: tuple[str, ...]  # module-specific normalized fields
    note: str


# Order matches the workbook tabs 1..9.
MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        ModuleKey.NEWS, "1_新闻", "新闻",
        item_title="新闻标题",
        payload_fields=("region", "topic", "lang"),
        note="News-only feeds (RSS / Google News / NewsAPI).",
    ),
    ModuleSpec(
        ModuleKey.EVENTS, "2_全球事件", "全球事件",
        item_title="事件标题",
        payload_fields=("event_type", "actors", "location", "cameo_code"),
        note="Event-discovery sources (GDELT / ACLED / Event Registry).",
    ),
    ModuleSpec(
        ModuleKey.CALENDAR, "3_日历", "日历",
        item_title="日期/事项",
        payload_fields=("event_date", "calendar_type", "symbol"),
        note="Earnings / IR / regulatory / economic / central-bank calendars.",
    ),
    ModuleSpec(
        ModuleKey.COMPANY, "4_公司", "公司",
        item_title="公司名称",
        payload_fields=("symbol", "exchange", "data_type"),
        note="Company profile / financials / valuation / filings / analyst / sentiment.",
    ),
    ModuleSpec(
        ModuleKey.MARKET, "5_市场", "市场",
        item_title="可交易对象",
        payload_fields=("instrument", "asset_class", "venue"),
        note="Primary/secondary markets, bonds, commodities, forex, crypto, prediction.",
    ),
    ModuleSpec(
        ModuleKey.MACRO, "6_宏观", "宏观",
        item_title="区域/国家指标",
        payload_fields=("country", "indicator", "period"),
        note="Official macro releases (GDP / CPI / PMI / employment ...).",
    ),
    ModuleSpec(
        ModuleKey.OPINION, "7_关键舆论平台", "关键舆论平台",
        item_title="平台条目",
        payload_fields=("platform", "topic", "rank"),
        note="Opinion platforms organized by L1=platform / L2=topic.",
    ),
    ModuleSpec(
        ModuleKey.CHANNEL, "8_关键频道", "关键频道",
        item_title="频道条目",
        payload_fields=("medium", "topic", "lang"),
        note="Podcasts / blogs / newsletters / YouTube, by L1=medium.",
    ),
    ModuleSpec(
        ModuleKey.PERSON, "9_关键人物", "关键人物",
        item_title="人物动态",
        payload_fields=("person", "platform", "bio"),
        note="Key people (X / Weibo / personal sites). Sheet has an extra Bio column.",
    ),
)

_BY_TAB = {m.tab: m for m in MODULES}
_BY_KEY = {m.key: m for m in MODULES}


def module_for_tab(tab: str) -> ModuleSpec | None:
    return _BY_TAB.get(tab)


def module_for_key(key: str) -> ModuleSpec | None:
    try:
        return _BY_KEY[ModuleKey(key)]
    except ValueError:
        return None
