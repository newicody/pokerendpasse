#!/usr/bin/env python3
"""
PokerEndPasse — Script de lancement
Usage: python run.py [--host 0.0.0.0] [--port 8000] [--reload]
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="PokerEndPasse Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--workers", type=int, default=1, help="Workers (default: 1, must be 1 for WS)")
    args = parser.parse_args()

    print(f"""
    ╔══════════════════════════════════════════╗
    ║   ♠ PokerEndPasse — Freeroll Server ♥   ║
    ║   http://{args.host}:{args.port}                ║
    ╚══════════════════════════════════════════╝
    """)

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
