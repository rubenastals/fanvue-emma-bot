"""
Start the purchase webhook server + Cloudflare tunnel.
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
except Exception:
    pass


def _cloudflared_path() -> str:
    import shutil

    found = shutil.which("cloudflared")
    if found:
        return found
    for c in (
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ):
        if os.path.exists(c):
            return c
    return "cloudflared"


def main():
    listen = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "purchase_webhook.py")],
        cwd=ROOT,
    )
    time.sleep(2)

    tunnel = subprocess.Popen(
        [_cloudflared_path(), "tunnel", "--url", "http://127.0.0.1:8000"],
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
        m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
        if m:
            public_url = m.group(1)
            break

    if not public_url:
        print("ERROR: no tunnel URL")
        listen.terminate()
        tunnel.terminate()
        sys.exit(1)

    webhook_url = f"{public_url}/webhook/fanvue/purchase"
    print("\n" + "=" * 60)
    print("PURCHASE WEBHOOK READY")
    print(f"  Health:  {public_url}/health")
    print(f"  Webhook: {webhook_url}")
    print("=" * 60)
    print(
        """
Fanvue Builder → your app → Events:
  1. Add Webhook
  2. Endpoint URL = the Webhook URL above
  3. Event: creator.payment.succeeded  (Purchase / Tip)
  4. Save → then use the ... menu → Test
  5. Copy the Signing secret → put FANVUE_WEBHOOK_SECRET in .env and restart

Ctrl+C to stop.
"""
    )

    try:
        while listen.poll() is None and tunnel.poll() is None:
            line = tunnel.stdout.readline()
            if line and ("err" in line.lower() or "fail" in line.lower()):
                print(line.rstrip())
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        listen.terminate()
        tunnel.terminate()


if __name__ == "__main__":
    main()
