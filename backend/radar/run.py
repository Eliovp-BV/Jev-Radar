import socket,ipaddress,uvicorn
from .config import Settings
from .api import create_app
s=Settings.load()
if s.host=='localhost':s.host='127.0.0.1'
try:ipaddress.IPv4Address(s.host)
except ValueError:raise SystemExit('RADAR_HOST must be an IPv4 bind address or localhost.') from None
for candidate in range(s.port,s.port+20):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try: probe.bind((s.host,candidate))
        except OSError: continue
        s.port=candidate;break
else: raise SystemExit('No available port in the requested 20-port range.')
print(f'Jev Radar by Eliovp listening on {s.host}:{s.port}',flush=True)
if s.host=='0.0.0.0':
    print(f'Local: http://127.0.0.1:{s.port} | Network: http://<this-machine-LAN-IP>:{s.port}',flush=True)
else:print(f'Jev Radar by Eliovp: http://{s.host}:{s.port}',flush=True)
uvicorn.run(create_app(s),host=s.host,port=s.port,access_log=False,timeout_graceful_shutdown=5)
