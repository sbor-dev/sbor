#!/bin/bash

set -e

dockerd &

echo "[start.sh] run docker service"

ROLE="${AGENT_ROLE:-}"

if [ -n "$ROLE" ]; then
    SRC_BASE="/root/.pi/agent"
    ROLE_DIR="$SRC_BASE/promts/$ROLE"

    echo "[start.sh] AGENT_ROLE=$ROLE -> copying $ROLE_DIR/* into $SRC_BASE"

    if [ -d "$ROLE_DIR" ]; then
        for item in "$ROLE_DIR"/* "$ROLE_DIR"/.[!.]* "$ROLE_DIR"/..?*; do
            [ -e "$item" ] || [ -L "$item" ] || continue

            name=$(basename "$item")
            target="$SRC_BASE/$name"

            rm -rf "$target"
            ln -s "$item" "$target"
            echo "[start.sh]   $item -> $target"
        done
    else
        echo "[start.sh] role dir $ROLE_DIR not found — nothing to copy."
    fi
else
    echo "[start.sh] AGENT_ROLE is not set — skip copying role files."
fi

AGENT_CMD="${AGENT_CMD:-pi}"

echo "[start.sh] starting agent: $AGENT_CMD"

if [ "$#" -gt 0 ]; then
    exec "$@"
else
    exec "$AGENT_CMD"
fi
