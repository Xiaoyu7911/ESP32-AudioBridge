#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Create a Python 3.12 venv and install host/requirements.lock.txt first. See docs/BUILD_AND_RECOVERY.md.' >&2
  exit 2
fi
exec .venv/bin/python -m host.sender "$@"
