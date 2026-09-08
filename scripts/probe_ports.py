# -*- coding: utf-8 -*-
# 端口探测：python scripts/probe_ports.py
import socket

PORTS = (443, 888, 8888, 9999, 8022, 22022, 22222, 36000, 60022, 6379)
open_ports = []
for port in PORTS:
    s = socket.socket()
    s.settimeout(2)
    if s.connect_ex(("39.102.71.80", port)) == 0:
        open_ports.append(port)
    s.close()
print("open:", open_ports or "none")
