# X Monitor Skill

Autonomous Twitter/X monitoring service that scans accounts hourly, analyzes with Cerebras, and posts highlights to Telegram.

## Features
- Hourly scans of configured X accounts
- Cerebras-powered highlight extraction
- Automatic Telegram posting to configured group
- Deployed on Coolify as persistent service

## Target Accounts
- @pumpdotfun / @pump_fun - Pump.fun official
- @RaydiumProtocol - Raydium DEX
- @MeteoraAG - Meteora DEX  
- @solaboratory - Solana ecosystem
- @MarioNawfal - Crypto news
- @RohOnChain - DeFi/trading insights

## Configuration
Environment variables:
- `CEREBRAS_API_KEY` - Cerebras API key
- `TELEGRAM_BOT_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Target chat ID (-5223082150)
- `SCAN_INTERVAL` - Scan interval in seconds (default: 3600)

## Deployment
Deployed via Coolify at `x-monitor.machinemachine.ai`

## Manual Run
```bash
~/.openclaw/skills/x-monitor/monitor.py --once
```
