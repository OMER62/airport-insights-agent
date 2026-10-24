"""Install dependencies and start the chat: python run_app.py."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parent
    environment = {**os.environ, "PYTHONPATH": str(project / "app")}
    commands = [
        [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt"],
        [sys.executable, "-m", "chainlit", "run", "app/ui/app.py", "-w", "--host", "127.0.0.1"],
    ]
    try:
        for command in commands:
            subprocess.run(command, cwd=project, env=environment, check=True)
    except subprocess.CalledProcessError as error:
        return error.returncode
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
