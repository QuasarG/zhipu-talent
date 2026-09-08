# -*- coding: utf-8 -*-
# 上传清理脚本到服务器并执行（python scripts/deploy_cleanup.py [dry|execute]）
import sys

import paramiko

HOST, USER, PASSWORD, PORT = "39.102.71.80", "root", "AITime1234", 29652
MODE = sys.argv[1] if len(sys.argv) > 1 else "dry"
LOCAL = "scripts/cleanup_evaluations.py"
REMOTE = "/opt/zhipu-talent/current/scripts/cleanup_evaluations.py"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
try:
    sftp = client.open_sftp()
    sftp.put(LOCAL, REMOTE)
    sftp.close()
    print("uploaded ->", REMOTE)

    cmd = (
        "set -a; . /etc/zhipu-talent.env; set +a; "
        'export DATABASE_URL="mysql+pymysql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"; '
        "cd /opt/zhipu-talent/current && /opt/zhipu-talent/venv/bin/python scripts/cleanup_evaluations.py"
        + (" --execute" if MODE == "execute" else "")
    )
    _, out, err = client.exec_command(cmd, timeout=600)
    print(out.read().decode("utf-8", "replace"))
    stderr = err.read().decode("utf-8", "replace")
    if stderr:
        print("[stderr]", stderr)
    print("[exit]", out.channel.recv_exit_status())
finally:
    client.close()
