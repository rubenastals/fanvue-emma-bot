"""Loopback-only launcher with lab-specific credentials and persistence."""
import argparse
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Laboratorio local de conversación")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.lab", override=False)
    uvicorn.run("lab.app:create_app", factory=True, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
