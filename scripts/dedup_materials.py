"""全库材料去重：同一申请人名下、内容 md5 一致、未被评估引用的副本，保留一份。

安全边界：
- 只动 (application_id, content_md5) 相同的组；跨申请人相同内容一律不碰；
- 任何评估 verified_papers.pdf_file_id 引用到的材料 id 不删；
- 文件被其他行共享路径时只删行不删文件；
- 全表备份 + 删除清单 CSV 先落盘，再执行；
- 无文件/指纹失败的行跳过。
"""
import csv, hashlib, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, '/opt/zhipu-talent/current')
from agi_talent_radar.core.db import get_session
from agi_talent_radar.core.db.orm import ScholarshipEvaluationORM, ScholarshipMaterialORM

BACKUP = Path(f"/opt/zhipu-talent/backups/materials_dedup_{__import__("datetime").date.today():%Y%m%d}")
BACKUP.mkdir(parents=True, exist_ok=True)
apply = '--apply' in sys.argv

with get_session() as s:
    rows = s.query(ScholarshipMaterialORM).all()
    # ① 指纹
    by_key = defaultdict(list)
    for m in rows:
        p = Path(m.file_path or '')
        if not p.exists():
            continue
        h = hashlib.md5()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        by_key[(m.application_id, h.hexdigest())].append(m)
    # ② 被评估引用的 id（论文 PDF 按钮）不可删
    referenced = set()
    for (pdf_ids,) in s.query(ScholarshipEvaluationORM.verified_papers).all():
        for p in pdf_ids or []:
            if isinstance(p, dict) and p.get('pdf_file_id'):
                referenced.add(int(p['pdf_file_id']))
    # ③ 规划删除：每组保留一份（优先被引用的、其次 id 最小），其余删除
    path_rows = defaultdict(list)
    for m in rows:
        path_rows[m.file_path].append(m)
    plan = []
    for (app_id, digest), group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda m: (m.id in referenced, m.id))  # 被引用优先保留
        keep, extras = group[0], group[1:]
        for m in extras:
            if m.id in referenced:
                continue  # 双保险
            plan.append((m, keep))
    n_bytes = sum(Path(m.file_path).stat().st_size for m, _ in plan
                  if not any(o.id != m.id and o.file_path == m.file_path for o in rows))
    print(f"总行数 {len(rows)} | 重复组 {sum(1 for g in by_key.values() if len(g) > 1)} | 计划删行 {len(plan)} | 释放约 {n_bytes/1e9:.2f} GB")
    by_kind = defaultdict(int)
    for m, _ in plan:
        by_kind[m.kind] += 1
    print('按类型:', dict(by_kind))
    # 抽样展示
    for m, keep in plan[:8]:
        print(f"  删 {m.id} {m.kind} {Path(m.file_path).name[:40]}  保留 {keep.id}")
    # ④ 备份 + 清单
    import subprocess
    subprocess.run(['bash', '-c',
        'set -a; source /etc/zhipu-talent.env; set +a; '
        'mysqldump talent_radar scholarship_materials | gzip > '
        f'{BACKUP}/scholarship_materials_backup.sql.gz'], check=True)
    with open(BACKUP / 'deleted_rows_manifest.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['deleted_id', 'kept_id', 'application_id', 'kind', 'filename', 'file_path', 'md5'])
        for m, keep in plan:
            w.writerow([m.id, keep.id, m.application_id, m.kind, m.filename, m.file_path, ''])
    print('备份+清单已写', BACKUP)
    if not apply:
        print('（dry-run，未执行。加 --apply 执行）')
        sys.exit(0)
    # ⑤ 执行
    ids = [m.id for m, _ in plan]
    file_paths = {}
    for m, _ in plan:
        file_paths.setdefault(m.file_path, 0)
    deleted_ids = set(ids)
    with get_session() as s:
        for mid in ids:
            m = s.get(ScholarshipMaterialORM, mid)
            if m is None:
                continue
            s.delete(m)
        s.commit()
    # ⑥ 删孤儿文件：路径无任何行引用且不等于保留行路径
    with get_session() as s:
        alive_paths = {r.file_path for r in s.query(ScholarshipMaterialORM).all()}
    freed = 0
    for m, _ in plan:
        p = Path(m.file_path)
        if m.file_path in alive_paths:
            continue
        if p.exists():
            freed += p.stat().st_size
            p.unlink()
    print(f'执行完成：删行 {len(ids)}，删文件释放 {freed/1e9:.2f} GB')
    # ⑦ 校验
    with get_session() as s:
        left = s.query(ScholarshipMaterialORM).count()
        missing = [r.id for r in s.query(ScholarshipMaterialORM).all() if not Path(r.file_path or '').exists()]
        ref_broken = referenced - {r.id for r in s.query(ScholarshipMaterialORM).all()}
    print(f'剩余行 {left} | 保留行文件缺失 {len(missing)} | 引用断链 {len(ref_broken)}')
    assert not missing and not ref_broken, '校验失败！'
