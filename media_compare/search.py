import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import re
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import List
import newspaper

from .models import Article, ArticleSignals
from .sources import load_sources, detect_source, DEFAULT_UNKNOWN


def resolve_google_redirect(url: str) -> str:
    """Resolve Google News redirect URL to the original article publisher URL using googlenewsdecoder."""
    if "news.google.com" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            decoded = gnewsdecoder(url)
            if decoded.get("status"):
                return decoded.get("decoded_url")
        except Exception as e:
            print(f"googlenewsdecoder failed for {url}: {e}")
    return url


def fetch_article_data(url: str) -> tuple[str, str]:
    """Fetch article body text and top image URL using newspaper3k."""
    try:
        resolved_url = resolve_google_redirect(url)
        article = newspaper.Article(resolved_url, keep_article_html=False)
        article.download()
        article.parse()
        
        body = article.text.strip()
        image_url = article.top_image.strip() if article.top_image else ""
        
        return body, image_url
    except Exception as e:
        print(f"newspaper3k failed to parse {url}: {e}")
    return "", ""


def search_news(
    query: str,
    sources_config_path: Path,
    limit: int = 10,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    local_base_url: str | None = None,
) -> List[Article]:
    """Search Google News RSS for a query, scrape contents, and return Article list."""
    encoded_query = urllib.parse.quote(query)
    
    # Check if query contains Korean characters
    if re.search(r"[\uac00-\ud7a3]", query):
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    sources = load_sources(sources_config_path)
    articles: List[Article] = []
    
    try:
        response = requests.get(rss_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch RSS feed. Status code: {response.status_code}")
            return []
            
        root = ET.fromstring(response.content)
        items = root.findall(".//item")[:limit]
        
        for idx, item in enumerate(items):
            title = item.find("title").text if item.find("title") is not None else "No Title"
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source_el = item.find("source")
            xml_source_name = source_el.text if source_el is not None else ""
            
            if not link:
                continue
                
            # Clean title (sometimes Google News appends " - Publisher" to title)
            clean_title = title
            if xml_source_name and title.endswith(f" - {xml_source_name}"):
                clean_title = title[:-len(f" - {xml_source_name}")].strip()
            
            # Scrape content using newspaper3k
            print(f"[{idx+1}/{len(items)}] Fetching: {clean_title} ({link})")
            body, image_url = fetch_article_data(link)
            
            # Fallback to title and description if body scraping failed
            if not body:
                desc = item.find("description").text if item.find("description") is not None else ""
                clean_desc = BeautifulSoup(desc, "html.parser").get_text() if desc else ""
                body = f"{clean_title}\n\n{clean_desc}\n\n[Body content could not be retrieved]"
            
            # Identify source profile
            source_hint = f"{xml_source_name} {link}"
            source_profile = detect_source(
                source_hint,
                sources,
                config_path=sources_config_path,
                llm_provider=llm_provider,
                llm_model=llm_model,
                local_base_url=local_base_url,
            )
            
            # If the source is unknown, we dynamically create a temporary SourceProfile using xml_source_name
            if source_profile.name == DEFAULT_UNKNOWN.name and xml_source_name:
                # Normalize name
                source_profile = DEFAULT_UNKNOWN.__class__(
                    name=xml_source_name,
                    aliases=[xml_source_name.lower()],
                    trust=0.60, # Moderate default trust for detected online sources
                    reach=0.50, # Moderate default reach
                    bias="untracked",
                    notes="Dynamically detected online source."
                )
                
            # Date signal formatting (from RSS pubDate: e.g. "Wed, 08 Jul 2026 12:00:00 GMT")
            # Convert to YYYY-MM-DD
            # A simple regex to find the date pattern from RSS
            date_match = re.search(r"(\d{1,2})\s([a-zA-Z]{3})\s(\d{4})", pub_date)
            date_str = ""
            year_str = ""
            if date_match:
                day, month, year = date_match.groups()
                months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                          "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                month_num = months.get(month, "01")
                day_num = f"{int(day):02d}"
                date_str = f"{year}-{month_num}-{day_num}"
                year_str = year
                
            signals = ArticleSignals(
                dates=[date_str] if date_str else [],
                years=[year_str] if year_str else [],
                locations=[] # Will be filled by existing metadata/article extraction or LLM
            )
            
            # Build Article
            article = Article(
                article_id=f"online_{idx}",
                path=link, # Using link as Path placeholder
                source=source_profile,
                title=clean_title,
                body=body,
                image_url=image_url,
                metadata={
                    "url": link,
                    "date": date_str,
                    "publisher": xml_source_name
                },
                signals=signals
            )
            articles.append(article)
            
    except Exception as e:
        print(f"Error in search_news: {e}")
        
    return articles


def fetch_trending_news(
    sources_config_path: Path,
    limit: int = 15,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    local_base_url: str | None = None,
) -> List[Article]:
    """Retrieve top trending news headlines from News API, Brave News API, or fallback to Google News RSS Home."""
    import os
    
    news_api_key = os.environ.get("NEWS_API_KEY")
    brave_api_key = os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY")
    articles: List[Article] = []
    
    sources = load_sources(sources_config_path)
    
    # 1. Try News API
    if news_api_key:
        print("Fetching trending news from News API...")
        try:
            url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize={limit}&apiKey={news_api_key}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for idx, item in enumerate(data.get("articles", [])):
                    title = item.get("title", "")
                    link = item.get("url", "")
                    pub_date = item.get("publishedAt", "")
                    xml_source_name = item.get("source", {}).get("name", "")
                    image_url = item.get("urlToImage", "")
                    
                    if not link or not title:
                        continue
                        
                    body, scraped_img = fetch_article_data(link)
                    if not body:
                        body = item.get("description", "") or "[Body content could not be retrieved]"
                    if not image_url:
                        image_url = scraped_img
                        
                    # parse date
                    date_str = pub_date.split("T")[0] if "T" in pub_date else ""
                    year_str = date_str.split("-")[0] if "-" in date_str else ""
                    
                    source_hint = f"{xml_source_name} {link}"
                    source_profile = detect_source(
                        source_hint,
                        sources,
                        config_path=sources_config_path,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        local_base_url=local_base_url,
                    )
                    if source_profile.name == DEFAULT_UNKNOWN.name and xml_source_name:
                        source_profile = DEFAULT_UNKNOWN.__class__(
                            name=xml_source_name,
                            aliases=[xml_source_name.lower()],
                            trust=0.60,
                            reach=0.50,
                            bias="untracked",
                            notes="Dynamic News API source"
                        )
                        
                    articles.append(Article(
                        article_id=f"trending_news_{idx}",
                        path=link,
                        source=source_profile,
                        title=title,
                        body=body,
                        image_url=image_url,
                        metadata={"url": link, "date": date_str, "publisher": xml_source_name},
                        signals=ArticleSignals(dates=[date_str] if date_str else [], years=[year_str] if year_str else [])
                    ))
                if articles:
                    return articles
        except Exception as e:
            print(f"News API failed: {e}")
            
    # 2. Try Brave Search API (News Search)
    if brave_api_key:
        print("Fetching trending news from Brave News API...")
        try:
            url = "https://api.search.brave.com/res/v1/news/search?q=top+news&count=10"
            headers = {"Accept": "application/json", "X-Subscription-Token": brave_api_key}
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for idx, item in enumerate(data.get("results", [])):
                    title = item.get("title", "")
                    link = item.get("url", "")
                    xml_source_name = item.get("meta_url", {}).get("hostname", "")
                    thumbnail = item.get("thumbnail") or {}
                    image_url = thumbnail.get("src", "") if isinstance(thumbnail, dict) else str(thumbnail or "")
                    
                    if not link or not title:
                        continue
                        
                    body, scraped_img = fetch_article_data(link)
                    if not body:
                        body = item.get("description", "") or "[Body content could not be retrieved]"
                    if not image_url:
                        image_url = scraped_img
                        
                    source_hint = f"{xml_source_name} {link}"
                    source_profile = detect_source(
                        source_hint,
                        sources,
                        config_path=sources_config_path,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        local_base_url=local_base_url,
                    )
                    if source_profile.name == DEFAULT_UNKNOWN.name and xml_source_name:
                        source_profile = DEFAULT_UNKNOWN.__class__(
                            name=xml_source_name,
                            aliases=[xml_source_name.lower()],
                            trust=0.60,
                            reach=0.50,
                            bias="untracked",
                            notes="Dynamic Brave News source"
                        )
                        
                    articles.append(Article(
                        article_id=f"trending_brave_{idx}",
                        path=link,
                        source=source_profile,
                        title=title,
                        body=body,
                        image_url=image_url,
                        metadata={"url": link, "date": "", "publisher": xml_source_name},
                        signals=ArticleSignals()
                    ))
                if articles:
                    return articles
        except Exception as e:
            print(f"Brave News API failed: {e}")

    # 3. Fallback: Google News RSS default headlines (Global/US default)
    print("Falling back to Google News RSS headlines...")
    try:
        rss_url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(rss_url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall(".//item")[:limit]
            
            for idx, item in enumerate(items):
                title = item.find("title").text if item.find("title") is not None else "No Title"
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                source_el = item.find("source")
                xml_source_name = source_el.text if source_el is not None else ""
                
                if not link:
                    continue
                    
                clean_title = title
                if xml_source_name and title.endswith(f" - {xml_source_name}"):
                    clean_title = title[:-len(f" - {xml_source_name}")].strip()
                
                body, image_url = fetch_article_data(link)
                if not body:
                    desc = item.find("description").text if item.find("description") is not None else ""
                    clean_desc = BeautifulSoup(desc, "html.parser").get_text() if desc else ""
                    body = f"{clean_title}\n\n{clean_desc}\n\n[Body content could not be retrieved]"
                
                source_hint = f"{xml_source_name} {link}"
                source_profile = detect_source(
                    source_hint,
                    sources,
                    config_path=sources_config_path,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    local_base_url=local_base_url,
                )
                if source_profile.name == DEFAULT_UNKNOWN.name and xml_source_name:
                    source_profile = DEFAULT_UNKNOWN.__class__(
                        name=xml_source_name,
                        aliases=[xml_source_name.lower()],
                        trust=0.60,
                        reach=0.50,
                        bias="untracked",
                        notes="Dynamically detected online source."
                    )
                    
                date_match = re.search(r"(\d{1,2})\s([a-zA-Z]{3})\s(\d{4})", pub_date)
                date_str = ""
                year_str = ""
                if date_match:
                    day, month, year = date_match.groups()
                    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                              "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                    month_num = months.get(month, "01")
                    day_num = f"{int(day):02d}"
                    date_str = f"{year}-{month_num}-{day_num}"
                    year_str = year
                    
                articles.append(Article(
                    article_id=f"trending_rss_{idx}",
                    path=link,
                    source=source_profile,
                    title=clean_title,
                    body=body,
                    image_url=image_url,
                    metadata={"url": link, "date": date_str, "publisher": xml_source_name},
                    signals=ArticleSignals(dates=[date_str] if date_str else [], years=[year_str] if year_str else [])
                ))
    except Exception as e:
        print(f"Fallback RSS failed: {e}")
        
    return articles


def extract_trending_keywords_info(limit: int = 40, num_keywords: int = 10) -> dict:
    """Extract top trending multi-word keywords from live Google News RSS headlines."""
    import collections
    
    rss_url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    keywords: List[str] = []
    live = False
    fallback_reason = ""
    try:
        response = requests.get(rss_url, headers=headers, timeout=5)
        if response.status_code != 200:
            fallback_reason = f"Google News RSS returned HTTP {response.status_code}"
            response = None
        else:
            live = True

        titles_text = []
        if response is not None:
            root = ET.fromstring(response.content)
            items = root.findall(".//item")[:limit]

            for item in items:
                title = item.find("title").text if item.find("title") is not None else ""
                source_el = item.find("source")
                xml_source_name = source_el.text if source_el is not None else ""
                if xml_source_name and title.endswith(f" - {xml_source_name}"):
                    title = title[:-len(f" - {xml_source_name}")].strip()
                titles_text.append(title)
            
        # Extended stop words list
        stop_words = {
            "the", "and", "for", "are", "now", "was", "but", "not", "its", "has", "have", "had", 
            "you", "out", "our", "one", "two", "who", "why", "all", "itself", "him", "her", "his", 
            "can", "get", "got", "say", "saying", "does", "did", "been", "being", "what", "than", 
            "that", "this", "then", "them", "their", "there", "these", "those", "any", "how", "why",
            "live", "updates", "says", "after", "with", "about", "over", "into", "more", "first", 
            "from", "will", "show", "watch", "could", "should", "would", "about", "were", "when", 
            "where", "your", "news", "world", "today", "deal", "new", "warns", "dead", "killing", 
            "struck", "strike", "dies", "attack", "plane", "missing", "forces", "biden", "trump", 
            "harris", "election", "campaign", "court", "ruling", "judge", "state", "police", "officer", 
            "people", "against", "aftermath", "near", "during", "briefing", "press", "claims", 
            "called", "calls", "amid", "chief", "after", "here", "time", "health", "lives", "report",
            "reports", "back", "says", "make", "made", "some", "most", "just", "into", "onto", "under", "over"
        }
        
        bigrams = []
        unigrams = []
        
        for title in titles_text:
            # Remove punctuation except spaces
            clean_title = re.sub(r"[^\w\s-]", "", title)
            words = clean_title.split()
            
            # 1. Extract Bigrams (adjacent clean pairs)
            for i in range(len(words) - 1):
                w1 = words[i]
                w2 = words[i+1]
                w1_low = w1.lower()
                w2_low = w2.lower()
                
                if w1_low in stop_words or w2_low in stop_words:
                    continue
                if len(w1) < 3 or len(w2) < 3:
                    continue
                
                # Check capitalization for proper casing
                is_w1_cap = w1[0].isupper() if w1 else False
                is_w2_cap = w2[0].isupper() if w2 else False
                
                if is_w1_cap and is_w2_cap:
                    phrase = f"{w1} {w2}"
                else:
                    phrase = f"{w1.capitalize()} {w2.capitalize()}"
                    
                bigrams.append(phrase)
                
            # 2. Extract Unigrams (clean single words) for fallback
            for w in words:
                w_low = w.lower()
                if w_low not in stop_words and len(w) >= 3:
                    unigrams.append(w.capitalize())
                    
        # Score Bigrams
        bigram_counter = collections.Counter(bigrams)
        most_common_bigrams = bigram_counter.most_common(num_keywords * 2)
        
        for phrase, count in most_common_bigrams:
            # Skip if we already have a subset of this concept or duplicate
            if phrase not in keywords:
                keywords.append(phrase)
            if len(keywords) >= num_keywords:
                break
                
        # Fallback to Unigrams if bigrams are scarce
        if len(keywords) < num_keywords:
            unigram_counter = collections.Counter(unigrams)
            for word, count in unigram_counter.most_common(num_keywords):
                # Avoid inserting a unigram that is already part of an existing bigram
                is_duplicate = False
                for kw in keywords:
                    if word in kw:
                        is_duplicate = True
                        break
                if not is_duplicate and word not in keywords:
                    keywords.append(word)
                if len(keywords) >= num_keywords:
                    break
                    
    except Exception as e:
        fallback_reason = str(e)
        print(f"Error extracting keywords: {e}")
        
    if not keywords:
        keywords = ["NATO Summit", "Iran Conflict", "US Election", "Climate Crisis", "Tech Policy", "Global Economy", "Ceasefire Deal", "Cargo Plane", "Space Exploration", "Stock Market"]
        live = False
        
    return {
        "keywords": keywords[:num_keywords],
        "source": "Google News RSS",
        "live": live,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fallback_reason": fallback_reason,
    }


def extract_trending_keywords(limit: int = 40, num_keywords: int = 10) -> List[str]:
    """Backward-compatible keyword-only wrapper."""
    return extract_trending_keywords_info(limit=limit, num_keywords=num_keywords)["keywords"]
