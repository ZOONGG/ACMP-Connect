"""Prepare a Railway-mounted data directory, then permanently drop root."""
import os
from pathlib import Path


def main():
    os.umask(0o077)
    parent = Path(os.environ.get('DATABASE_PATH', '/data/acmp.sqlite3')).parent
    parent.mkdir(parents=True, exist_ok=True)
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        os.chown(parent, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    from .mcp_server import main as serve
    serve()


if __name__ == '__main__':
    main()
