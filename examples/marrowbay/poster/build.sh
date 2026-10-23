#!/bin/sh
# Rebuild the fictional Marrowbay poster from its inputs (brand.md, brief.md, variants/, judge.md). Marrowbay
# Ferments does not exist. No image generator is used here: source/still-life.png (a flat still life drawn in HTML) stands for the image you
# would provide, and is kept as it is.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
S="$HERE/../../../scripts/studio"
cd "$HERE"
rm -f pick.json image.json image.png image.jpg piece.html piece.png check.json decision.md bans.md [1-5]-*.html
python3 "$S" brand .
python3 "$S" brief .
python3 "$S" diverge .
python3 "$S" pick . v2
cp source/still-life.png image.png
python3 "$S" image . --engine none
python3 "$S" compose .
python3 "$S" check .
python3 "$S" decide . keep "Plain and friendly; the call to action is the verb. Ship it to the market stall."
