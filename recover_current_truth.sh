#!/usr/bin/env bash
# recover_current_truth.sh
# Restore docs/CURRENT_TRUTH.md from git history after a clobber.
# Working tree only. No commit, no push, no other files touched.
set -euo pipefail

FILE="docs/CURRENT_TRUTH.md"
CLOBBER_PREFIX='grep -E'
MIN_BYTES=10000   # full file is ~13.5k; anything under this is suspect
MAX_BYTES=20000   # sanity ceiling

# 1. Recent history for this file
echo "== git log --oneline -5 -- $FILE"
git log --oneline -5 -- "$FILE" || true

# 2. Inspect HEAD's copy
echo
echo "== HEAD:$FILE (first 40 lines)"
if git cat-file -e "HEAD:$FILE" 2>/dev/null; then
  git show "HEAD:$FILE" | head -40
  head_size=$(git show "HEAD:$FILE" | wc -c)
  head_first=$(git show "HEAD:$FILE" | head -1)
  echo
  echo "HEAD copy: $head_size bytes; first line: $head_first"
else
  head_size=0
  head_first=""
  echo "(file absent at HEAD)"
fi

restore_from() {
  local hash="$1"
  git checkout "$hash" -- "$FILE"
  echo
  echo "Restored from: $hash"
  echo "Final size: $(wc -c < "$FILE") bytes"
  echo "== head -12 $FILE"
  head -12 "$FILE"
}

# 3. HEAD looks full -> restore from HEAD
if [ "$head_size" -ge "$MIN_BYTES" ] && [ "$head_size" -le "$MAX_BYTES" ] \
   && [[ "$head_first" != "$CLOBBER_PREFIX"* ]]; then
  restore_from HEAD
  exit 0
fi

# 5. HEAD is clobbered (or missing) -> walk back through history
echo
echo "== walking back through history"
found=""
for hash in $(git log --format='%h' -10 -- "$FILE" || true); do
  if ! git cat-file -e "$hash:$FILE" 2>/dev/null; then
    echo "$hash: file absent at this commit, skipping"
    continue
  fi
  size=$(git show "$hash:$FILE" | wc -c)
  first=$(git show "$hash:$FILE" | head -1)
  echo "$hash: $size bytes | first line: $first"
  if [ "$size" -ge "$MIN_BYTES" ] && [ "$size" -le "$MAX_BYTES" ] \
     && [[ "$first" != "$CLOBBER_PREFIX"* ]]; then
    found="$hash"
    break
  fi
done

if [ -z "$found" ]; then
  echo "ERROR: no full version of $FILE found in the last 10 commits." >&2
  exit 1
fi

restore_from "$found"
