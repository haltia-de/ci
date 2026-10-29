#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -B -m unittest discover -s tests -v
