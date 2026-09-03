"""材料包工作区工具：文件清单与路径安全（预览端点/简历定位共用）。

文字提取与视觉转译已不属于导入链路：预览直接出原件，
评估时的转译由评估 agent 的工具调用完成。
"""
from __future__ import annotations

import os


class BundleContext:
    """材料包工作区访问上下文：路径收敛（zip-slip 防护）。"""

    def __init__(self, bundle_id: str) -> None:
        from agi_talent_radar.talent_bundle.ingest import workspace_root

        self.bundle_id = bundle_id
        self.ws = workspace_root(bundle_id)

    def resolve(self, rel: str) -> str | None:
        """工作区内相对路径 → 绝对路径；越界/不存在返回 None。"""
        clean = (rel or "").replace("\\", "/").lstrip("/")
        parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
        if not parts:
            return None
        target = os.path.join(self.ws, *parts)
        if os.path.commonpath([os.path.abspath(target), os.path.abspath(self.ws)]) != os.path.abspath(self.ws):
            return None
        return target


def walk_files(ctx: BundleContext) -> list[str]:
    """工作区文件清单（相对路径，排序截断）。"""
    out: list[str] = []
    for root, _dirs, files in os.walk(ctx.ws):
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), ctx.ws).replace(os.sep, "/"))
    return sorted(out)[:500]
