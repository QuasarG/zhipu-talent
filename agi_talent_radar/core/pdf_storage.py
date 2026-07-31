# 候选人原始简历文件存储（PDF/图片/MD/TXT 等按后缀落盘）
# 二进制不进数据库，落盘到 data/resume_pdfs/<candidate_id><suffix>
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "data" / "resume_pdfs"


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def save_resume_original(candidate_id: str, file_bytes: bytes, suffix: str = ".pdf") -> Path | None:
    """落盘候选人原始简历文件；空 id/空字节返回 None。后缀决定文件类型。"""
    if not candidate_id or not file_bytes:
        return None
    _ensure_root()
    suffix = suffix or ".pdf"
    if not suffix.startswith("."):
        suffix = "." + suffix
    path = _ROOT / f"{candidate_id}{suffix.lower()}"
    path.write_bytes(file_bytes)
    return path


# 兼容旧调用
def save_resume_pdf(candidate_id: str, pdf_bytes: bytes) -> Path | None:
    return save_resume_original(candidate_id, pdf_bytes, ".pdf")


def get_resume_original_path(candidate_id: str, suffix: str = "") -> Path | None:
    """查找候选人原始文件。指定 suffix 直接定位；不指定则按常见后缀查找。"""
    if not candidate_id:
        return None
    if suffix:
        s = suffix if suffix.startswith(".") else "." + suffix
        path = _ROOT / f"{candidate_id}{s.lower()}"
        return path if path.exists() else None
    for s in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".md", ".txt", ".jsonl"):
        path = _ROOT / f"{candidate_id}{s}"
        if path.exists():
            return path
    return None


get_resume_pdf_path = get_resume_original_path


# 允许环境变量覆盖默认根目录（部署/测试用）
_env_root = os.getenv("RESUME_PDF_DIR", "").strip()
if _env_root:
    _ROOT = Path(_env_root)
