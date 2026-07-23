from __future__ import annotations

from pydantic import BaseModel, Field


class PersonIdentity(BaseModel):
    name: str
    org: str = ""
    direction: str = ""
    works: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    query: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    media: str = ""
    publish_date: str = ""


class ReputationEvent(BaseModel):
    category: str           # 学术不端 / 抄袭争议 / 公开冲突 / 法律纠纷 / 其他负面 / 误报
    identity_match: str     # confirmed / probable / rejected
    summary: str = ""
    status: str = ""        # 进行中 / 已澄清 / 已有结论 等
    source_urls: list[str] = Field(default_factory=list)
    publish_date: str = ""


class ReputationReport(BaseModel):
    level: str              # red / yellow / green
    events: list[ReputationEvent] = Field(default_factory=list)
    hits: list[SearchHit] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
