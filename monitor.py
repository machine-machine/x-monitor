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
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Target accounts to monitor
TARGET_ACCOUNTS = [
    "Pumpfun",          # Official pump.fun (verified)
    "Raydium",          # Raydium DEX (not RaydiumProtocol)
    "MeteoraAG",        # Meteora DEX
    "MarioNawfal",      # Crypto news
    "RohOnChain",       # DeFi/trading insights
    "xDaily",           # xAI news
    "JupiterExchange",  # Jupiter aggregator
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


def fetch_via_rss_bridge(account: str) -> list[dict]:
    """Try RSS-Bridge instances for X feeds."""
    tweets = []
    
    # Public RSS-Bridge instances
    bridges = [
        f"https://rss-bridge.org/bridge01/?action=display&bridge=TwitterBridge&context=By+username&u={account}&format=Atom",
    ]
    
    for url in bridges:
        try:
            resp = requests.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DEXY-Monitor/1.0)"
            })
            
            if resp.status_code == 200 and '<entry>' in resp.text:
                import xml.etree.ElementTree as ET
                
                # Parse Atom feed
                root = ET.fromstring(resp.text)
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                
                for entry in root.findall('.//atom:entry', ns)[:10]:
                    title = entry.find('atom:title', ns)
                    link = entry.find('atom:link', ns)
                    content = entry.find('atom:content', ns)
                    published = entry.find('atom:published', ns)
                    
                    text = ""
                    if content is not None and content.text:
                        import re
                        text = re.sub(r'<[^>]+>', '', content.text).strip()
                    elif title is not None and title.text:
                        text = title.text
                    
                    if text and len(text) > 20:
                        tweets.append({
                            "author": f"@{account}",
                            "text": text[:1000],
                            "url": link.get('href') if link is not None else "",
                            "timestamp": published.text if published is not None else "",
                        })
                
                if tweets:
                    logger.info(f"Fetched {len(tweets)} tweets from @{account} via RSS-Bridge")
                    return tweets
                    
        except Exception as e:
            logger.debug(f"RSS-Bridge failed for @{account}: {e}")
            continue
    
    return tweets


def fetch_via_nitter(account: str) -> list[dict]:
    """Fetch tweets via Nitter instances."""
    tweets = []
    
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]
    
    for instance in nitter_instances:
        try:
            url = f"{instance}/{account}/rss"
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DEXY-Monitor/1.0)"
            })
            
            if resp.status_code == 200 and '<item>' in resp.text:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                
                for item in root.findall(".//item")[:10]:
                    title = item.find("title")
                    link = item.find("link")
                    description = item.find("description")
                    pub_date = item.find("pubDate")
                    
                    text = ""
                    if description is not None and description.text:
                        import re
                        text = re.sub(r'<[^>]+>', '', description.text).strip()
                    elif title is not None and title.text:
                        text = title.text
                    
                    if text and len(text) > 20:
                        tweets.append({
                            "author": f"@{account}",
                            "text": text[:1000],
                            "url": link.text if link is not None else "",
                            "timestamp": pub_date.text if pub_date is not None else "",
                        })
                
                if tweets:
                    logger.info(f"Fetched {len(tweets)} tweets from @{account} via Nitter")
                    return tweets
                    
        except Exception as e:
            logger.debug(f"Nitter failed for @{account}: {e}")
            continue
    
    return tweets


def fetch_via_twstalker(account: str) -> list[dict]:
    """Fetch tweets via twstalker.com (X viewer)."""
    tweets = []
    
    try:
        url = f"https://twstalker.com/{account}"
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
        })
        
        if resp.status_code == 200:
            import re
            
            # Extract tweet content from twstalker HTML
            tweet_pattern = re.compile(
                r'<div[^>]*class="[^"]*tweet-content[^"]*"[^>]*>(.*?)</div>',
                re.DOTALL | re.IGNORECASE
            )
            
            for match in tweet_pattern.finditer(resp.text)[:10]:
                text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                if text and len(text) > 20:
                    tweets.append({
                        "author": f"@{account}",
                        "text": text[:1000],
                        "url": f"https://x.com/{account}",
                    })
            
            if tweets:
                logger.info(f"Fetched {len(tweets)} tweets from @{account} via twstalker")
                return tweets
                
    except Exception as e:
        logger.debug(f"Twstalker failed for @{account}: {e}")
    
    return tweets


def fetch_all_tweets() -> list[dict]:
    """Fetch tweets from all target accounts using multiple methods."""
    all_tweets = []
    
    for account in TARGET_ACCOUNTS:
        tweets = []
        
        # Try methods in order of reliability
        for fetch_method in [fetch_via_rss_bridge, fetch_via_nitter, fetch_via_twstalker]:
            tweets = fetch_method(account)
            if tweets:
                break
        
        if tweets:
            all_tweets.extend(tweets)
        else:
            logger.warning(f"Could not fetch tweets for @{account}")
        
        time.sleep(2)  # Rate limiting
    
    return all_tweets


def analyze_with_cerebras(tweets: list[dict]) -> str:
    """Send tweets to Cerebras for highlight extraction."""
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
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
        f"{t.get('author', '?')}: {t.get('text', '')}"
        for t in tweets[:20]
    ])
    
    if len(tweet_text) < 100:
        logger.warning("Not enough tweet content to analyze")
        return "No major highlights this hour."
    
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
                "model": "llama-3.3-70b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.3,
            },
            timeout=60,
        )
        
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning") or ""
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
            "text": f"🔍 *X Monitor Scan*\n_{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n\n{message}",
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
    
    state = load_state()
    tweets = fetch_all_tweets()
    logger.info(f"Fetched {len(tweets)} total tweets")
    
    if not tweets:
        logger.warning("No tweets fetched from any source")
        return
    
    # Deduplicate
    new_tweets = []
    for tweet in tweets:
        tweet_hash = hashlib.md5(tweet.get("text", "")[:100].encode()).hexdigest()
        if tweet_hash not in state.get("seen_hashes", []):
            new_tweets.append(tweet)
            state.setdefault("seen_hashes", []).append(tweet_hash)
    
    state["seen_hashes"] = state["seen_hashes"][-500:]
    logger.info(f"Found {len(new_tweets)} new tweets")
    
    if not new_tweets and not force_post:
        logger.info("No new tweets, skipping analysis")
        state["last_scan"] = datetime.utcnow().isoformat()
        save_state(state)
        return
    
    # Analyze with Cerebras
    analysis = analyze_with_cerebras(new_tweets if new_tweets else tweets)
    logger.info(f"Analysis result: {analysis[:200] if analysis else 'EMPTY'}...")
    
    if analysis and "No major highlights" not in analysis and len(analysis) > 50:
        send_to_telegram(analysis)
    else:
        logger.info("No significant highlights to post")
    
    state["last_scan"] = datetime.utcnow().isoformat()
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="X Monitor")
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
