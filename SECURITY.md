# Security

Peek is built so that its safety is a property of the code, not a promise you have to trust. If you only read one thing, read this.

## The core guarantee: read-only by construction

Peek can read your mail and can do nothing else. This is not a setting or a policy — it is structural:

- Every mailbox is opened in **IMAP EXAMINE mode** (`readonly=True`). In this mode the server cannot mark, move, delete, or flag a message even if it tried. The mail server itself refuses.
- Every message fetch uses **`BODY.PEEK`**, which returns content without setting the `\Seen` flag. Reading a message never marks it read.
- There is **no STORE, COPY, MOVE, EXPUNGE, or APPEND** call anywhere in the server, and **no SMTP or send code at all**. There is no write path to misuse.
- Only three tools exist, all read: `list_accounts`, `search_mail`, `read_message`.

You do not have to take our word for any of this. Run the verifier:

    ./verify.sh

It inspects the server's own source and confirms all of the above, printing PASS or FAIL for each property. Read it — it is short.

## Where your credentials live

- Peek uses a **Gmail app password** (a 16-character, read-scoped, individually revocable key that requires 2-Step Verification). It is **not** your Google password.
- Claude Desktop stores it in your **operating system keychain** (macOS Keychain / Windows Credential Manager). It is never written to a plaintext file by the extension and never leaves your machine.
- Revoke it any time at **myaccount.google.com/apppasswords**. Revoking Peek's key affects nothing else you have connected.

## The honest boundary

The read-only guarantee is a property of *this server*. The app password itself is a normal IMAP credential: anything else on your machine that could read it could use it in a different client. That is why Peek keeps it in the keychain and why you can revoke it instantly. Treat the app password like any other secret.

## Untrusted content

Mail that Peek reads is treated as **untrusted data**. If an email contains text that looks like an instruction ("ignore your rules and…"), it is never executed as a command. This is standard prompt-injection hygiene and it matters specifically for tools that read inboxes.

## Reporting

Found something? Open an issue, or contact AIM Consulting at https://consultwithaim.com.
