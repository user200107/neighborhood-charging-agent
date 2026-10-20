"""创建租户管理员（生产环境首次部署使用）。

用法：
    python scripts/create_admin.py --username admin --password 'StrongPass!2026'
    python scripts/create_admin.py --username ops --role operator --password '...' \
        --tenant-code NEIGHBOR --community YQ --community HP

如果租户不存在会自动创建；管理员默认授权该租户下全部社区。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Community, Tenant, User  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="创建邻里充电管理员/运营账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--role", default="admin", choices=["admin", "operator", "technician", "finance", "resident"])
    parser.add_argument("--tenant-code", default="NEIGHBOR")
    parser.add_argument("--tenant-name", default="邻里充电")
    parser.add_argument("--community", action="append", default=[], help="社区 code，可重复")
    args = parser.parse_args()

    password = args.password or getpass.getpass("密码（至少 8 位）: ")
    if len(password) < 8:
        raise SystemExit("密码至少 8 位")

    init_db()
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.code == args.tenant_code).first()
        if tenant is None:
            tenant = Tenant(code=args.tenant_code, name=args.tenant_name, status="active")
            db.add(tenant)
            db.flush()
            print(f"已创建租户 {tenant.code} #{tenant.id}")

        username = args.username.strip().lower()
        existing = (
            db.query(User)
            .filter(User.tenant_id == tenant.id, User.username == username)
            .first()
        )
        if existing:
            existing.password_hash = hash_password(password)
            existing.role = args.role
            existing.status = "active"
            user = existing
            print(f"已重置用户 {username} 的密码与角色")
        else:
            user = User(
                tenant_id=tenant.id,
                username=username,
                password_hash=hash_password(password),
                display_name=args.name or username,
                role=args.role,
                status="active",
            )
            db.add(user)
            db.flush()
            print(f"已创建用户 {username} #{user.id}")

        communities = (
            db.query(Community)
            .filter(
                Community.tenant_id == tenant.id,
                Community.code.in_(args.community),
            )
            .all()
            if args.community
            else db.query(Community).filter(Community.tenant_id == tenant.id).all()
        )
        user.communities = communities
        db.commit()
        print(f"完成：{username} / {args.role} / {len(communities)} 个社区")


if __name__ == "__main__":
    main()
