#!/usr/bin/env python3
"""Peek — read-only IMAP access to Gmail for Claude.

Zero dependencies (Python standard library only).

Credentials come from the host as environment variables (MAIL_EMAIL,
MAIL_APP_PASSWORD), which Claude Desktop stores in the OS keychain and injects
at launch. A local accounts.json beside this file is supported as a fallback
for self-hosting and multiple accounts.

Strictly read-only by construction: mailboxes are opened in IMAP EXAMINE
(read-only) mode and every fetch uses BODY.PEEK, so nothing is ever marked
read, moved, deleted, or sent. There is no STORE / COPY / APPEND / EXPUNGE /
MOVE path anywhere in this file.
"""
import json, sys, os, imaplib, email, re, socket
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE, "accounts.json")
socket.setdefaulttimeout(30)


def load_accounts():
    """Return {key: {email, app_password, host}}.

    Priority 1: a single account injected via environment (the bundle path).
    Priority 2: accounts.json beside this file (self-host / multi-account).
    """
    email_addr = os.environ.get("MAIL_EMAIL", "").strip()
    pw = os.environ.get("MAIL_APP_PASSWORD", "").strip()
    if email_addr and pw and "PASTE" not in pw:
        return {"default": {"email": email_addr, "app_password": pw,
                            "host": os.environ.get("MAIL_HOST", "imap.gmail.com")}}
    if os.path.exists(CONF):
        with open(CONF) as f:
            cfg = json.load(f)
        return {k: v for k, v in cfg.get("accounts", {}).items()
                if v.get("app_password") and "PASTE" not in v["app_password"]}
    return {}


def resolve_account(args, accounts):
    """Pick the account: the one named, or the only one configured."""
    acct = args.get("account")
    if acct:
        if acct not in accounts:
            raise ValueError("Unknown account '%s'. Configured: %s"
                             % (acct, ", ".join(sorted(accounts)) or "none"))
        return acct
    if len(accounts) == 1:
        return next(iter(accounts))
    if not accounts:
        raise ValueError("No account configured. Add your Gmail address and app "
                         "password in the extension settings.")
    raise ValueError("Multiple accounts configured; pass 'account' (one of: %s)."
                     % ", ".join(sorted(accounts)))


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


def headline(m, uid):
    typ, data = m.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
    if typ != "OK" or not data or data[0] is None:
        return None
    msg = email.message_from_bytes(data[0][1])
    try:
        d = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        d = msg.get("Date", "")
    return {"uid": uid.decode() if isinstance(uid, bytes) else str(uid),
            "date": d, "from": dh(msg.get("From")), "subject": dh(msg.get("Subject"))}


def t_list_accounts(args):
    accounts = load_accounts()
    out = [{"account": k, "email": v.get("email"), "configured": True}
           for k, v in accounts.items()]
    if not out:
        return "No account configured yet. Add your Gmail address and app password in the extension settings."
    return json.dumps(out, indent=1)


def t_search(args):
    accounts = load_accounts()
    acct = resolve_account(args, accounts)
    q = args.get("query", "")
    limit = min(int(args.get("limit", 15)), 50)
    m = connect(acct, accounts)
    try:
        m.select('"' + args.get("folder", "INBOX") + '"', readonly=True)
        typ, data = m.uid("search", None, "X-GM-RAW", '"' + q.replace('"', "'") + '"') if q else m.uid("search", None, "ALL")
        if typ != "OK":
            return "Search failed."
        uids = data[0].split()
        uids = uids[-limit:][::-1]
        rows = [h for u in uids if (h := headline(m, u))]
        return json.dumps(rows, indent=1) if rows else "No messages matched."
    finally:
        try:
            m.logout()
        except Exception:
            pass


def t_read(args):
    accounts = load_accounts()
    acct = resolve_account(args, accounts)
    uid = str(args["uid"])
    m = connect(acct, accounts)
    try:
        m.select('"' + args.get("folder", "INBOX") + '"', readonly=True)
        typ, data = m.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or data[0] is None:
            return "Message not found."
        msg = email.message_from_bytes(data[0][1])
        head = {k: dh(msg.get(k)) for k in ("From", "To", "Date", "Subject")}
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
     "description": "Search the mailbox with Gmail search syntax (e.g. 'from:alerts@bofa.com newer_than:2d', 'subject:invoice'). Returns newest-first headlines with UIDs. Read-only.",
     "inputSchema": {"type": "object", "properties": {
         "account": {"type": "string", "description": "Optional. Only needed if more than one account is configured."},
         "query": {"type": "string", "description": "Gmail search syntax; empty = most recent."},
         "limit": {"type": "integer", "description": "Max results, default 15, max 50."},
         "folder": {"type": "string", "description": "IMAP folder, default INBOX. Use '[Gmail]/All Mail' for everything."}},
         "required": []}},
    {"name": "read_message",
     "description": "Read one message (headers + plain-text body) by UID from search_mail. Read-only — never marks as read.",
     "inputSchema": {"type": "object", "properties": {
         "account": {"type": "string", "description": "Optional. Only needed if more than one account is configured."},
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
                        "serverInfo": {"name": "peek-mail", "version": "1.0.0"}})
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
