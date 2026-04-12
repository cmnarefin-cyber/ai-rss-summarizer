import feedparser
import requests
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict

# --- CONFIGURATION ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "llama3")
OUTPUT_DIR = "executive_digests"
MAX_WORKERS = 4  # Concurrency for LLM and feed fetching to speed up runtimes

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
            return "_Content too brief in RSS feed for deep analysis. Please refer directly to the source link._"

        prompt = f"""
        You are an elite Executive Communications Strategist. 
        Read the following article excerpt titled "{title}" and provide:
        1. A concise 2-sentence executive summary.
        2. 2-3 bullet points on strategic implications (impact on markets, technology, or policy).
        
        Format your response cleanly. Avoid introductory filler phrases.
        
        Article content:
        {text}
        """
        
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
        
        try:
            logger.info(f"Submitting to Ollama: '{title}'")
            response = requests.post(OLLAMA_URL, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "No summary generated.").strip()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout while generating summary for '{title}'.")
            return "_Error: LLM generation timed out. Ensure host hardware can keep up with concurrent requests._"
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama connection error for '{title}': {e}")
            return f"_Error connecting to local LLM: {e}_"
        except Exception as e:
            logger.error(f"Unexpected error formatting '{title}': {e}")
            return f"_Unexpected error: {e}_"

    def process_feed_entry(self, entry: feedparser.FeedParserDict) -> Dict[str, str]:
        """Processes a single RSS feed entry and returns the synthesized markdown object."""
        title = entry.get('title', 'Unknown Title')
        link = entry.get('link', '#')
        raw_summary = entry.get("summary", entry.get("description", ""))
        
        clean_text = self.get_text_from_html(raw_summary)
        ai_summary = self.summarize_with_ollama(clean_text, title)
        
        return {
            "title": title,
            "link": link,
            "synthesis": ai_summary
        }

    def process_feed(self, source_name: str, url: str) -> str:
        """Fetches and processes a single feed, returning its formatted markdown section."""
        logger.info(f"Fetching feed: {source_name}")
        feed = feedparser.parse(url)
        entries_to_process = feed.entries[:3]
        
        if not entries_to_process:
            logger.warning(f"No entries found for {source_name}")
            return f"## Source: {source_name}\n\n*No recent articles found in this feed.*\n\n"

        section_md = f"## Source: {source_name}\n\n"
        
        # We can process articles in this feed concurrently using ThreadPool
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_entry = {executor.submit(self.process_feed_entry, entry): entry for entry in entries_to_process}
            for future in as_completed(future_to_entry):
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.error(f"Article processing generated an exception: {exc}")

        # Construct markdown section safely
        for res in results:
            section_md += f"### [{res['title']}]({res['link']})\n"
            section_md += f"**Strategic Synthesis:**\n"
            section_md += f"{res['synthesis']}\n\n"
            section_md += "---\n\n"
            
        return section_md

    def generate_digest(self, feeds: Dict[str, str]) -> str:
        """Generates the full daily digest across all feeds robustly."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        output_file = os.path.join(self.output_dir, f"Executive_Strategic_Digest_{today_str}.md")
        
        logger.info(f"Starting AI Feed Summarization for {today_str}...")
        
        feed_sections = []
        # Run across multiple sources simultaneously to significantly cut down total script execution time
        with ThreadPoolExecutor(max_workers=len(feeds) if len(feeds) > 0 else 1) as executor:
            future_to_feed = {executor.submit(self.process_feed, name, url): name for name, url in feeds.items()}
            for future in as_completed(future_to_feed):
                try:
                    feed_sections.append(future.result())
                except Exception as exc:
                    name = future_to_feed[future]
                    logger.error(f"Feed {name} generated an exception: {exc}")
                    feed_sections.append(f"## Source: {name}\n\n*Failed to retrieve or process feed due to system error.*\n\n")
                    
        # Write consolidated digest
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Executive Strategic Digest: {today_str}\n\n")
            f.write("> **System Note:** Automated intelligence summary generated via local LLM (Ollama).\n\n")
            
            for section in feed_sections:
                f.write(section)
                
        logger.info(f"Optimization Complete! Digest saved to: {output_file}")
        return output_file

def main():
    summarizer = StrategicFeedSummarizer()
    summarizer.generate_digest(FEEDS)

if __name__ == "__main__":
    main()
