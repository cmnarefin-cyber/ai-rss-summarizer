import feedparser
import requests
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict
from dotenv import load_dotenv
import sqlite3

# Load secret variables (like Github Token and Webhooks)
load_dotenv()

# --- CONFIGURATION ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "llama3")
OUTPUT_DIR = "executive_digests"
MAX_WORKERS = 4 

# GitHub Integration Config
# Set GITHUB_TOKEN environment variable with the User Access Token from your OAuth App
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "cmnarefin-cyber/ai-rss-summarizer")

# Webhook Config for Make/Zapier Integration
AUTOMATION_WEBHOOK_URL = os.getenv("AUTOMATION_WEBHOOK_URL")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure professional enterprise logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Default RSS feeds
FEEDS = {
    "NREL Renewable News": "https://www.nrel.gov/news/feed/news-releases.xml",
    "Energy.gov News": "https://www.energy.gov/rss/255309",
    "Bloomberg Energy": "https://feeds.bloomberg.com/markets/news.rss"
}

class StrategicFeedSummarizer:
    def __init__(self, output_dir: str = OUTPUT_DIR):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
    @staticmethod
    def get_text_from_html(html_content: str) -> str:
        """Extracts plain text from HTML content cleanly."""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator=' ', strip=True)

    def summarize_with_ollama(self, text: str, title: str) -> str:
        """Generates an executive summary using the local Ollama LLM."""
        if len(text) < 50:
            return "_Content too brief in RSS feed for deep analysis._"

        prompt = f"""
        You are an elite Executive Communications Strategist. 
        Read the titled "{title}" and provide:
        1. A concise 2-sentence executive summary.
        2. 2-3 bullet points on strategic implications.
        
        Format your response cleanly.
        
        Article content:
        {text}
        """
        
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False}
        
        try:
            logger.info(f"Submitting to Ollama: '{title}'")
            response = requests.post(OLLAMA_URL, json=payload, timeout=120)
            response.raise_for_status()
            return response.json().get("response", "No summary generated.").strip()
        except Exception as e:
            logger.warning(f"Ollama offline for '{title}'. Falling back to Gemini API...")
            if not GEMINI_API_KEY:
                return f"_Synthesis failed. Ollama offline and no GEMINI_API_KEY provided._"
            
            gemini_payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                resp = requests.post(gemini_url, json=gemini_payload, headers={"Content-Type": "application/json"}, timeout=30)
                resp.raise_for_status()
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as ge:
                logger.error(f"Gemini fallback failed: {ge}")
                return f"_Synthesis failed entirely. Both local & cloud LLMs unavailable._"

    def post_to_github(self, content: str, title: str):
        """Posts the digest as a new GitHub Issue in the specified repository."""
        if not GITHUB_TOKEN:
            logger.warning("GITHUB_TOKEN not found. Skipping GitHub deployment.")
            return

        url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        data = {
            "title": title,
            "body": content
        }

        try:
            logger.info(f"Deploying digest to GitHub: {GITHUB_REPO}")
            response = requests.post(url, json=data, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully posted to GitHub! Issue URL: {response.json().get('html_url')}")
        except Exception as e:
            logger.error(f"Failed to post to GitHub: {e}")

    def log_to_database(self, title: str, url: str, synthesis: str):
        """Archives the digest locally into a SQLite database."""
        db_path = os.path.join(self.output_dir, 'ai_digests.db')
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS digests (id INTEGER PRIMARY KEY, date TEXT, title TEXT, url TEXT, synthesis TEXT)''')
            cursor.execute('INSERT INTO digests (date, title, url, synthesis) VALUES (?, ?, ?, ?)', 
                           (datetime.now().isoformat(), title, url, synthesis))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log to SQLite Database: {e}")

    def post_to_discord(self, title: str, feed_url: str, summary: str):
        """Pushes an alert to a Discord channel."""
        if not DISCORD_WEBHOOK_URL:
            return
        data = { "content": f"🚨 **New Intel Digest**: {title}\n*Source:* <{feed_url}>\n\n> {summary[:1500]}" }
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Discord Hook failed: {e}")

    def post_to_webhook(self, content: str, title: str):
        """Sends the digest to a Make.com or Zapier webhook."""
        if not AUTOMATION_WEBHOOK_URL:
            logger.warning("AUTOMATION_WEBHOOK_URL not found. Skipping webhook trigger.")
            return

        data = {
            "title": title,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        try:
            logger.info("Triggering automation webhook (n8n)...")
            response = requests.post(AUTOMATION_WEBHOOK_URL, json=data, timeout=15)
            response.raise_for_status()
            logger.info("Successfully triggered n8n webhook automation!")
        except Exception as e:
            logger.error(f"Failed to trigger webhook: {e}")

    def process_feed_entry(self, entry: feedparser.FeedParserDict) -> Dict[str, str]:
        title = entry.get('title', 'Unknown Title')
        link = entry.get('link', '#')
        raw_summary = entry.get("summary", entry.get("description", ""))
        clean_text = self.get_text_from_html(raw_summary)
        ai_summary = self.summarize_with_ollama(clean_text, title)
        
        # Log entry to local SQL database and Discord
        self.log_to_database(title, link, ai_summary)
        self.post_to_discord(title, link, ai_summary)
        
        return {"title": title, "link": link, "synthesis": ai_summary}

    def process_feed(self, source_name: str, url: str) -> str:
        logger.info(f"Fetching feed: {source_name}")
        feed = feedparser.parse(url)
        entries_to_process = feed.entries[:3]
        
        if not entries_to_process:
            return f"## Source: {source_name}\n\n*No recent articles found.*\n\n"

        section_md = f"## Source: {source_name}\n\n"
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_entry = {executor.submit(self.process_feed_entry, entry): entry for entry in entries_to_process}
            for future in as_completed(future_to_entry):
                try: results.append(future.result())
                except Exception as exc: logger.error(f"Error: {exc}")

        for res in results:
            section_md += f"### [{res['title']}]({res['link']})\n**Strategic Synthesis:**\n{res['synthesis']}\n\n---\n\n"
        return section_md

    def generate_digest(self, feeds: Dict[str, str]):
        today_str = datetime.now().strftime("%Y-%m-%d")
        title = f"Executive Strategic Digest: {today_str}"
        output_file = os.path.join(self.output_dir, f"Executive_Strategic_Digest_{today_str}.md")
        
        logger.info(f"Starting AI Feed Summarization for {today_str}...")
        
        feed_sections = []
        with ThreadPoolExecutor(max_workers=len(feeds) if feeds else 1) as executor:
            future_to_feed = {executor.submit(self.process_feed, name, url): name for name, url in feeds.items()}
            for future in as_completed(future_to_feed):
                try: feed_sections.append(future.result())
                except Exception as exc: logger.error(f"Error: {exc}")
                    
        consolidated_content = f"# {title}\n\n> Automated intelligence summary via Ollama.\n\n" + "".join(feed_sections)
        
        # Save local copy
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(consolidated_content)
        logger.info(f"Local digest saved to: {output_file}")
        
        # Deploy to GitHub
        self.post_to_github(consolidated_content, title)
        
        # Trigger n8n webhook automations
        self.post_to_webhook(consolidated_content, title)

def main():
    summarizer = StrategicFeedSummarizer()
    summarizer.generate_digest(FEEDS)

if __name__ == "__main__":
    main()
