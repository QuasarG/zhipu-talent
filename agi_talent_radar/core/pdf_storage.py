# 候选人原始简历 PDF 文件存储
# 二进制不进数据库，落盘到 data/resume_pdfs/<candidate_id>.pdf
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "data" / "resume_pdfs"


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def save_resume_pdf(candidate_id: str, pdf_bytes: bytes) -> Path | None:
    """落盘候选人原始 PDF；空 id/空字节返回 None。"""
    if not candidate_id or not pdf_bytes:
        return None
    _ensure_root()
    path = _ROOT / f"{candidate_id}.pdf"
    path.write_bytes(pdf_bytes)
    return path


def get_resume_pdf_path(candidate_id: str) -> Path | None:
    if not candidate_id:
        return None
    path = _ROOT / f"{candidate_id}.pdf"
    return path if path.exists() else None


# 允许环境变量覆盖默认根目录（部署/测试用）
_env_root = os.getenv("RESUME_PDF_DIR", "").strip()
if _env_root:
    _ROOT = Path(_env_root)
