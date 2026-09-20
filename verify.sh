#!/usr/bin/env bash
# verify.sh — prove Peek is read-only, by inspecting its own code.
#
# Peek's promise is that it CANNOT mark, move, delete, or send mail. This
# script demonstrates that from the source, so you never have to take it on
# faith. Run it before you install: ./verify.sh
#
# Exit 0 = read-only property holds. Exit 1 = something to look at.

set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
SRV="$DIR/server/server.py"
fail=0

echo "Peek — read-only verification"
echo "=============================="
echo "Inspecting: $SRV"
echo

# 1) No mailbox-mutating IMAP verbs anywhere in the server.
#    Target IMAP calls on the connection object `m` (m.store(, m.copy(, ...,
#    or m.uid("store"...)). This deliberately does NOT match Python's own
#    list .append() (e.g. parts.append()), which is not an IMAP operation.
echo "[1] No write/delete/move verbs in the code"
MUT='m\.(store|copy|expunge|append)\(|m\.uid\(\s*["'"'"'](store|copy|move|append)'
if grep -nE "$MUT" "$SRV" >/dev/null 2>&1; then
  echo "    FAIL — found a mutating IMAP call:"
  grep -nE "$MUT" "$SRV" | sed 's/^/      /'
  fail=1
else
  echo "    PASS — no STORE / COPY / MOVE / EXPUNGE / APPEND calls exist."
fi
echo

# 2) No SMTP / send path at all.
echo "[2] No sending capability"
if grep -nEi 'smtplib|sendmail|SMTP\(|starttls|send_message' "$SRV" >/dev/null 2>&1; then
  echo "    FAIL — found a send-related reference:"
  grep -nEi 'smtplib|sendmail|SMTP\(|starttls|send_message' "$SRV" | sed 's/^/      /'
  fail=1
else
  echo "    PASS — no SMTP or send code. Peek physically cannot send mail."
fi
echo

# 3) Mailboxes are opened read-only (IMAP EXAMINE).
echo "[3] Mailboxes opened in read-only (EXAMINE) mode"
sel=$(grep -cE '\.select\(.*readonly=True' "$SRV")
selbad=$(grep -E '\.select\(' "$SRV" | grep -v 'readonly=True' | wc -l | tr -d ' ')
if [ "$sel" -gt 0 ] && [ "$selbad" -eq 0 ]; then
  echo "    PASS — every mailbox open uses readonly=True ($sel found, 0 writable opens)."
else
  echo "    FAIL — found a mailbox opened without readonly=True."
  grep -nE '\.select\(' "$SRV" | sed 's/^/      /'
  fail=1
fi
echo

# 4) Every fetch uses BODY.PEEK (never sets the \Seen flag).
echo "[4] Reads use BODY.PEEK (never marks a message read)"
peek=$(grep -cE 'BODY\.PEEK' "$SRV")
badfetch=$(grep -nE 'uid\(\s*["'"'"']fetch' "$SRV" | grep -vc 'PEEK' )
if [ "$peek" -gt 0 ] && [ "$badfetch" -eq 0 ]; then
  echo "    PASS — all fetches use BODY.PEEK ($peek found, 0 non-PEEK fetches)."
else
  echo "    FAIL — a fetch does not use BODY.PEEK (could mark mail read)."
  grep -nE 'uid\(\s*["'"'"']fetch' "$SRV" | sed 's/^/      /'
  fail=1
fi
echo

# 5) Only three read tools are exposed.
echo "[5] Only read tools are exposed"
tools=$(grep -oE '"name": "(list_accounts|search_mail|read_message)"' "$SRV" | sort -u | wc -l | tr -d ' ')
other=$(grep -oE '"name": "[a-z_]+"' "$SRV" | grep -vE 'list_accounts|search_mail|read_message' | sort -u)
if [ "$tools" = "3" ] && [ -z "$other" ]; then
  echo "    PASS — exactly 3 tools, all read-only: list_accounts, search_mail, read_message."
else
  echo "    FAIL — an unexpected tool is exposed:"
  echo "$other" | sed 's/^/      /'
  fail=1
fi
echo

echo "=============================="
if [ "$fail" -eq 0 ]; then
  echo "RESULT: PASS — Peek is a window, not a hand. It can read your mail and nothing else."
  exit 0
else
  echo "RESULT: FAIL — review the lines above before trusting this build."
  exit 1
fi
