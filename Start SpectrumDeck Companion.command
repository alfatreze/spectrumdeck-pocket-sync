#!/bin/zsh
cd -- "$(dirname -- "$0")"
exec /usr/bin/env python3 tools/desktop_companion.py
