#!/bin/sh
# Servidor MCP do DMaker instalado, para ligar ao Claude Code: claude mcp add dmaker -- <este arquivo>
PYTHONNOUSERSITE=1 PYTHONUTF8=1 exec "@@PROGRAMA@@/python/bin/python3" -m dmaker mcp "$@"
