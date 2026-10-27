# register-graphviz-plugins.sh
# pixi activation script, macOS only. Writes Graphviz's plugin registry
# (lib/graphviz/config8) if it is missing. See "Graphviz on macOS" in AGENTS.md.
#
# Sourced, not executed: no `exit`, no output. The check is a file test, so
# every activation after the first costs nothing.

if [ -x "$CONDA_PREFIX/bin/dot" ] && ! ls "$CONDA_PREFIX"/lib/graphviz/config* >/dev/null 2>&1; then
    "$CONDA_PREFIX/bin/dot" -c >/dev/null 2>&1 || true
fi
