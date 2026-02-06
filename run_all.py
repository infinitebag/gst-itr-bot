# run_all.py
import asyncio
import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


async def run_process(name: str, cmd: list):
    """
    Runs a subprocess and streams logs to console.
    """
    print(f"▶ Starting {name}: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _pipe_reader(stream, prefix):
        while True:
            line = await stream.readline()
            if not line:
                break
            print(f"[{prefix}] {line.decode().rstrip()}")

    # concurrently stream logs
    await asyncio.gather(
        _pipe_reader(process.stdout, name),
        _pipe_reader(process.stderr, name),
    )


async def main():
    # ---------------------------
    # 1️⃣ Start Redis
    # ---------------------------
    redis_cmd = ["redis-server"]

    # ---------------------------
    # 2️⃣ Start ARQ Worker
    #    Module path only — do NOT add `.WorkerSettings`
    # ---------------------------
    arq_cmd = [
        sys.executable,
        "-m",
        "arq",
        "app.infrastructure.queue.arq_settings.WorkerSettings",
    ]

    # ---------------------------
    # 3️⃣ Start FastAPI/Uvicorn app
    # ---------------------------
    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8000",
    ]

    # Run all three tasks concurrently
    await asyncio.gather(
        run_process("REDIS", redis_cmd),
        run_process("ARQ", arq_cmd),
        run_process("APP", uvicorn_cmd),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")