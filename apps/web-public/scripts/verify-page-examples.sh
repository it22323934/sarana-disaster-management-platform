#!/usr/bin/env bash
#
# The curl snippets on /verify actually work.
#
#   bash apps/web-public/scripts/verify-page-examples.sh
#
# Build file 21's fifth Definition-of-Done command, and the one with the clearest failure
# mode if it is skipped. `/verify` is the page that makes SARANA's central claim checkable,
# and it makes it by telling a reader to run two commands. A snippet that has drifted from
# the real endpoint does not produce a confused reader — it produces a reader who concludes
# the transparency was theatre, and they are not wrong to.
#
# **The commands are extracted from the rendered page, not typed here.** The script fetches
# /en/verify, pulls out every `<code data-verify-command>`, and runs them. So this cannot
# pass while the page shows something different: there is one copy of each command and it
# is the one a reader sees.
#
# Two things it deliberately does not do:
#
#   It does not run the `sarana-verify` invocation. That command needs a booted ledger-svc
#   with a seeded chain; asserting it here would make the gate depend on the whole stack and
#   turn a five-second check into one nobody runs. What it asserts instead is that the
#   command's URLs resolve, which is the part that drifts. The verifier itself is tested in
#   `tests/ledger/test_public_feed.py` against the real chain.
#
#   It does not check the JSON shape. `curl -s` succeeding against the documented URL is
#   the claim on the page; what the payload contains is asserted by the Python suite that
#   owns those endpoints.

set -euo pipefail

BASE_URL="${SARANA_VERIFY_BASE_URL:-http://127.0.0.1:3101}"
PAGE="${BASE_URL}/en/verify"

say() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

say "Reading the verify page: ${PAGE}"

if ! html="$(curl -sS --max-time 20 "${PAGE}")"; then
  fail "could not fetch ${PAGE}.
Start the app first, for example:
  SARANA_LEDGER_SVC_URL=http://127.0.0.1:8099 pnpm --filter web-public dev
or run the Playwright suite, which boots the app and a stub for you:
  pnpm --filter web-public test:pii-sweep"
fi

# Every <code data-verify-command>…</code> body, one per line, entities decoded.
#
# `data-verify-command` is a marker the page puts on exactly the blocks that are meant to
# be executed. The expected-output blocks next to them are deliberately unmarked, so this
# never tries to run a sample of a verifier's stdout.
commands="$(
  printf '%s' "${html}" |
    tr '\n' ' ' |
    grep -o '<code data-verify-command[^>]*>[^<]*</code>' |
    sed -e 's/<code data-verify-command[^>]*>//' -e 's|</code>||' \
        -e 's/&#x27;/'"'"'/g' -e "s/&apos;/'/g" -e 's/&quot;/"/g' \
        -e 's/&amp;/\&/g' -e 's/&lt;/</g' -e 's/&gt;/>/g'
)"

if [ -z "${commands}" ]; then
  fail "no <code data-verify-command> blocks on ${PAGE}.
Either the page stopped rendering its examples, or the marker was renamed. Both mean the
gate is no longer checking anything, which is why an empty result is a failure and not a
pass."
fi

total=0
checked=0

while IFS= read -r command; do
  [ -z "${command}" ] && continue
  total=$((total + 1))

  say ""
  say "  ${command}"

  case "${command}" in
    curl*)
      # Extract the single-quoted URL and request it. Running the line through `eval`
      # would execute page content as shell, which is not a thing a build gate should do
      # however trusted the page is.
      url="$(printf '%s' "${command}" | sed -n "s/.*'\\([^']*\\)'.*/\\1/p")"
      [ -z "${url}" ] && fail "could not read a URL out of: ${command}"

      status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${url}" || echo 000)"
      if [ "${status}" != "200" ]; then
        fail "${url} returned ${status}, not 200.
The verify page tells every reader to run this. A non-200 here is a broken instruction on
the page that carries the platform's central claim."
      fi
      say "    -> 200 OK"
      checked=$((checked + 1))
      ;;

    python*sarana-verify*)
      # Not executed - see this file's header. What is asserted is that both URLs the
      # command passes are live, because those are the parts that drift.
      urls="$(printf '%s' "${command}" | grep -o "'[^']*'" | tr -d "'")"
      [ -z "${urls}" ] && fail "the verifier command names no URLs: ${command}"

      while IFS= read -r url; do
        [ -z "${url}" ] && continue
        status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${url}" || echo 000)"
        [ "${status}" != "200" ] && fail "${url} returned ${status}, not 200."
        say "    -> ${url} 200 OK"
      done <<EOF
${urls}
EOF
      say "    (the verifier itself is exercised by tests/ledger/test_public_feed.py)"
      checked=$((checked + 1))
      ;;

    *)
      fail "unrecognised command on the verify page: ${command}
This script knows how to check a curl invocation and the sarana-verify invocation. A new
kind of example needs a branch here rather than being skipped silently."
      ;;
  esac
done <<EOF
${commands}
EOF

say ""
say "${checked} of ${total} example(s) on /verify resolve against ${BASE_URL}."
