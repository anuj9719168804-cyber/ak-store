# Permanent Link worker (Cloudflare)

Makes the links the bot generates **permanent**: instead of `https://t.me/<bot>?start=...` the bot
hands out `https://<your-worker>/?url=...`, which redirects to whatever bot is configured here.
If your bot is banned or you move to a new one, change one variable and all old links work again
(as long as the new bot uses the same DB channel).

Free Cloudflare plan is enough. No database is needed.

## Setup

```bash
npm install -g wrangler
wrangler login
cd backend
# edit wrangler.toml -> BOT_USERNAME = "YourBot"
wrangler deploy
```

Wrangler prints a URL like `https://filestore-permanent-link.<you>.workers.dev`.

## Turn it on in the bot

1. Set the environment variable (or `.env`) and restart the bot:
   ```
   BACKEND_API_URL=https://filestore-permanent-link.<you>.workers.dev
   ```
2. Open the bot's `/settings` -> **Next** -> **Permanent Link** (or the web panel -> Settings) and switch it on.

**User-created bots (multi-bot system):** the same worker is used. Their links look like
`https://<worker>/?url=<payload>&bot=<their_bot_username>`, so one worker serves every bot and no
extra setup is needed. A user switches it on in their bot dashboard -> **Permanent Link**.
(If a user replaces their bot, links made earlier keep the old `&bot=` name.)

Links generated from then on (`/genlink`, `/batch`, `/nbatch`, `/custom_batch`, `/flink`, uploads) use the worker URL.
Old `t.me` links keep working; switching it off goes back to normal links.
