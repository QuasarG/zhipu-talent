from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchDirection(BaseModel):
    """一条研究方向，带证据来源。"""
    name: str = ""
    evidence: str = ""          # 从哪个来源/检索结果抽出的
    source_urls: list[str] = Field(default_factory=list)


class RepresentativeWork(BaseModel):
    """代表成果，可被学术链核查对齐。"""
    title: str = ""
    venue: str = ""
    year: str = ""
    role: str = ""              # 一作 / 通讯 / 其他


class ScholarProfile(BaseModel):
    """嘉宾学术画像：研究方向 + 代表成果 + 基本指标。"""
    name: str = ""
    org: str = ""
    research_directions: list[ResearchDirection] = Field(default_factory=list)
    representative_works: list[RepresentativeWork] = Field(default_factory=list)
    affiliation: str = ""       # 机构（用于消歧）
    citation_count: int = 0
    publication_count: int = 0
    hindex: int = 0
    data_source: str = ""       # aminer / web_search / academic_chain
    warnings: list[str] = Field(default_factory=list)


class GuestProfile(BaseModel):
    """嘉宾画像总报告：学术画像 + 学术核查 + 舆情分级三段汇总。"""
    name: str
    org: str = ""
    direction: str = ""
    scholar_profile: ScholarProfile = Field(default_factory=ScholarProfile)
    academic_summary: dict = Field(default_factory=dict)   # verified/mismatch/unverifiable 计数 + 关键差异
    reputation_level: str = "green"                        # red / yellow / green
    reputation_rationale: str = ""
    reputation_events: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
