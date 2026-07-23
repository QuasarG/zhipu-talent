from __future__ import annotations

from pydantic import BaseModel, Field


class PaperClaim(BaseModel):
    title: str
    venue: str = ""
    year: str = ""
    claimed_role: str = "不明"      # 一作 / 共同一作 / 通讯 / 其他作者 / 不明
    claimed_status: str = "不明"    # 已发表 / 已接收 / 在投 / 不明


class ClaimAlignment(BaseModel):
    claim: PaperClaim
    verdict: str                    # verified / mismatch / unverifiable
    matched_title: str = ""
    discrepancies: list[str] = Field(default_factory=list)
    cited_by_count: int = 0
    is_retracted: bool = False
    openalex_url: str = ""
    note: str = ""


class AcademicReport(BaseModel):
    alignments: list[ClaimAlignment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(1 for item in self.alignments if item.verdict == "verified")

    @property
    def mismatch_count(self) -> int:
        return sum(1 for item in self.alignments if item.verdict == "mismatch")

    @property
    def unverifiable_count(self) -> int:
        return sum(1 for item in self.alignments if item.verdict == "unverifiable")
