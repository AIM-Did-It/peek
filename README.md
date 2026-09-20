# Peek

**Let Claude read your Gmail, safely.**

Add Peek to Claude and it can search and read your inbox right inside a conversation. Ask "what did my bank send this week," "pull the invoice from Tuesday," or "summarize what I missed." Claude answers from your actual mail.

## Why Peek is different

Peek is **read-only by construction, not by promise.** It opens your mailbox in IMAP read-only mode (EXAMINE) and every fetch uses `BODY.PEEK`, so it cannot mark a message read, move it, delete it, or send anything. There is no write path anywhere in the code. Most mail integrations ask for full access. Peek is built so it *can't* do harm, and the whole server is one short file you can read to confirm.

- **Read-only, provably.** No STORE, COPY, APPEND, EXPUNGE, or MOVE anywhere.
- **No servers, no cloud.** It runs on your machine, on demand, and exits with the session. Nothing listens on any port.
- **Your credentials stay put.** Stored in your operating system's keychain, never uploaded. Revoke any time from your Google account.
- **Zero dependencies.** Python standard library only, so there is no supply chain to trust.

## Install (Claude Desktop)

1. Download `peek-mail.mcpb` and double-click it. Claude Desktop installs the extension.
2. In the extension settings, enter your **Gmail address** and a **Gmail app password**.
3. Ask Claude about your email.

### Getting a Gmail app password (about 2 minutes)

1. Turn on 2-Step Verification on your Google account if it is not already on.
2. Go to **myaccount.google.com/apppasswords**.
3. Create a password named "Peek" and copy the 16-character code.
4. Paste it into the Peek settings. You can revoke it any time on the same page.

## Requirements

- Claude Desktop with extension support.
- Python 3.9 or newer available on your system (macOS and most Linux ship this; on Windows, install from python.org).

## Try asking

Once installed, just talk to Claude in plain language:

- "What did my bank send this week?"
- "Pull up the invoice from Tuesday and summarize it."
- "Did I get anything from my accountant in the last month?"
- "Summarize the unread threads in my inbox."
- "Find the confirmation email for my flight."

## Prove it can't touch your mail

Before you trust it, run the verifier — it reads Peek's own source and confirms, line by line, that there is no way for it to send, delete, or modify anything:

    ./verify.sh

See [SECURITY.md](SECURITY.md) for the full read-only guarantee.

## Tools

| Tool | What it does |
|---|---|
| `list_accounts` | Show the configured account. |
| `search_mail` | Search with Gmail syntax (`from:`, `subject:`, `newer_than:2d`, etc.). Returns newest-first headlines with UIDs. |
| `read_message` | Read one message's headers and plain-text body by UID. |

## A note on trust

Mail content Claude reads through Peek is treated as untrusted data. Instructions that happen to appear inside an email are never followed as commands. This is standard prompt-injection hygiene.

## License

MIT. Built by [AIM Consulting LLC](https://consultwithaim.com).
