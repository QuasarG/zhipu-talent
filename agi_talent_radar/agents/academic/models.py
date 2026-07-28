from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


PUBLICATION_STATUSES = ("草稿", "已投稿", "在审", "已接收", "已发表", "不明")


class PaperClaim(BaseModel):
    title: str
    venue: str = ""
    year: str = ""
    claimed_role: str = "不明"      # 一作 / 共同一作 / 通讯 / 其他作者 / 不明
    claimed_status: str = "不明"

    @field_validator("claimed_status", mode="before")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if any(token in text for token in ("草稿", "draft")):
            return "草稿"
        if any(token in text for token in ("在审", "审稿", "under review", "reviewing")):
            return "在审"
        if any(token in text for token in ("投稿", "submitted", "submission", "在投")):
            return "已投稿"
        if any(token in text for token in ("已接收", "已录用", "录用", "accepted", "forthcoming", "to appear")):
            return "已接收"
        if any(token in text for token in ("已发表", "正式发表", "published", "publication")):
            return "已发表"
        return "不明"


class ClaimAlignment(BaseModel):
    claim: PaperClaim
    verdict: str                    # verified / mismatch / unverifiable
    verified_status: str = "不明"
    matched_title: str = ""
    discrepancies: list[str] = Field(default_factory=list)
    cited_by_count: int = 0
    is_retracted: bool = False
    openalex_url: str = ""
    note: str = ""

    @field_validator("verified_status", mode="before")
    @classmethod
    def normalize_verified_status(cls, value: str) -> str:
        return "已发表" if PaperClaim.normalize_status(value) == "已发表" else "不明"


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
