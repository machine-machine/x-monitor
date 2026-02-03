#!/usr/bin/env python3
"""
X Monitor - Autonomous Twitter monitoring with Cerebras analysis.
Scans target accounts hourly and posts highlights to Telegram.
"""

import os
import json
import time
import logging
import hashlib
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Target accounts to monitor
TARGET_ACCOUNTS = [
    "pumpdotfun",
    "RaydiumProtocol", 
    "MeteoraAG",
    "solaboratory",
    "MarioNawfal",
    "RohOnChain",
    "xDaily",
    "solaboratory",
]

# Nitter instances for scraping (fallback)
NITTER_INSTANCES = [
    "https://nitter.lucabased.xyz",
    "https://nitter.perennialte.ch", 
    "https://nitter.woodland.cafe",
    "https://xcancel.com",
]

# State file for deduplication
STATE_FILE = Path("/data/x-monitor-state.json") if Path("/data").exists() else Path.home() / ".openclaw/skills/x-monitor/state.json"


def load_state() -> dict:
    """Load seen tweets state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {"seen_hashes": [], "last_scan": None}
    return {"seen_hashes": [], "last_scan": None}


def save_state(state: dict):
    """Save state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_tweets_nitter(account: str) -> list[dict]:
    """Fetch recent tweets via Nitter RSS."""
    tweets = []
    
    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/{account}/rss"
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DEXY-Monitor/1.0)"
            })
            
            if resp.status_code == 200:
                # Parse RSS
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                
                for item in root.findall(".//item")[:10]:  # Last 10 tweets
                    title = item.find("title")
                    link = item.find("link")
                    pub_date = item.find("pubDate")
                    description = item.find("description")
                    
                    if title is not None:
                        tweets.append({
                            "author": f"@{account}",
                            "text": title.text or "",
                            "url": link.text if link is not None else "",
                            "timestamp": pub_date.text if pub_date is not None else "",
                            "description": description.text if description is not None else "",
                        })
                
                logger.info(f"Fetched {len(tweets)} tweets from @{account} via {instance}")
                return tweets
                
        except Exception as e:
            logger.warning(f"Failed to fetch from {instance}: {e}")
            continue
    
    return tweets


def fetch_tweets_direct(account: str) -> list[dict]:
    """Fetch tweets via X's syndication API (public, no auth needed)."""
    tweets = []
    
    # Try multiple endpoints
    endpoints = [
        f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{account}",
        f"https://publish.twitter.com/oembed?url=https://twitter.com/{account}",
    ]
    
    for url in endpoints:
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/json",
            })
            
            if resp.status_code == 200:
                import re
                
                # Try JSON format (oembed)
                if 'application/json' in resp.headers.get('content-type', '') or url.endswith('.json'):
                    try:
                        data = resp.json()
                        if 'html' in data:
                            text = re.sub(r'<[^>]+>', '', data['html']).strip()
                            if text:
                                tweets.append({
                                    "author": f"@{account}",
                                    "text": text[:500],
                                    "url": f"https://x.com/{account}",
                                })
                    except:
                        pass
                
                # Try HTML format (syndication)
                elif "timeline-Tweet" in resp.text or "Tweet-text" in resp.text:
                    tweet_pattern = re.compile(
                        r'data-tweet-id="(\d+)".*?<p[^>]*class="[^"]*(?:timeline-Tweet-text|Tweet-text)[^"]*"[^>]*>(.*?)</p>',
                        re.DOTALL
                    )
                    
                    for match in tweet_pattern.finditer(resp.text):
                        tweet_id, text = match.groups()
                        text = re.sub(r'<[^>]+>', '', text).strip()
                        
                        if text:
                            tweets.append({
                                "author": f"@{account}",
                                "text": text,
                                "url": f"https://x.com/{account}/status/{tweet_id}",
                                "id": tweet_id,
                            })
                
                if tweets:
                    logger.info(f"Fetched {len(tweets)} tweets from @{account} via syndication")
                    return tweets
                
        except Exception as e:
            logger.warning(f"Direct fetch failed for @{account}: {e}")
            continue
    
    return tweets


def fetch_all_tweets() -> list[dict]:
    """Fetch tweets from all target accounts."""
    all_tweets = []
    
    for account in TARGET_ACCOUNTS:
        # Try direct first, fall back to nitter
        tweets = fetch_tweets_direct(account)
        if not tweets:
            tweets = fetch_tweets_nitter(account)
        
        all_tweets.extend(tweets)
        time.sleep(2)  # Rate limiting between accounts
    
    return all_tweets


def analyze_with_cerebras(tweets: list[dict]) -> str:
    """Send tweets to Cerebras for highlight extraction."""
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        # Try loading from config file
        config_path = Path.home() / ".config/cerebras/config"
        if config_path.exists():
            for line in config_path.read_text().split('\n'):
                if line.startswith("CEREBRAS_API_KEY="):
                    api_key = line.split("=", 1)[1].strip('"\'')
                    break
    
    if not api_key:
        logger.error("No Cerebras API key found")
        return ""
    
    # Format tweets for analysis
    tweet_text = "\n\n".join([
        f"@{t.get('author', '?')}: {t.get('text', '')[:500]}"
        for t in tweets[:30]  # Limit to 30 tweets
    ])
    
    prompt = f"""Analyze these recent crypto/Solana tweets and extract the most important highlights.

Focus on:
1. New token launches or announcements
2. Technical updates to protocols (Raydium, Meteora, Pump.fun)
3. Market-moving news
4. Notable alpha or trading insights
5. Partnerships or integrations

Tweets:
{tweet_text}

Provide a concise summary (max 5 bullet points) of the most important/actionable information. 
Use emojis for visual appeal. Format for Telegram (markdown).
If nothing significant, say "No major highlights this hour."
"""

    try:
        resp = requests.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "zai-glm-4.7",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.3,
            },
            timeout=60,
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        else:
            logger.error(f"Cerebras API error: {resp.status_code} - {resp.text}")
            return ""
            
    except Exception as e:
        logger.error(f"Cerebras analysis failed: {e}")
        return ""


def send_to_telegram(message: str, chat_id: str = "-5223082150"):
    """Send message to Telegram group."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        # Try to get from OpenClaw config
        try:
            config_path = Path.home() / ".openclaw/openclaw.json"
            if config_path.exists():
                config = json.loads(config_path.read_text())
                bot_token = config.get("channels", {}).get("telegram", {}).get("token")
        except:
            pass
    
    if not bot_token:
        logger.error("No Telegram bot token found")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": f"🔍 **X Monitor Scan**\n_{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n\n{message}",
            "parse_mode": "Markdown",
        }, timeout=30)
        
        if resp.status_code == 200:
            logger.info("Successfully posted to Telegram")
            return True
        else:
            logger.error(f"Telegram API error: {resp.status_code} - {resp.text}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to send to Telegram: {e}")
        return False


def run_scan(force_post: bool = False):
    """Run a single scan cycle."""
    logger.info("Starting X monitor scan...")
    
    # Load state
    state = load_state()
    
    # Fetch tweets
    tweets = fetch_all_tweets()
    logger.info(f"Fetched {len(tweets)} total tweets")
    
    if not tweets:
        logger.warning("No tweets fetched")
        return
    
    # Deduplicate using hash
    new_tweets = []
    for tweet in tweets:
        tweet_hash = hashlib.md5(tweet.get("text", "")[:100].encode()).hexdigest()
        if tweet_hash not in state.get("seen_hashes", []):
            new_tweets.append(tweet)
            state.setdefault("seen_hashes", []).append(tweet_hash)
    
    # Keep only last 1000 hashes
    state["seen_hashes"] = state["seen_hashes"][-1000:]
    
    logger.info(f"Found {len(new_tweets)} new tweets")
    
    if not new_tweets and not force_post:
        logger.info("No new tweets, skipping analysis")
        state["last_scan"] = datetime.utcnow().isoformat()
        save_state(state)
        return
    
    # Analyze with Cerebras
    analysis = analyze_with_cerebras(new_tweets if new_tweets else tweets)
    
    if analysis and "No major highlights" not in analysis:
        # Post to Telegram
        send_to_telegram(analysis)
    else:
        logger.info("No significant highlights to post")
    
    # Save state
    state["last_scan"] = datetime.utcnow().isoformat()
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="X Monitor - Twitter monitoring with Cerebras")
    parser.add_argument("--once", action="store_true", help="Run single scan and exit")
    parser.add_argument("--interval", type=int, default=3600, help="Scan interval in seconds")
    parser.add_argument("--force", action="store_true", help="Force post even if no new tweets")
    args = parser.parse_args()
    
    if args.once:
        run_scan(force_post=args.force)
    else:
        logger.info(f"Starting X monitor service (interval: {args.interval}s)")
        while True:
            try:
                run_scan()
            except Exception as e:
                logger.error(f"Scan failed: {e}")
            
            logger.info(f"Sleeping for {args.interval}s...")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
