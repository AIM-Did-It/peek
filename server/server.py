#!/usr/bin/env python3
"""Peek — read-only IMAP access to one or more Gmail inboxes, for Claude.

Zero dependencies (Python standard library only).

Credentials come from the host as environment variables, which Claude Desktop
stores in the OS keychain and injects at launch. Multiple accounts are
supported: MAIL_EMAIL_1 / MAIL_APP_PASSWORD_1, MAIL_EMAIL_2 / MAIL_APP_PASSWORD_2,
and so on. (MAIL_EMAIL / MAIL_APP_PASSWORD without a number also works as a
single account.) A local accounts.json beside this file is honored as a
fallback for self-hosting.

Strictly read-only by construction: mailboxes are opened in IMAP EXAMINE
(read-only) mode and every fetch uses BODY.PEEK, so nothing is ever marked
read, moved, deleted, or sent. There is no STORE / COPY / APPEND / EXPUNGE /
MOVE path anywhere in this file, for any number of accounts.
"""
import json, sys, os, imaplib, email, re, socket
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE, "accounts.json")
socket.setdefaulttimeout(30)


def _clean(v):
    return (v or "").strip()


def load_accounts():
    """Return {account_key: {email, app_password, host}}.

    Priority 1: accounts injected via environment (the bundle path) — any of
      MAIL_EMAIL_1/MAIL_APP_PASSWORD_1 .. MAIL_EMAIL_9/MAIL_APP_PASSWORD_9,
      plus the un-numbered MAIL_EMAIL/MAIL_APP_PASSWORD. Each account is keyed
      by its email address.
    Priority 2: accounts.json beside this file (self-host / multi-account).
    """
    out = {}
    pairs = [("MAIL_EMAIL", "MAIL_APP_PASSWORD")]
    pairs += [("MAIL_EMAIL_%d" % n, "MAIL_APP_PASSWORD_%d" % n) for n in range(1, 10)]
    for ekey, pkey in pairs:
        email_addr = _clean(os.environ.get(ekey))
        pw = _clean(os.environ.get(pkey))
        if email_addr and pw and "PASTE" not in pw:
            out[email_addr] = {"email": email_addr, "app_password": pw,
                               "host": os.environ.get("MAIL_HOST", "imap.gmail.com")}
    if out:
        return out
    if os.path.exists(CONF):
        with open(CONF) as f:
            cfg = json.load(f)
        return {k: v for k, v in cfg.get("accounts", {}).items()
                if v.get("app_password") and "PASTE" not in v["app_password"]}
    return {}


def resolve_targets(args, accounts):
    """Which accounts a call operates on: the one named, or all configured."""
    acct = args.get("account")
    if acct:
        if acct not in accounts:
            raise ValueError("Unknown account '%s'. Configured: %s"
                             % (acct, ", ".join(sorted(accounts)) or "none"))
        return [acct]
    if not accounts:
        raise ValueError("No account configured. Add a Gmail address and app "
                         "password in the extension settings.")
    return list(accounts)  # all


def connect(acct, accounts):
    a = accounts[acct]
    m = imaplib.IMAP4_SSL(a.get("host", "imap.gmail.com"))
    m.login(a["email"], a["app_password"].replace(" ", ""))
    return m


def dh(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def body_text(msg, limit=20000):
    parts = []
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain" and "attachment" not in str(p.get("Content-Disposition", "")):
                try:
                    parts.append(p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace"))
                except Exception:
                    pass
        if not parts:
            for p in msg.walk():
                if p.get_content_type() == "text/html":
                    try:
                        h = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
                        parts.append(re.sub(r"<[^>]+>", " ", h))
                        break
                    except Exception:
                        pass
    else:
        try:
            raw = msg.get_payload(decode=True)
            t = raw.decode(msg.get_content_charset() or "utf-8", "replace") if raw else ""
            if msg.get_content_type() == "text/html":
                t = re.sub(r"<[^>]+>", " ", t)
            parts.append(t)
        except Exception:
            pass
    t = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()
    return t[:limit] + ("\n…[truncated]" if len(t) > limit else "")


def headline(m, uid, acct):
    typ, data = m.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
    if typ != "OK" or not data or data[0] is None:
        return None
    msg = email.message_from_bytes(data[0][1])
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        d = dt.strftime("%Y-%m-%d %H:%M")
        sortkey = dt.timestamp()
    except Exception:
        d = msg.get("Date", "")
        sortkey = 0
    return {"account": acct, "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
            "date": d, "from": dh(msg.get("From")), "subject": dh(msg.get("Subject")),
            "_sort": sortkey}


def t_list_accounts(args):
    accounts = load_accounts()
    out = [{"account": k, "email": v.get("email"), "configured": True} for k, v in accounts.items()]
    if not out:
        return "No account configured yet. Add a Gmail address and app password in the extension settings."
    return json.dumps(out, indent=1)


def t_search(args):
    accounts = load_accounts()
    targets = resolve_targets(args, accounts)   # one named account, or all
    q = args.get("query", "")
    limit = min(int(args.get("limit", 15)), 50)
    rows = []
    for acct in targets:
        m = connect(acct, accounts)
        try:
            m.select('"' + args.get("folder", "INBOX") + '"', readonly=True)
            typ, data = m.uid("search", None, "X-GM-RAW", '"' + q.replace('"', "'") + '"') if q else m.uid("search", None, "ALL")
            if typ != "OK":
                continue
            uids = data[0].split()[-limit:][::-1]
            for u in uids:
                h = headline(m, u, acct)
                if h:
                    rows.append(h)
        finally:
            try:
                m.logout()
            except Exception:
                pass
    if not rows:
        return "No messages matched."
    rows.sort(key=lambda r: r.pop("_sort"), reverse=True)   # newest first across all accounts
    return json.dumps(rows[:limit], indent=1)


def t_read(args):
    accounts = load_accounts()
    acct = args.get("account")
    if not acct:
        if len(accounts) == 1:
            acct = next(iter(accounts))
        else:
            raise ValueError("Specify 'account' (one of: %s) — UIDs are per-account. "
                             "Use the 'account' shown next to the message in search_mail."
                             % ", ".join(sorted(accounts)))
    if acct not in accounts:
        raise ValueError("Unknown account '%s'. Configured: %s" % (acct, ", ".join(sorted(accounts)) or "none"))
    uid = str(args["uid"])
    m = connect(acct, accounts)
    try:
        m.select('"' + args.get("folder", "INBOX") + '"', readonly=True)
        typ, data = m.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or data[0] is None:
            return "Message not found."
        msg = email.message_from_bytes(data[0][1])
        head = {"account": acct}
        head.update({k: dh(msg.get(k)) for k in ("From", "To", "Date", "Subject")})
        return json.dumps(head, indent=1) + "\n\n" + body_text(msg)
    finally:
        try:
            m.logout()
        except Exception:
            pass


TOOLS = [
    {"name": "list_accounts",
     "description": "List the mail account(s) configured for this extension.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "search_mail",
     "description": "Search mail with Gmail search syntax (e.g. 'from:alerts@bofa.com newer_than:2d', 'subject:invoice'). Searches ALL configured accounts and returns newest-first headlines, each tagged with its 'account'. Pass 'account' to search just one. Read-only.",
     "inputSchema": {"type": "object", "properties": {
         "account": {"type": "string", "description": "Optional. An account from list_accounts. Omit to search every configured account at once."},
         "query": {"type": "string", "description": "Gmail search syntax; empty = most recent."},
         "limit": {"type": "integer", "description": "Max results, default 15, max 50."},
         "folder": {"type": "string", "description": "IMAP folder, default INBOX. Use '[Gmail]/All Mail' for everything."}},
         "required": []}},
    {"name": "read_message",
     "description": "Read one message (headers + plain-text body) by UID from search_mail. Pass the 'account' shown next to that message (UIDs are per-account). Read-only — never marks as read.",
     "inputSchema": {"type": "object", "properties": {
         "account": {"type": "string", "description": "The account the message belongs to (from search_mail). Optional only if a single account is configured."},
         "uid": {"type": "string"},
         "folder": {"type": "string", "description": "Must match the folder searched, default INBOX."}},
         "required": ["uid"]}},
]
HANDLERS = {"list_accounts": t_list_accounts, "search_mail": t_search, "read_message": t_read}


def reply(id_, result=None, error=None):
    r = {"jsonrpc": "2.0", "id": id_}
    if error:
        r["error"] = {"code": -32000, "message": error}
    else:
        r["result"] = result
    sys.stdout.write(json.dumps(r) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params", {})
        if mid is None:
            continue  # notification — no reply
        if method == "initialize":
            reply(mid, {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "peek-mail", "version": "1.1.0"}})
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            fn = HANDLERS.get(name)
            if not fn:
                reply(mid, error="Unknown tool: %s" % name)
                continue
            try:
                reply(mid, {"content": [{"type": "text", "text": fn(args)}]})
            except imaplib.IMAP4.error as e:
                reply(mid, {"content": [{"type": "text", "text": "IMAP error (check the app password, and that IMAP + 2-step verification are enabled on the account): %s" % e}], "isError": True})
            except Exception as e:
                reply(mid, {"content": [{"type": "text", "text": "Error: %s" % e}], "isError": True})
        elif method == "ping":
            reply(mid, {})
        else:
            reply(mid, error="Method not supported: %s" % method)


if __name__ == "__main__":
    main()
