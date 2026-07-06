"""Schemas for AI research brief outputs."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class EventCard(BaseModel):
    symbol: str
    market: Literal["us"]
    source_type: Literal["announcement", "news", "price_action", "financial"]
    event_type: Literal[
        "业绩财报",
        "指引调整",
        "回购增持",
        "内部人交易",
        "并购重组",
        "重大合同",
        "监管调查",
        "诉讼仲裁",
        "股权融资/增发",
        "分红拆股",
        "人事变动",
        "异动提示",
        "其他",
    ]
    severity: int = Field(ge=1, le=5)
    direction: Literal["利多", "利空", "中性", "不确定"]
    one_line: str = Field(max_length=60)
    key_numbers: list[str]
    rationale: str = Field(max_length=200)
    source_url: str = Field(min_length=1)
    input_truncated: bool = False
    prompt_version: str

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an http(s) URL")
        return value
