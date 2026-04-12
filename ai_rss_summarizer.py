import feedparser
import requests
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3" # You can change this to mistral or whatever you have installed
OUTPUT_DIR = "executive_digests"

# Default RSS feeds (focused on energy, finance, and general news)
FEEDS = {
    "NREL Renewable News": "https://www.nrel.gov/news/feed/news-releases.xml",
    "Energy.gov News": "https://www.energy.gov/rss/255309",
    "Bloomberg Energy": "https://feeds.bloomberg.com/markets/news.rss" # Note: example feed
}

def get_text_from_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=' ', strip=True)

def summarize_with_ollama(text, title):
    prompt = f"""
    You are an elite Executive Communications Strategist. 
    Please read the following article excerpt/summary titled "{title}" and provide:
    1. A concise 2-sentence executive summary.
    2. 2-3 bullet points on strategic implications (if applicable to markets or technology).
    
    Article content:
    {text}
    """
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "No summary generated.")
    except requests.exceptions.RequestException as e:
        return f"Error connecting to Ollama: {e}. Please ensure Ollama is running and the model {MODEL_NAME} is installed."
    except Exception as e:
        return f"Unexpected error: {e}"

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_file = os.path.join(OUTPUT_DIR, f"Executive_Strategic_Digest_{today_str}.md")
    
    print(f"[*] Starting AI Feed Summarization for {today_str}...")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# Executive Strategic Digest: {today_str}\n\n")
        f.write("> **System Note:** Automated intelligence summary generated via local LLM (Ollama).\n\n")
        
        for source, url in FEEDS.items():
            print(f"[*] Fetching feeds from {source}...")
            f.write(f"## Source: {source}\n\n")
            
            feed = feedparser.parse(url)
            
            # Limit to top 3 articles per feed for speed
            for entry in feed.entries[:3]:
                title = entry.title
                link = entry.link
                raw_summary = entry.get("summary", entry.get("description", ""))
                
                clean_text = get_text_from_html(raw_summary)
                
                # If the summary is too short, we might not get a great result, but we'll try
                if len(clean_text) < 50:
                    clean_text = "Content too brief in RSS feed for deep analysis. Source link provided."
                
                print(f"    - Processing: {title}")
                ai_summary = summarize_with_ollama(clean_text, title)
                
                f.write(f"### [{title}]({link})\n")
                f.write(f"**AI Synthesis:**\n")
                f.write(f"{ai_summary}\n\n")
                f.write("---\n\n")

    print(f"\n[+] Optimization Complete! Digest saved to: {output_file}")

if __name__ == "__main__":
    main()
