SKY SPORT AFAAN OROMOO — RENDER V14

This is a Render Web Service backend. It:
- receives Telegram /start webhook requests
- registers subscribers
- sends a Mini App button
- validates Telegram Mini App initData
- checks the Blogger RSS feed hourly
- sends new posts to registered users
- retries Telegram/feed transient failures
- handles Telegram 429 and removes blocked users
- exposes /health
- stores state in a JSON file.

IMPORTANT STORAGE NOTE:
Render services have ephemeral filesystems by default. This V14 is designed to work immediately for testing/small deployments, but for durable subscriber state use Render Postgres or another persistent datastore. Do NOT rely on the local JSON file for long-term production data.

ENVIRONMENT VARIABLES:
BOT_TOKEN = your Telegram bot token (Render Secret)
WEB_APP_URL = https://t.me/sky_sport_afaan_oromoo_bot/sky_sporti
FEED_URL = your Blogger RSS feed
PUBLIC_BASE_URL = your Render URL, e.g. https://sky-sport-telegram-backend.onrender.com
ADMIN_SECRET = random secret
POLL_SECONDS = 3600

RENDER:
New -> Web Service
Build: pip install -r requirements.txt
Start: python app.py
Health Check: /health

TELEGRAM WEBHOOK:
After deployment, set the webhook to:
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<PUBLIC_BASE_URL>/telegram/webhook

Test:
GET <PUBLIC_BASE_URL>/health
Then send /start to the bot.

MINI APP:
The Blogger XML should use:
https://t.me/sky_sport_afaan_oromoo_bot/sky_sporti

SECURITY:
Never put BOT_TOKEN in Blogger XML, browser JS, GitHub, or chat. Keep it as a Render environment secret.
