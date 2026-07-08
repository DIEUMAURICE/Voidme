#!/bin/bash

# Ensure we are in the root directory
cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python -m core.agent
