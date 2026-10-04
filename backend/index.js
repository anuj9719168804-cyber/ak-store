// Permanent-link redirector for File Store Pro (Cloudflare Worker).
//
//   https://<your-worker>/?url=<payload>              ->   302   https://t.me/<BOT_USERNAME>?start=<payload>
//   https://<your-worker>/?url=<payload>&bot=<name>   ->   302   https://t.me/<name>?start=<payload>
//
// Stateless: no database, no API keys. The <payload> is the same base64 string the bot puts in a
// normal t.me deep link, so it only depends on the DB channel + message id, never on the bot.
// If the bot is ever banned/replaced, change BOT_USERNAME below (or in the Cloudflare dashboard)
// and every link you ever shared keeps working.
//
// (The Multi-FileStoreBot worker stored link->owner mappings through the MongoDB Atlas Data API.
//  MongoDB shut that API down on 2025-09-30, so this version does not need it.)

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname !== '/') {
      return new Response('Not found', { status: 404 });
    }

    const payload = url.searchParams.get('url');
    if (!payload) {
      return new Response('Missing "url" parameter', { status: 400 });
    }
    // Deep-link payloads are URL-safe base64 (A-Z a-z 0-9 _ -). Refuse anything else.
    if (!/^[A-Za-z0-9_-]{1,256}$/.test(payload)) {
      return new Response('Invalid link', { status: 400 });
    }

    // Optional ?bot=<username> (used by user-created bots); otherwise the BOT_USERNAME variable.
    const botParam = String(url.searchParams.get('bot') || '').trim().replace(/^@/, '');
    if (botParam && !/^[A-Za-z0-9_]{4,32}$/.test(botParam)) {
      return new Response('Invalid bot', { status: 400 });
    }
    const bot = botParam || String(env.BOT_USERNAME || '').trim().replace(/^@/, '');
    if (!/^[A-Za-z0-9_]{4,32}$/.test(bot)) {
      return new Response('Worker is not configured: set the BOT_USERNAME variable.', { status: 500 });
    }

    return Response.redirect(`https://t.me/${bot}?start=${payload}`, 302);
  },
};
