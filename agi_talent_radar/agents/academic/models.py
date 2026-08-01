from __future__ import annotations

from typing import Literal

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


CheckStatus = Literal["match", "mismatch", "pending"]


class VerificationChecks(BaseModel):
    title: CheckStatus = "pending"
    author_identity: CheckStatus = "pending"
    author_position: CheckStatus = "pending"
    publication_status: CheckStatus = "pending"


class ExternalPaperRecord(BaseModel):
    source: str = ""
    source_url: str = ""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    year: str = ""
    publication_status: str = "不明"
    cited_by_count: int = 0
    is_retracted: bool = False


class ClaimAlignment(BaseModel):
    claim: PaperClaim
    verdict: str                    # verified / mismatch / unverifiable
    verified_status: str = "不明"
    matched_title: str = ""
    discrepancies: list[str] = Field(default_factory=list)
    cited_by_count: int = 0
    is_retracted: bool = False
    openalex_url: str = ""
    source_url: str = ""
    # 候选人在外部作者列表中的实际位次（1-based，0=未找到/未匹配）
    candidate_author_position: int = 0
    # 匹配到的那个外部作者名（原样引用，便于复核）
    candidate_author_name: str = ""
    # 论文是否标注了共同一作（† / equal contribution / co-first），放宽位次约束
    is_co_first: bool = False
    external_record: ExternalPaperRecord = Field(default_factory=ExternalPaperRecord)
    checks: VerificationChecks = Field(default_factory=VerificationChecks)
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
