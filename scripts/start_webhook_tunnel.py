"""
Start receive-only webhook server + Cloudflare Tunnel.

Prints the public HTTPS URL to paste into Fanvue Builder → Events.
"""
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    listen = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "webhook_listen.py")],
        cwd=ROOT,
    )
    time.sleep(2)

    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    public_url = None
    print("Waiting for Cloudflare Tunnel URL...")
    deadline = time.time() + 45
    while time.time() < deadline:
        line = tunnel.stdout.readline()
        if not line:
            if tunnel.poll() is not None:
                break
            continue
        print(line.rstrip())
        m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
        if m:
            public_url = m.group(1)
            break

    if not public_url:
        print("ERROR: could not get tunnel URL")
        listen.terminate()
        tunnel.terminate()
        sys.exit(1)

    webhook_url = f"{public_url}/webhook/fanvue"
    print("\n" + "=" * 60)
    print("TUNNEL LISTO")
    print(f"  Health:  {public_url}/health")
    print(f"  Webhook: {webhook_url}")
    print("=" * 60)
    print(
        """
En Fanvue Builder → tu app → Events:
  1. Add Webhook
  2. Endpoint URL = la URL Webhook de arriba
  3. Eventos: creator.message.received (y opcional creator.payment.succeeded)
  4. Save
  5. En el menú … del webhook → Test (envía payload de prueba)

Copia también el Signing secret → FANVUE_WEBHOOK_SECRET en .env
(puedes probar el Test primero sin secret; luego ponlo y reinicia).

Ctrl+C para parar.
"""
    )

    try:
        while True:
            line = tunnel.stdout.readline()
            if line:
                print(line.rstrip())
            if listen.poll() is not None or tunnel.poll() is not None:
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        listen.terminate()
        tunnel.terminate()


if __name__ == "__main__":
    main()
