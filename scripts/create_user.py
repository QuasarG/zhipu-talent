"""创建或更新平台账号。

用法：
    python scripts/create_user.py <username> --display-name 张三 --role reviewer
    python scripts/create_user.py <username> --role admin --reset            # 更新已有账号

- 角色只有 admin（全功能，默认）与 reviewer（仅奖学金 + 设置）。
- --password 缺省时自动生成随机密码并只打印一次。
- 用户名已存在时默认报错；--reset 改为更新 display_name / role / 密码。
"""
import argparse
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash

from agi_talent_radar.core.database import get_session, init_db
from agi_talent_radar.core.db.orm import UserORM

_ROLES = ("admin", "reviewer")


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="登录用户名（姓名全拼小写）")
    parser.add_argument("--display-name", default="", help="显示名（如：张三）")
    parser.add_argument("--role", choices=_ROLES, default="admin", help="角色：admin=全功能，reviewer=仅奖学金+设置")
    parser.add_argument("--password", default="", help="登录密码；缺省时自动生成并打印一次")
    parser.add_argument("--reset", action="store_true", help="用户名已存在时更新而不是报错")
    args = parser.parse_args()

    username = args.username.strip().lower()
    if not username:
        print("错误：用户名不能为空")
        return 1
    password = args.password or generate_password()

    # 先跑迁移（老库补 users.role 列）再建号
    init_db()

    with get_session() as session:
        existing = session.query(UserORM).filter_by(username=username).first()
        if existing is not None:
            if not args.reset:
                print(f"错误：用户 {username} 已存在；如需更新请加 --reset")
                return 1
            existing.display_name = args.display_name or existing.display_name
            existing.role = args.role
            existing.password_hash = generate_password_hash(password)
            action = "已更新"
        else:
            session.add(
                UserORM(
                    username=username,
                    display_name=args.display_name,
                    role=args.role,
                    password_hash=generate_password_hash(password),
                    is_active=True,
                )
            )
            action = "已创建"
        session.commit()

    print(f"账号 {username} {action}：role={args.role}")
    print(f"初始密码：{password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
