"""Text for /help. Kept free of Telegram imports so it can be unit-tested.

Every command named here must also be listed in the exclusion filter of plugins/channel_post.py,
otherwise an admin's /command would be treated as a file to upload (tests/test_help_cmd.py checks this).
"""

USER_COMMANDS = (
    ("start", "open the bot / get a file from a link"),
    ("search", "find a file by name, e.g. /search avengers 1080p"),
    ("daily", "claim your free daily credits"),
    ("refer", "get your invite link and earn credits"),
    ("redeem", "use a gift code, e.g. /redeem CODE"),
    ("credits", "see your credits"),
    ("cplan", "buy more credits"),
    ("buy", "premium plans"),
    ("profile", "your plan"),
    ("info", "your Telegram details and account age"),
    ("contact", "write to the admins, e.g. /contact my link is broken"),
    ("trial", "one free premium trial (if the owner switched it on)"),
    ("bots", "create and manage your own file-store bot"),
    ("about", "about this bot"),
    ("help", "this list"),
)

ADMIN_COMMANDS = (
    ("Links", (
        ("genlink", "link for one file"), ("batch", "link for a range of posts"),
        ("nbatch", "numbered batch"), ("custom_batch", "pick posts one by one"),
        ("flink", "link to a forwarded post"), ("explink", "link with time / use limit"),
        ("links", "list expiring links"), ("revoke", "cancel an expiring link"),
    )),
    ("Users", (
        ("users", "user count"), ("stats", "bot status"), ("broadcast", "message everyone"),
        ("pbroadcast", "pinned broadcast"), ("ban", "ban a user: /ban id [id..] [reason]"), ("unban", "unban a user"),
        ("unbanall", "unban everyone"), ("reply", "answer a /contact message"),
    )),
    ("Premium & credits", (
        ("addpremium", "give premium"), ("delpremium", "remove premium"),
        ("premiumusers", "list premium users"), ("add_credit", "give credits"),
        ("gencode", "make gift codes"), ("codes", "list gift codes"),
        ("delcode", "delete a gift code"), ("ledger", "credit history"),
    )),
    ("Setup", (
        ("shortner", "shortener settings"), ("db", "DB channels"), ("adddb", "add a DB channel"),
        ("removedb", "remove a DB channel"), ("addadmin", "add an admin"),
        ("removeadmin", "remove an admin"), ("autobatch", "auto-group qualities into one link: on / off / seconds"),
        ("autoquality", "make 144p-1080p copies of stored videos: on / off / set"), ("genquality", "make the qualities of a stored video"),
        ("autosplit", "auto-split files over 2 GB into parts: on / off"), ("gensplit", "split a stored big file"),
        ("maintenance", "maintenance mode: on / off"),
        ("set_expiry", "how long new web links stay valid: 1h / 2d / 0 / reset"),
    )),
    ("Auto-post", (
        ("addpostch", "add a post channel"), ("rmpostch", "remove a post channel"),
        ("postchs", "list post channels"), ("autopost", "schedule a post"),
        ("scheduled", "scheduled posts"), ("cancelpost", "cancel a scheduled post"),
    )),
)

OWNER_COMMANDS = (
    ("backup", "back up the database now"), ("logs", "latest log lines as a file"),
    ("restart", "restart the bot"), ("mban", "ban a user from all user-made bots"),
    ("munban", "undo mban"), ("mcast", "message all user-made bots' owners"),
    ("check", "check a user-made bot"), ("sysstats", "server stats"),
)


def all_listed_commands() -> set:
    names = {c for c, _ in USER_COMMANDS} | {c for c, _ in OWNER_COMMANDS}
    for _, rows in ADMIN_COMMANDS:
        names |= {c for c, _ in rows}
    return names


def render(is_admin: bool, is_owner: bool = False) -> str:
    lines = ["<blockquote>📖 <b>Commands</b></blockquote>"]
    lines += [f"/{c} — {d}" for c, d in USER_COMMANDS]
    if is_admin:
        for title, rows in ADMIN_COMMANDS:
            lines += ["", f"<b>🛠 {title}</b>"]
            lines += [f"/{c} — {d}" for c, d in rows]
    if is_owner:
        lines += ["", "<b>👑 Owner</b>"]
        lines += [f"/{c} — {d}" for c, d in OWNER_COMMANDS]
    return "\n".join(lines)
