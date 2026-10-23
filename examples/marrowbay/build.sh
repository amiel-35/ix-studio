#!/bin/sh
# Rebuild the fictional Marrowbay dossier from its inputs. Marrowbay Ferments does not exist: every name, address
# and value here is made up to show how a dossier is built (no real brand in this repository, R14).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
K="$HERE/../../scripts/brandkit"
B="$HERE/brand"
rm -rf "$B"
python3 "$K" init "$B" --name "Marrowbay Ferments" --lang en
for f in "$HERE"/inputs/*.json; do python3 "$K" add "$B" "$f" --no-merge; done
python3 "$K" merge "$B"
cp "$B/review.md" "$HERE/review-before-answers.md"
sh "$HERE/inputs/5-decisions.sh" "$K" "$B"
python3 "$K" validate "$B" --by "example"
