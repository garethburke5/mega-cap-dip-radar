
# Mega-Cap Dip Radar

A free personal dashboard + Telegram alert system for five stocks:

- TSLA
- NVDA
- META
- AMZN
- GOOGL

## What it does

The dashboard tracks:
- current price
- drawdown from a rolling high
- rebound from the recent correction low
- RSI
- distance from 50-day moving average
- volume versus normal
- opportunity status

The scheduled checker sends a Telegram message when a stock changes into:
- OPPORTUNITY
- REVERSAL ALERT
- EXTREME + REVERSAL

It is intentionally not an automatic trading system.

## Free stack

- GitHub: code + scheduled checks
- GitHub Actions: hourly checks on US trading days
- Streamlit Community Cloud: phone-friendly dashboard
- yfinance / Yahoo Finance data
- Telegram Bot API: alerts

## 1. Put this folder in GitHub

Create a new GitHub repository and upload all files in this folder, including the `.github` folder.

## 2. Create a Telegram bot

In Telegram:
1. Open BotFather.
2. Send `/newbot`.
3. Follow the prompts.
4. Copy the bot token.

Then open your new bot and send it any message, e.g. `hello`.

To find your chat ID, open this in a browser after replacing YOUR_TOKEN:

`https://api.telegram.org/botYOUR_TOKEN/getUpdates`

Look for:

`"chat":{"id":123456789,...}`

That number is your Telegram chat ID.

## 3. Add GitHub secrets

In your GitHub repository:

Settings → Secrets and variables → Actions → New repository secret

Add:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Never put the actual token in the Python files.

## 4. Test the alert checker

GitHub repository → Actions → Check dip opportunities → Run workflow.

If a stock is not currently in a trigger state, no Telegram alert will be sent. That is expected.

## 5. Deploy the dashboard on Streamlit Community Cloud

Go to Streamlit Community Cloud.

Create app → choose your GitHub repo → select:

`app.py`

Deploy.

You will receive a normal web address that opens on your phone.

## Current default thresholds

- TSLA: -20% opportunity, -30% extreme
- NVDA: -20% opportunity, -30% extreme
- META: -20% opportunity, -30% extreme
- AMZN: -15% opportunity, -25% extreme
- GOOGL: -15% opportunity, -25% extreme

Rolling-high window: 90 trading days.

Reversal confirmation: +5% from the correction low.

## How duplicate alerts are prevented

`alert_state.json` stores the last alert state for each stock.

If TSLA stays in OPPORTUNITY for five consecutive checks, you do not receive five identical notifications.

You get another alert when the state changes, for example:

OPPORTUNITY → REVERSAL ALERT

or

REVERSAL ALERT → EXTREME + REVERSAL

## Important

This is a research and decision-support tool, not financial advice. Historical recoveries do not guarantee future recoveries. Always inspect the reason for a major fall before trading.
