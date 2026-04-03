# TradingAgents Frontend

Next.js 15 frontend for the TradingAgents multi-agent trading analysis platform.

## Tech Stack

- **Framework:** Next.js 15 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4
- **Charts:** Recharts + Lightweight Charts
- **Streaming:** Server-Sent Events (SSE)

## Setup

```bash
# 1. Install dependencies
cd frontend
npm install

# 2. Configure environment
cp .env.local.example .env.local
# Edit .env.local if your API runs on a different port

# 3. Start dev server
npm run dev
```

The app will be available at [http://localhost:3000](http://localhost:3000).

## Prerequisites

The backend API server must be running on `http://localhost:8000` (configurable via `NEXT_PUBLIC_API_URL`).

## Pages

| Route          | Description                                      |
| -------------- | ------------------------------------------------ |
| `/`            | Dashboard with system stats and recent analyses  |
| `/analysis`    | Trigger new analysis with live SSE progress       |
| `/divergence`  | Agent divergence heatmap across dimensions        |
| `/backtest`    | Run backtests and view trade-level results        |
| `/portfolio`   | Current portfolio positions and P&L               |

## Project Structure

```
src/
  app/              # Next.js App Router pages
  components/       # Shared UI components
  hooks/            # React hooks (useSSE for streaming)
  lib/              # API client and utilities
```

## Build

```bash
npm run build
npm start
```
