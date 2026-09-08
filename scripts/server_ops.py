# -*- coding: utf-8 -*-
# 服务器运维辅助：python scripts/server_ops.py "cmd" [timeout]
import sys
import paramiko

HOST, USER, PASSWORD, PORT = "39.102.71.80", "root", "AITime1234", 29652


def run(cmd: str, timeout: int = 60) -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
    try:
        _, out, err = client.exec_command(cmd, timeout=timeout)
        stdout = out.read().decode("utf-8", "replace")
        stderr = err.read().decode("utf-8", "replace")
        code = out.channel.recv_exit_status()
        if stdout:
            print(stdout)
        if stderr:
            print("[stderr]", stderr)
        print(f"[exit {code}]")
    finally:
        client.close()


if __name__ == "__main__":
    run(sys.argv[1], timeout=int(sys.argv[2]) if len(sys.argv) > 2 else 60)
