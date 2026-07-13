# Product Launch Tracker

**[🔗 Live app](https://appuct-launch-newsfeed-ikdapki88wvs4vnnhwezyx.streamlit.app/)**

A daily-refreshing dashboard that tracks NASDAQ-100 companies for real
product-launch news, cross-checks it against multiple sources before
treating it as confirmed, and turns each confirmed launch into a short,
readable brief with a stock snapshot.

## What it does

- Watches all 100 NASDAQ-100 companies for product-launch news every day
- Only surfaces a launch once it's been reported by two independent sources
  (or one major wire service), filtering out noise like earnings reports
  and routine press releases
- Auto-generates a plain-language summary and stock snapshot for each
  confirmed launch
- Presents everything in a simple, browsable dashboard — pick a date, pick
  a company, read the brief

## How it works

```mermaid
flowchart LR
    A["📰 Scan the news"] --> B["✅ Confirm it's real"]
    B --> C["✍️ Write a brief"]
    C --> D["📊 Live dashboard"]
```

1. **Scan the news** — each company is checked daily against recent news
   coverage.
2. **Confirm it's real** — a launch only counts once it's corroborated by
   multiple outlets, filtering out routine financial news.
3. **Write a brief** — a short, plain-language summary is generated
   alongside a stock snapshot (price, 1-year change, 52-week range).
4. **Live dashboard** — everything is published to the app above
   automatically, no manual updates.

## Built with

Python · Streamlit · Google News · Yahoo Finance data · Claude (Anthropic)

## A note on the content

This is not investment advice. The stock data shown is historical/current
only — no forecasts, and no claim that a launch caused any price movement.
