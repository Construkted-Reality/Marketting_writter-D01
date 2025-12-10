#!/usr/bin/env python3
# File: cr_content_pipeline-02.py
# --------------------------------------------------------------
# Construkted Content Pipeline – Insights & Blog‑Post Generator
# --------------------------------------------------------------
# Usage:
#   python cr_content_pipeline.py --topic "remote work productivity" \
#       [--max-posts 15] [--verbose] [--gr-verbose] [--insights-only] [--posts-dir custom_folder]
#   python cr_content_pipeline.py --insights-input insights.json \
#       [--topic "dummy"] [--verbose] [--posts-dir custom_folder]
#
# The script:
#   1. Loads .env variables (API keys, endpoints, etc.).
#   2. Generates structured insights via GPT‑Researcher.
#   3. Enriches each insight's source_urls with URLs from GPT-Researcher's research and content extraction.
#   4. For each insight, generates a blog‑post draft.
#   5. Writes insights to insights.json and each blog post as a markdown file in the posts/ subdirectory (default: "posts/topic-{topic}" where spaces are replaced with underscores, or "posts/" if no topic).
#
# Source URL Enrichment:
#   - Attempts to call researcher.get_source_urls() and researcher.get_research_sources() (collected for reference)
#   - Extracts URLs from each insight's content using regex
#   - Merges existing URLs + content URLs only (no global research URL merge)
#   - Normalizes and deduplicates all URLs found
#   - Fails gracefully if GPT-Researcher methods are unavailable
# --------------------------------------------------------------
 
import argparse
import asyncio
import ast
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
import re
import hashlib
from datetime import datetime
from typing import Dict, Optional, List
from dotenv import load_dotenv
from gpt_researcher import GPTResearcher
from openai import OpenAI
 
 
@dataclass
class InsightObject:
    """Data class representing a simplified insight with title, content, source URLs, and blog post data."""
    title: str = ""
    content: str = ""
    source_urls: List[str] = field(default_factory=list)
    id: str = ""  # Optional post ID generated from title
    blog_post_content: str = ""  # Full blog post content when generated
    used: bool = False  # Flag indicating if blog post has been generated
 
def load_prompt_template(template_name: str, **kwargs) -> str:
    """Load a prompt template from the prompts directory and format it with provided variables.
    Uses brace-safe formatting to avoid conflicts with JSON braces in templates."""
    template_path = Path("llm_guidance") / f"{template_name}.md"
    try:
        template_content = template_path.read_text(encoding="utf-8")
        
        # Brace-safe formatting: only replace known placeholders
        for key, value in kwargs.items():
            placeholder = "{" + key + "}"
            template_content = template_content.replace(placeholder, str(value))
        
        return template_content
    except Exception as e:
        sys.stderr.write(f"Error loading prompt template {template_name}: {e}\n")
        sys.exit(1)

# Voice definitions (mirroring the associative array in the Bash script)
VOICE_DEFINITIONS: Dict[str, str] = {
    "TheNewYorker": (
        "New Yorker "
        "- Tone: sophisticated, witty, introspective, and conversational, yet authoritative. "
        "- Rhythm: mix short, punchy sentences with longer, meandering ones; allow occasional asides and minor tangents. "
        "- Style: sprinkle in idioms, slang, and light‑hearted rhetorical questions (e.g., “Who hasn’t…?”) to keep it authentic. "
        "- Personality: let the narrator’s sharp curiosity and dry humor shine through; don’t be afraid of a subtle imperfection or a fleeting digression. "
        "- Purpose: inform, entertain, and provoke thought—think of a column that educates while it delights and challenges the reader."
    ),
    "TheAtlantic": (
        "The Atlantic "
        "- Personality: Thought‑provoking, long‑form, measured, policy‑savvy. "
        "- Signature tricks: Structured arguments, data‑driven evidence, historical context, calm but persuasive tone, minimal slang. "
        "- Prompt cheat‑sheet: Write in the voice of an Atlantic columnist: analytical, well‑researched, balanced, with a calm persuasive tone and ample historical context."
    ),
    "Wired": (
        "Wired "
        "- Personality: Futurist, tech‑obsessed, fast‑paced, jargon‑light. "
        "- Signature tricks: Short, punchy sentences; use of bold tech metaphors ('the internet is a nervous system'); occasional emojis or meme references (when appropriate); 'what‑it‑means‑for‑you' framing. "
        "- Prompt cheat‑sheet: Write like a Wired feature: tech‑forward, fast‑paced, with vivid metaphors and a ‘what it means for the reader’ angle."
    ),
}

# ----------------------------------------------------------------------
# Helper – Load environment & ensure required variables are present
# ----------------------------------------------------------------------
def load_environment() -> None:
    """Load .env and validate critical variables."""
    load_dotenv()
    # Validate OpenAI base URL – required for the vLLM server
    openai_api_base = os.getenv("OPENAI_API_BASE")
    if not openai_api_base:
        raise ValueError("OPENAI_API_BASE environment variable is not set.")
    os.environ["OPENAI_API_BASE"] = openai_api_base
 
    # Set a reliable retriever to avoid SearXNG timeouts.
    # Default to Tavily (commercial) with MCP fallback; this works even if
    # the SearXNG instance is unreachable.
    #os.environ["RETRIEVER"] = "tavily,mcp"
 
    # Validate model name – required for the vLLM server
    openai_model_name = os.getenv("OPENAI_MODEL_NAME")
    if not openai_model_name:
        raise ValueError("OPENAI_MODEL_NAME environment variable is not set.")
    os.environ["OPENAI_MODEL_NAME"] = openai_model_name
 
    # Provide a dummy key if the downstream server does not need it
    os.environ["OPENAI_API_KEY"] = os.getenv(
        "OPENAI_API_KEY", "sk-dummy-key-if-not-needed"
    )
 
def slugify(text: str) -> str:
    """
    Convert a string to a safe filename slug.
    - Lower‑case
    - Replace non‑alphanumeric characters with underscores
    - Collapse multiple underscores
    - Strip leading/trailing underscores
    """
    import re
 
    # Replace any character that is not a letter, number, or underscore with underscore
    slug = re.sub(r"[^\w]+", "_", text.lower())
    # Collapse consecutive underscores
    slug = re.sub(r"_+", "_", slug)
    # Remove leading/trailing underscores
    slug = slug.strip("_")
    return slug

# ----------------------------------------------------------------------
# URL normalization and extraction utilities
# ----------------------------------------------------------------------

def is_http_url(url: str) -> bool:
    """Check if URL is a valid HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    return url.strip().lower().startswith(('http://', 'https://'))

def normalize_url(url: str) -> str:
    """Normalize URL by stripping whitespace and trailing punctuation."""
    if not url or not isinstance(url, str):
        return ""
    # Strip whitespace
    url = url.strip()
    # Strip common trailing punctuation that might be part of sentence structure
    url = url.rstrip('.,);:\'"')
    return url

def extract_urls_from_text(text: str) -> list[str]:
    """Extract HTTP/HTTPS URLs from text using regex."""
    if not text or not isinstance(text, str):
        return []
    import re
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return [normalize_url(url) for url in urls if is_http_url(normalize_url(url))]

def unique_ordered(iterable) -> list:
    """Return unique items preserving first-seen order."""
    seen = set()
    result = []
    for item in iterable:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
 
def load_insights_from_file(file_path: Path) -> list[InsightObject]:
    """
    Load structured insights from a JSON file.
    
    Args:
        file_path: Path to JSON file containing insights
        
    Returns:
        List of InsightObject instances
        
    Raises:
        ValueError: If file format is invalid or required fields are missing
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            raise ValueError("JSON file must contain a list of insights")
        
        insights = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"Insight {idx+1}: must be a dictionary")
            
            # Validate required fields
            required_fields = ["title", "content", "source_urls"]
            for field in required_fields:
                if field not in item:
                    raise ValueError(f"Insight {idx+1}: missing required field '{field}'")
                if field == "source_urls":
                    if not isinstance(item[field], list):
                        raise ValueError(f"Insight {idx+1}: field '{field}' must be a list of strings")
                    if not all(isinstance(src, str) for src in item[field]):
                        raise ValueError(f"Insight {idx+1}: all source_urls entries must be strings")
                else:
                    if not isinstance(item[field], str):
                        raise ValueError(f"Insight {idx+1}: field '{field}' must be a string")
            
            # Create InsightObject
            insight_obj = InsightObject(
                title=item["title"],
                content=item["content"],
                source_urls=item["source_urls"],
                id=item.get("id", ""),  # Optional id field
                blog_post_content=item.get("blog_post_content", ""),  # Optional blog post content
                used=item.get("used", False)  # Optional used flag
            )
            insights.append(insight_obj)
        
        return insights
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in {file_path}: {e}")
    except FileNotFoundError:
        raise ValueError(f"Insights file not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error loading insights from {file_path}: {e}")
 
# ----------------------------------------------------------------------
# Post ID generation utilities
# ----------------------------------------------------------------------

def encode_base62(data: bytes) -> str:
    """
    Encode bytes to base62 string (0-9, a-z, A-Z).
    
    Args:
        data: Bytes to encode
        
    Returns:
        Base62 encoded string
    """
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    
    # Convert bytes to integer
    num = int.from_bytes(data, byteorder='big')
    
    if num == 0:
        return alphabet[0]
    
    result = []
    while num > 0:
        num, remainder = divmod(num, 62)
        result.append(alphabet[remainder])
    
    return ''.join(reversed(result))

def make_post_id(seed: str, desired_len: int = 5) -> str:
    """
    Generate a deterministic post ID from seed data.
    
    Args:
        seed: Seed string (typically the insight title)
        desired_len: Desired length of ID (default 5)
        
    Returns:
        Base62 encoded ID of specified length
    """
    # Create SHA-256 hash of seed
    hash_obj = hashlib.sha256(seed.encode('utf-8'))
    hash_bytes = hash_obj.digest()
    
    # Encode to base62 and take first N characters
    base62_str = encode_base62(hash_bytes)
    return base62_str[:desired_len]

def generate_ids_for_insights(insights: list[InsightObject], verbose: bool = False) -> None:
    """
    Generate unique IDs for insights based on titles within the current run only.
    Modifies insights in-place to add IDs.
    
    Args:
        insights: List of InsightObject instances to generate IDs for
        verbose: If True, prints progress information
    """
    # Set desired ID length to 5
    desired_len = 5
    
    # Generate IDs for insights that don't have them (only avoid collisions within current run)
    used_ids = set()
    
    for insight in insights:
        if insight.id:  # Skip if already has an ID
            used_ids.add(insight.id)
            continue
            
        # Generate ID from title only
        title_seed = insight.title
        
        # Try different ID lengths to avoid collisions within current run
        for id_len in range(desired_len, min(desired_len + 6, 11)):  # Try up to 10 chars
            post_id = make_post_id(title_seed, id_len)
            
            if post_id not in used_ids:
                # New unique ID within current run
                insight.id = post_id
                used_ids.add(post_id)
                if verbose:
                    logging.debug(f"📝 Generated ID '{post_id}' for '{insight.title[:50]}...'")
                break
        else:
            # If we get here, we need to use a counter suffix (extremely unlikely)
            base_id = make_post_id(title_seed, desired_len)
            counter = 1
            while True:
                post_id = f"{base_id}{encode_base62(counter.to_bytes(2, 'big'))[:2]}"
                if post_id not in used_ids:
                    insight.id = post_id
                    used_ids.add(post_id)
                    if verbose:
                        logging.debug(f"📝 Generated collision-resolved ID '{post_id}' for '{insight.title[:50]}...'")
                    break
                
                counter += 1
                if counter > 999:  # Safety limit
                    raise RuntimeError(f"Unable to generate unique ID for title: {insight.title}")

def write_post_strategy(decisions_dir: str, insight: InsightObject, decisions_data: dict, verbose: bool = False):
    """Write marketing decisions to individual JSON file per blog post. Requires POST_ID to be set."""
    logging.info(f"📝 [write_post_strategy] Starting to write marketing decisions...")
    logging.debug(f"📝 [write_post_strategy] Parameters: decisions_dir={decisions_dir}, insight.title={insight.title if insight else 'None'}, insight.id={insight.id if insight else 'None'}")
    
    try:
        # Validate parameters
        if not decisions_dir:
            raise ValueError("decisions_dir parameter is empty or None")
        if not insight:
            raise ValueError("insight parameter is None")
        if not decisions_data:
            raise ValueError("decisions_data parameter is empty or None")
        
        logging.debug(f"📝 [write_post_strategy] Parameter validation passed")
        
        decisions_dir_path = Path(decisions_dir)
        logging.debug(f"📝 [write_post_strategy] decisions_dir_path created: {decisions_dir_path}")
        
        title = insight.title
        source_urls = insight.source_urls
        post_id = insight.id
        
        if not post_id:
            raise ValueError(f"insight.id is empty for insight with title: {title}")
        
        logging.debug(f"📝 [write_post_strategy] Extracted: post_id={post_id}, title={title[:50]}...")
        
        # Use hybrid filename with post ID
        filename = make_hybrid_filename(post_id, title, "-decisions.json")
        logging.debug(f"📝 [write_post_strategy] Generated filename: {filename}")
        
        individual_decisions_file = decisions_dir_path / filename
        logging.debug(f"📝 [write_post_strategy] Full file path: {individual_decisions_file}")
        
        # Create new record
        new_record = {
            "title": title,
            "decisions": decisions_data,
            "source_urls": source_urls,
            "timestamp": datetime.now().isoformat()
        }
        logging.debug(f"📝 [write_post_strategy] Created record with {len(decisions_data)} decision fields")
        
        # Write individual decision file for this blog post
        logging.debug(f"📝 [write_post_strategy] Creating directory: {decisions_dir_path}")
        decisions_dir_path.mkdir(parents=True, exist_ok=True)
        logging.debug(f"📝 [write_post_strategy] Directory created/verified")
        
        logging.debug(f"📝 [write_post_strategy] Opening file for writing: {individual_decisions_file}")
        with individual_decisions_file.open('w', encoding='utf-8') as f:
            json.dump(new_record, f, indent=2, ensure_ascii=False)
        logging.debug(f"📝 [write_post_strategy] JSON data written to file")
        
        logging.info(f"✅ [write_post_strategy] Marketing decisions written to {individual_decisions_file.resolve()}")
        if verbose:
            print(f"✅ Marketing decisions written to {individual_decisions_file.resolve()}")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ [write_post_strategy] FAILED to write marketing decisions: {type(e).__name__}: {e}")
        logging.error(f"❌ [write_post_strategy] Stack trace:", exc_info=True)
        raise

# ----------------------------------------------------------------------
# Helper – Voice selection for rewrite (LLM-based)
# ----------------------------------------------------------------------
async def select_post_strategy(insight: InsightObject, draft_md: str, posts_dir: Path, verbose: bool = False) -> tuple[str, dict]:
    """
    Use local LLM to suggest the most appropriate voice for blog post rewrite.
    Also collects comprehensive marketing metadata.
    
    Args:
        insight: The InsightObject containing title, content, and metadata
        draft_md: The generated blog post markdown (optional)
        posts_dir: Directory path where decisions should be saved (optional)
        verbose: If True, prints progress information
        
    Returns:
        Tuple of (voice_key, decisions_metadata) where voice_key is "Wired", "TheAtlantic", or "TheNewYorker"
    """
    logging.debug(f"🎭 [select_post_strategy] Starting voice selection for: {insight.title[:50]}...")
    # Create OpenAI client using the configured vLLM endpoint
    from openai import OpenAI as OpenAIClient
    client = OpenAIClient(
        api_key=os.getenv("OPENAI_API_KEY", "sk-dummy-key-if-not-needed"),
        base_url=os.getenv("OPENAI_API_BASE")
    )
    
     # Build detailed voice definitions from VOICE_DEFINITIONS dict
    detailed_voice_definitions = "\n\n".join(
        f"{name}: {desc}" for name, desc in VOICE_DEFINITIONS.items()
    )
    
    # Load system prompt template with detailed voice definitions
    system_prompt = load_prompt_template(
        "03-post_strategy_selection_system_prompt",
        detailed_voice_definitions=detailed_voice_definitions,
    )
    # Load user prompt template with detailed voice definitions
    user_prompt = load_prompt_template(
        "03-post_strategy_selection_user_prompt",
        draft_md=draft_md,
    )

    if verbose:
        print("🤖 Using LLM to select voice and collect marketing metadata...")
    
    selected_voice = "TheNewYorker"  # Default fallback
    decisions_data = None
    
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=os.getenv("OPENAI_MODEL_NAME", "none"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=8192
        )
        
        decisions_output = response.choices[0].message.content
        if decisions_output is None:
            raise ValueError("Empty response from LLM")
        
        decisions_output = decisions_output.strip()
        
        # Parse JSON response
        try:
            decisions_data = json.loads(decisions_output)
            
            # Validate and extract voice
            voice = decisions_data.get("voice", "").strip()
            valid_voices = ["Wired", "TheAtlantic", "TheNewYorker"]
            if voice in valid_voices:
                selected_voice = voice
                if verbose:
                    print(f"🤖 LLM selected voice: {selected_voice}")
            else:
                if verbose:
                    print(f"⚠️ LLM returned invalid voice '{voice}', using fallback")
            
            # Validate other fields and normalize
            decisions_data = normalize_post_strategy_decisions(decisions_data, verbose)
                
        except json.JSONDecodeError as e:
            if verbose:
                print(f"⚠️ Failed to parse LLM marketing decisions JSON: {e}")
            decisions_data = None
          
    except Exception as e:
        if verbose:
            print(f"⚠️ LLM marketing decisions failed: {e}")
        decisions_data = None
    
    # Ensure voice is included in the decisions metadata before returning
    final_decisions = decisions_data or {}
    final_decisions["voice"] = selected_voice

    # Write marketing decisions to file if posts_dir is provided
    if posts_dir:
        try:
            logging.debug(f"🎭 [select_post_strategy] Attempting to write decisions to: {posts_dir}")
            write_post_strategy(str(posts_dir), insight, final_decisions, verbose)
            logging.info(f"✅ [select_post_strategy] Successfully wrote marketing decisions")
        except Exception as e:
            logging.error(f"❌ [select_post_strategy] Failed to write marketing decisions: {type(e).__name__}: {e}")
            logging.error(f"❌ [select_post_strategy] Stack trace:", exc_info=True)
            if verbose:
                print(f"⚠️ Failed to write marketing decisions: {e}")
    else:
        logging.warning(f"⚠️ [select_post_strategy] posts_dir not provided, skipping decision file write")
    
    return selected_voice, final_decisions

async def generate_blog_structure_outline(decision_metadata: str) -> str:
    """
    Use local LLM to suggest the most appropriate structure for the blog post
    
    Args:
        decision_metadata: The decision metadata containing marketing decisions
        
    Returns:
        String containing the structure outline headings
    """
    logging.info(f"🎭 [generate_blog_structure_outline] Starting outline generation")
    # Create OpenAI client using the configured vLLM endpoint
    from openai import OpenAI as OpenAIClient
    client = OpenAIClient(
        api_key=os.getenv("OPENAI_API_KEY", "sk-dummy-key-if-not-needed"),
        base_url=os.getenv("OPENAI_API_BASE")
    )

    # Load system prompt template with instruction on what to do
    system_prompt = load_prompt_template(
        "03.5-structure_extract_prompt",
    )
    # Load user prompt template with blog post
    user_prompt = "Metadata provided. Use this information to make the decision.\n " + json.dumps(decision_metadata, indent=2)

    # Initialize with default value
    structure_outline = ""

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=os.getenv("OPENAI_MODEL_NAME", "none"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=8192
        )

        structure_outline = response.choices[0].message.content
        if structure_outline is None:
            raise ValueError("Empty response from LLM")
        
        structure_outline = structure_outline.strip()

        logging.info(f"🎭 [generate_blog_structure_outline] Outline generated successfully \n {structure_outline} \n")

    except Exception as e:
        logging.error(f"⚠️ LLM structure outline generation failed: {e}")
        print(f"⚠️ LLM structure outline generation failed: {e}")
        # Return empty string as fallback
        structure_outline = ""

    return structure_outline

def normalize_post_strategy_decisions(decisions_data: dict, verbose: bool = False) -> dict:
    """Normalize and validate marketing decisions data."""
    normalized = {}
    
    # Voice (already validated above)
    normalized["voice"] = decisions_data.get("voice", "TheNewYorker")
    
    # Piece type
    valid_piece_types = ["explainer", "tutorial", "methods deep dive", "case study", "product update", "standards/policy analysis", "news reaction"]
    piece_type = decisions_data.get("piece_type", "").lower()
    normalized["piece_type"] = piece_type if piece_type in valid_piece_types else "explainer"
    
    # Marketing post type
    valid_marketing_types = ["Educational (TOFU)", "Comparison (MOFU)", "Conversion-focused (BOFU)", "Case Study", "Product Update", "Standards/Policy Analysis", "News Reaction"]
    marketing_type = decisions_data.get("marketing_post_type", "")
    normalized["marketing_post_type"] = marketing_type if marketing_type in valid_marketing_types else "Educational (TOFU)"
    
    # Primary goal
    valid_goals = ["educate", "persuade", "announce", "compare", "troubleshoot"]
    goal = decisions_data.get("primary_goal", "").lower()
    normalized["primary_goal"] = goal if goal in valid_goals else "educate"
    
    # Post target destination
    valid_destinations = ["website blog", "technical guide"]
    destination = decisions_data.get("post_target_destination", "").lower()
    normalized["post_target_destination"] = destination if destination in valid_destinations else "website blog"
    
    # Target audience
    valid_audiences = ["enterprise", "public sector", "academic", "hobbyist"]
    audience = decisions_data.get("target_audience", "").lower()
    normalized["target_audience"] = audience if audience in valid_audiences else "enterprise"
    
    # Technical depth
    valid_depths = ["low", "med", "high"]
    depth = decisions_data.get("technical_depth", "").lower()
    normalized["technical_depth"] = depth if depth in valid_depths else "med"
    
    # Candidate for code
    code_candidate = decisions_data.get("candidate_for_code")
    if code_candidate and isinstance(code_candidate, dict):
        if "justification" in code_candidate and "functionality_description" in code_candidate:
            normalized["candidate_for_code"] = {
                "justification": str(code_candidate["justification"]),
                "functionality_description": str(code_candidate["functionality_description"])
            }
        else:
            normalized["candidate_for_code"] = None
    else:
        normalized["candidate_for_code"] = None
    
    # Pain points
    pain_points = decisions_data.get("pain_points", [])
    if isinstance(pain_points, list):
        normalized["pain_points"] = [str(p) for p in pain_points if p]
    else:
        normalized["pain_points"] = []
    
    # Primary SEO keyword
    primary_seo = decisions_data.get("primary_seo_keyword", "")
    normalized["primary_seo_keyword"] = str(primary_seo) if primary_seo else ""
    
    # Secondary SEO keywords
    secondary_seo = decisions_data.get("secondary_seo_keywords", [])
    if isinstance(secondary_seo, list):
        normalized["secondary_seo_keywords"] = [str(k) for k in secondary_seo if k][:5]  # Max 5
    else:
        normalized["secondary_seo_keywords"] = []
    
    return normalized

def make_hybrid_filename(post_id: str, title: str, suffix: str = "") -> str:
    """
    Create hybrid filename: ID + short readable slug + suffix.
    
    Args:
        post_id: The unique post ID
        title: Post title for readable slug
        suffix: Optional suffix (e.g., "-pre_rewrite", "_decisions")
        
    Returns:
        Hybrid filename
    """

    file_title_word_length = 20

    # Create short readable slug (max 30 chars)
    title_slug = slugify(title)
    if len(title_slug) > file_title_word_length:
        # Truncate at word boundary if possible
        words = title_slug.split('_')
        short_slug = ""
        for word in words:
            if len(short_slug + word) <= file_title_word_length:
                short_slug += word + "_"
            else:
                break
        short_slug = short_slug.rstrip('_')
        if not short_slug:  # Fallback if first word is too long
            short_slug = title_slug[:file_title_word_length]
    else:
        short_slug = title_slug
    
    return f"{post_id}-{short_slug}{suffix}"

def save_raw_research_md(raw_output: str, posts_dir: Path) -> None:
    """
    Save raw research text to 00-insights_raw_text.md file.
    
    Args:
        raw_output: The raw research text to save
        posts_dir: Directory path where the file should be saved
    """
    try:
        posts_dir.mkdir(parents=True, exist_ok=True)
        raw_output_md_path = posts_dir / "00-insights.md"
        raw_output_md_path.write_text(raw_output, encoding="utf-8")
        logging.debug(f"✅ Raw insights written to {raw_output_md_path.resolve()}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to write raw insights markdown: {e}")

def save_raw_research_json(insights: list[InsightObject], posts_dir: Path) -> None:
    """
    Save insights to 00-insights.json file.
    
    Args:
        insights: List of InsightObject instances to save
        posts_dir: Directory path where the file should be saved
    """
    # Write insights to a fixed file named "00-insights.json" inside the posts directory
  
    try:
        posts_dir.mkdir(parents=True, exist_ok=True)
        insights_path = posts_dir / "00-insights.json"
        
        # Create JSON-compatible data structure that matches load_insights_from_file() expectations
        # The function expects a list of insight dictionaries, so we write the insights array directly
        insights_for_json = []
        for insight_obj in insights:
            insight_dict = {
                "title": insight_obj.title,
                "content": insight_obj.content,
                "source_urls": insight_obj.source_urls,
                "id": insight_obj.id,  # Include the generated ID
                "blog_post_content": insight_obj.blog_post_content,  # Include blog post content
                "used": insight_obj.used  # Include used flag
            }
            insights_for_json.append(insight_dict)
        
        # Write JSON data to file (overwrite mode for canonical format)
        with insights_path.open("w", encoding="utf-8") as f:
            json.dump(insights_for_json, f, indent=2, ensure_ascii=False)
        
        logging.debug(f"✅ Insights with IDs written to {insights_path.resolve()}")
    except Exception as e:
        logging.error(f"❌ Failed to write insights file: {e}")

def save_main_insights_json(insights: list[InsightObject], file_path: str = "main_insights.json") -> None:
    """
    Save insights to main_insights.json file with all fields including blog post content.
    
    Args:
        insights: List of InsightObject instances to save
        file_path: Path to the main insights JSON file
    """
    try:
        # Create JSON-compatible data structure
        insights_for_json = []
        for insight_obj in insights:
            insight_dict = {
                "title": insight_obj.title,
                "content": insight_obj.content,
                "source_urls": insight_obj.source_urls,
                "id": insight_obj.id,
                "blog_post_content": insight_obj.blog_post_content,
                "used": insight_obj.used
            }
            insights_for_json.append(insight_dict)
        
        # Write JSON data to file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(insights_for_json, f, indent=2, ensure_ascii=False)
        
        logging.info(f"✅ Main insights saved to {file_path} with {len(insights)} insights")
    except Exception as e:
        logging.error(f"❌ Failed to save main insights file: {e}")

def collect_global_urls(researcher) -> list[str]:
    """Collect global research URLs from GPTResearcher instance."""
    global_urls = []
    
    try:
        # Try to get source URLs from GPT-Researcher
        source_urls = researcher.get_source_urls() if hasattr(researcher, 'get_source_urls') else None
        if source_urls and isinstance(source_urls, list):
            global_urls.extend(source_urls)
    except Exception:
        pass
    
    try:
        # Try to get research sources from GPT-Researcher
        research_sources = researcher.get_research_sources() if hasattr(researcher, 'get_research_sources') else None
        if research_sources and isinstance(research_sources, list):
            source_urls_from_objs = []
            for obj in research_sources:
                if isinstance(obj, dict):
                    url = obj.get("url") or obj.get("source_url") or obj.get("link")
                    if url:
                        source_urls_from_objs.append(url)
            global_urls.extend(source_urls_from_objs)
    except Exception:
        pass
    
    # Normalize and dedupe global URLs
    return unique_ordered([
        normalize_url(url) for url in global_urls if is_http_url(normalize_url(url))
    ])

def enrich_insights_with_urls(insights: list[InsightObject], global_urls: list[str]) -> None:
    """Enrich insights with URLs from their own content only (no global research URL merge). Modifies insights in-place."""
    for insight in insights:
        # Normalize existing source URLs
        existing_urls = [
            normalize_url(url) for url in insight.source_urls
            if is_http_url(normalize_url(url))
        ]
        
        # Extract URLs from insight content
        content_urls = extract_urls_from_text(insight.content)
        
        # Merge only existing + content URLs, no global research URLs
        insight.source_urls = unique_ordered(existing_urls + content_urls)

async def run_raw_research(prompt: str, gr_verbose: bool = False) -> GPTResearcher:
    """
    Execute raw research using GPTResearcher.
    
    Returns:
        GPTResearcher instance after conducting research
    """
    logging.info("  🔧 Creating GPTResearcher instance...")

    try:
        #report_type="custom_report"
        #report_type = "custom_report"
        report_type = "deep"
        report_format = "json"
        tone = "objective"
        # report_type=report_type, tone=tone, report_format=report_format,
        researcher = GPTResearcher(query=prompt, report_type=report_type, verbose=gr_verbose)
        logging.info("  ✅ GPTResearcher instance created successfully")
    except Exception as e:
        logging.error(f"  ❌ FAILED to create GPTResearcher instance: {e}")
        raise
    
    # Get raw research from GPT-Researcher
    logging.info("  🔍 Conducting research (this may take a while)...")
    try:
        raw = await researcher.conduct_research()
        raw_text = str(raw)
        logging.info(f"  ✅ Research completed successfully ({len(raw_text)} characters)")
    except Exception as e:
        logging.error(f"  ❌ FAILED to conduct research: {e}")
        raise
    
    # Calculate word counts for approximation
    logging.info("  📊 Calculating word counts...")
    #    prompt_words = count_words(prompt)
    #    completion_words = count_words(raw_text)
    #    logging.info(f"  ✅ Word counts: prompt={prompt_words}, completion={completion_words}")
    return researcher

def build_prompt_for_blog_post_rewrite(
    blog_post_research: str, decision_metadata: dict, structure_outline: str) -> str:
    """
    Build a prompt for rewriting a blog post in the specified voice.
    
    Args:
        blog_post_research: The original blog post markdown content
        decision_metadata: Marketing metadata dict containing voice and all marketing decisions
        structure_outline: The headings the document should have
        
    Returns:
        The formatted prompt string for blog post rewriting
    """
    
    # Step 1: Load and build prompts
    company_operation_content = load_prompt_template(
        "00-platform_features_and_limitations_prompt",
    )

    content_marketing_guidance_content = load_prompt_template(
        "00-content_marketing_prompt",
    ) 

    mission_strategy_prompt = load_prompt_template(
        "00-mission_and_strategy_prompt",
    )

    titles_content = load_prompt_template(
        "00-title_crafting_prompt",
    )

    formatting_rules_prompt = load_prompt_template(
        "00-formatting_rules_prompt",
    )
    
    # Extract voice from decision_metadata
    voice_key = decision_metadata.get("voice", "TheNewYorker")
    
    # Get voice definition
    voice_definition = VOICE_DEFINITIONS.get(voice_key, VOICE_DEFINITIONS["TheNewYorker"])
    
    # Build metadata guidance if available
    metadata_guidance = ""
    if decision_metadata and isinstance(decision_metadata, dict):
        guidance_parts = []
        
        # Piece type guidance
        piece_type = decision_metadata.get("piece_type", "")
        if piece_type:
            guidance_parts.append(f"- Piece type: {piece_type} (align narrative structure and framing accordingly)")
        
        # Marketing post type guidance
        marketing_type = decision_metadata.get("marketing_post_type", "")
        if marketing_type:
            guidance_parts.append(f"- Marketing post type: {marketing_type} (shape intro framing and CTA)")
        
        # Primary goal guidance
        primary_goal = decision_metadata.get("primary_goal", "")
        if primary_goal:
            guidance_parts.append(f"- Primary goal: {primary_goal} (optimize tone, framing, and conclusion to meet this goal)")
        
        # Target destination guidance
        target_destination = decision_metadata.get("post_target_destination", "")
        if target_destination:
            guidance_parts.append(f"- Target destination: {target_destination} (match the level of formality and publishing context)")
        
        # Target audience guidance
        target_audience = decision_metadata.get("target_audience", "")
        if target_audience:
            guidance_parts.append(f"- Target audience: {target_audience} (adapt vocabulary, assumptions, and examples appropriately)")
        
        # Technical depth guidance
        technical_depth = decision_metadata.get("technical_depth", "")
        if technical_depth:
            guidance_parts.append(f"- Technical depth: {technical_depth} (adjust explanations and jargon density accordingly)")
        
        # Pain points guidance
        pain_points = decision_metadata.get("pain_points", [])
        if pain_points and isinstance(pain_points, list):
            pain_points_str = ", ".join(pain_points)
            guidance_parts.append(f"- Pain points to emphasize: {pain_points_str}")
        
        # SEO keywords guidance
        primary_seo = decision_metadata.get("primary_seo_keyword", "")
        secondary_seo = decision_metadata.get("secondary_seo_keywords", [])
        if primary_seo or secondary_seo:
            seo_guidance = f"primary=\"{primary_seo}\""
            if secondary_seo and isinstance(secondary_seo, list):
                seo_guidance += f", secondary={secondary_seo}"
            guidance_parts.append(f"- SEO keywords: {seo_guidance} (weave naturally in body text)")
        
        # Code candidate guidance
        code_candidate = decision_metadata.get("candidate_for_code")
        if code_candidate and isinstance(code_candidate, dict):
            functionality = code_candidate.get("functionality_description", "")
            if functionality:
                guidance_parts.append(f"- Candidate for code: {functionality} — if present, describe a practical application in the Practical Guidance section in prose (no code blocks), only if it improves clarity and fits naturally")
        
        if guidance_parts:
            metadata_guidance = f""" Use these marketing decisions to guide the rewrite : {chr(10).join(guidance_parts)}"""

    logging.info(f"✅ - Metadata Guidance provided to report writer \n {metadata_guidance}")

    # Load system prompt template 
    prompt = load_prompt_template(
        "04-write_blog_post_prompt",
        #voice_key=voice_key,
        #voice_definition=voice_definition,
        company_operation_content=company_operation_content,
        content_marketing_guidance_content=content_marketing_guidance_content,
        mission_strategy_prompt=mission_strategy_prompt,
        metadata_guidance=metadata_guidance,    
        formatting_rules_prompt=formatting_rules_prompt, 
        #structure_outline=structure_outline,           
    )

    return prompt

# ----------------------------------------------------------------------
# Helper – Non‑AI extraction (deterministic passthrough/convert)
# ----------------------------------------------------------------------
async def extract_insights_from_raw(
    raw_text: str, topic: str, verbose: bool = False) -> tuple[list[InsightObject], str]:
    """
    Deterministically convert raw GPT‑Researcher output into structured insights
    WITHOUT calling an LLM.

    Strategy:
      1) If raw_text is JSON:
         - If schema == [{title, content, source_urls}], accept directly.
         - If schema == [{insight, context, source_reference, ...}], map:
             title = item["insight"]
             content = f"{item['insight']} — {item.get('context','')}".strip(" —")
             source_urls = item.get("source_reference", [])
      2) Else:
         - Split raw_text into paragraphs on blank lines (fallback to lines),
           strip bullets/headings, filter by length, extract URLs, synthesize title.
    Returns:
      (insight_objects, extraction_json_string)
    """
    # Save raw research text for reference
    # Strip markdown formatting (bold markers) before parsing
    raw_text = raw_text.replace("**", "")
    # Try to parse as a Python literal list
    try:
        data = ast.literal_eval(raw_text)
        if not isinstance(data, list):
            raise ValueError("Parsed data is not a list")
    except Exception as e:
        raise ValueError(f"Failed to parse raw insights as Python literal: {e}")
    
    insights: list[InsightObject] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        # Normalize keys to lower‑case for case‑insensitive matching
        normalized = {k.lower(): v for k, v in entry.items()}
        # Map possible fields to the unified schema (case‑insensitive)
        title = (
            normalized.get("title")
            or normalized.get("insight")
            or ""
        )
        content = (
            normalized.get("content")
            or normalized.get("context")
            or ""
        )
        source = (
            normalized.get("source_urls")
            or normalized.get("source")
            or normalized.get("source_reference")
            or []
        )
        if isinstance(source, str):
            source_urls = [source]
        elif isinstance(source, list):
            source_urls = [s for s in source if isinstance(s, str)]
        else:
            source_urls = []
        insights.append(InsightObject(title=title, content=content, source_urls=source_urls))
    
    extraction_json = json.dumps(
        [{"title": i.title, "content": i.content, "source_urls": i.source_urls} for i in insights],
        ensure_ascii=False,
        indent=2,
    )
    
    if verbose:
        logging.info(f"✅ Deterministic extractor produced {len(insights)} insights")
    
    return insights, extraction_json

async def run_research_pipeline(topic: str, posts_dir: str, verbose: bool = False, gr_verbose: bool = False) -> tuple[list[InsightObject], str, str, str, int, int, float]:
    """
    Execute the complete research pipeline in a linear fashion.
    
    Returns:
        Tuple of (insights, prompt_used, raw_output, extraction_json, prompt_words, completion_words, research_subtotal_usd)
    """
    logging.info("🔎 Starting research pipeline...")
    
    # Step 1: Build prompts
    logging.info("📋 Research step 1: Building prompts...")
    try:
        prompt = load_prompt_template(
            "01-insight_research_prompt",
            topic=topic,
        )
        logging.info("✅ Research step 1 completed: Prompt built successfully")
    except Exception as e:
        logging.error(f"❌ Step 1 FAILED: Error building prompt: {e}")
        raise
    
    # Step 2: Execute raw research
    logging.info("🔬 Research step 2: Executing raw research...")
    try:
    #    logging.info(f"   ** Prompt ** \n {prompt}")
        researcher = await run_raw_research(prompt, gr_verbose)
        logging.info("✅ Research step 2 completed: Raw research executed successfully")
    except Exception as e:
        logging.error(f"❌ Research step 2 FAILED: Error executing raw research: {e}")
        raise
    
    # Step 3: Collect global URLs
    logging.info("🔗 Research step 3: Collecting global URLs...")
    try:
        global_urls = collect_global_urls(researcher)
        if verbose and global_urls:
            logging.debug(f"🔗 Collected {len(global_urls)} unique research URLs for reference (not auto-merged into insights)")
        logging.info(f"✅ Research step 3 completed: Global URLs collected successfully. Collected {len(global_urls)} unique research URLs")
    except Exception as e:
        logging.error(f"❌ Research step 3 FAILED: Error collecting global URLs: {e}")
        raise
    
    # Step 4: Write research (which will output json formated data)
    logging.info("📝 Research step 4: Generate research text...researcher.write_report step")
    report_prompt = load_prompt_template(
        "01-insight_report_generation_prompt",
        topic=topic,
    )
    try:
        insight_research = await researcher.write_report(custom_prompt=report_prompt)
    #    logging.info(report)
    #    logging.info("=" * 80)
    except Exception as e:
        logging.error(f"❌ Error generating technical report: {e}")
        logging.info("=" * 80)

    # Step 5: Save raw research text to file
    logging.info("📝 Research step 5: Saving raw research text...")
    try:
        save_raw_research_md(insight_research, posts_dir)
        logging.info("✅ Research step 5 completed: Raw research text saved successfully")
    except Exception as e:
        logging.warning(f"⚠️ Research step 5 WARNING: Failed to save raw research text: {e}")

    # Step 6: Extract insights using deterministic approach
    logging.info("📊 Research step 6: Extracting insights from raw research...")
    try:
        insights, extraction_json = await extract_insights_from_raw(
            insight_research, topic, verbose
        )
        logging.info("✅ Research step 6 completed: Insights extracted successfully")
    except Exception as e:
        logging.error(f"❌ Research step 6 FAILED: Error extracting insights: {e}")
        raise
    
    # Step 7: Enrich insights with URLs
    logging.info("🔗 Research step 7: Enriching insights with URLs...")
    try:
        #enrich_insights_with_urls(insights, global_urls)
        if verbose and global_urls:
            enriched_count = sum(1 for insight in insights if len(insight.source_urls) > 0)
            logging.debug(f"🔗 Enriched {enriched_count}/{len(insights)} insights with source URLs")
        logging.info("✅ Research step 7 completed: Insights enriched with URLs successfully")
    except Exception as e:
        logging.error(f"❌ Research step 7 FAILED: Error enriching insights: {e}")
        raise
    
    # Step 8: Generater IDs for insights
    logging.info("🔗 Research step 8: Generate IDs for insights...")
    try:
        generate_ids_for_insights(insights, verbose=verbose)
        logging.info("✅ Research step 8 completed: IDs generated successfully")
    except Exception as e:
        logging.error(f"❌ Research step 8 FAILED: Error adding IDs for insights: {e}")
        raise

    # Step 9: Save insights to json
    logging.info("📝 Research step 9: Saving JSON insights...")
    try:
        save_raw_research_json(insights, posts_dir)
        logging.info("✅ Research step 9 completed: Insights JSON file saved successfully")
    except Exception as e:
        logging.warning(f"⚠️ Research step 9 WARNING: Failed to save insights JSON file: {e}")

    logging.info("✅ - Research pipeline completed successfully  ")
    return insights

async def draft_blog_post(topic: str, insight: InsightObject, posts_dir: Optional[Path] = None, verbose: bool = False, gr_verbose: bool = False) -> tuple[str, int, int, float]:
    """
    Generate a blog post draft for a single insight and update the insight object.
    
    Args:
        topic: The research topic
        insight: The InsightObject to generate a blog post for (will be updated with blog content)
        posts_dir: Directory path where decisions should be saved (optional)
        verbose: If True, prints progress information
        gr_verbose: If True, enables verbose output for GPT-Researcher
    
    Returns:
        Tuple of (draft_md, draft_prompt_words, draft_completion_words, draft_subtotal_usd)
    """
    logging.debug(f"🖋️ Starting draft generation for: {insight.title[:50]}...")
    logging.debug(f"🖋️ posts_dir parameter: {posts_dir}")

    research_prompt = load_prompt_template(
        "02-research_blog_post_prompt",
        content=insight.content,
    ) 

    logging.info(f"🖋️ - Researching in progress [draft_blog_post] function")
    logging.info(f"🖋️ - Research Prompt  {research_prompt}")

    report_type = "deep"
    researcher = GPTResearcher(query=research_prompt, report_type=report_type, verbose=gr_verbose)
    
    try:
        # Step 1: Conduct research
        await researcher.conduct_research()
        logging.info(f"🖋️ - Research completed sucesfully ")

        # Step 2: Write initial report
        research_report = await researcher.write_report()
        research_report_word_count = len(research_report.split())
        logging.info(f"🖋️ - First Report Successfully Completed (Word count: {research_report_word_count})")

        research_context = researcher.get_research_context()
        research_costs = researcher.get_costs()
        research_images = researcher.get_research_images()
        research_sources = researcher.get_research_sources()
        logging.info(f"🖋️ Research Context list:\n {research_context}")
        logging.info(f"🖋️ Research cost:\n {research_costs}")
        logging.info(f"🖋️ Research images:\n {len(research_images)}")
        logging.info(f"🖋️ Research sources list:\n {len(research_sources)}")

        # Step 3: Extract metadata from the first report and select voice and marketing strategy
        logging.info(f"🖋️ Calling select_post_strategy with posts_dir: {posts_dir}")
        voice, decision_metadata = await select_post_strategy(insight, research_report, posts_dir, verbose)
        logging.info(f"🎭 Selected voice for rewrite: {decision_metadata.get('voice', 'TheNewYorker')}")

        # Step 3.5: Extract structure outline
        logging.info(f"🖋️ Calling select_post_strategy with posts_dir: {posts_dir}")
        structure_outline = await generate_blog_structure_outline(decision_metadata)

        # Step 5: Build new prompt using 04-** prompts and metadata
        rewrite_prompt = build_prompt_for_blog_post_rewrite(insight.content, decision_metadata, structure_outline)

        # Step 6: Write final report 
        report = await researcher.write_report(custom_prompt=rewrite_prompt)
        report_word_count = len(research_report.split())
        logging.info(f"🖋️ - Final Report completed succesfully (Word count: {research_report_word_count})")
    
    except Exception as exc:
        raise RuntimeError(f"Failed to generate blog post draft for '{insight.title}': {exc}") from exc
    
    # Update the insight object with the generated blog post content
    insight.blog_post_content = report
    insight.used = True
    
    if verbose:
        logging.info(f"✅ Updated insight '{insight.title[:50]}...' with blog post content and marked as used")
    
    return report

def save_post_file(blog_post_md: str, post_id: str, title: str, posts_dir: Path):
    """
    Save blog post files and return paths.
    
    Returns:
        Tuple of (blog_post_path, research_draft_path)
    """
    posts_dir.mkdir(parents=True, exist_ok=True)
    
    # Write main blog post
    blog_post_filename = make_hybrid_filename(post_id, title, "-blog_post.md")
    blog_post_file_path = posts_dir / blog_post_filename
    
    try:
        with blog_post_file_path.open("w", encoding="utf-8") as f:
            f.write(blog_post_md)
        
    except Exception as e:
        logging.error(f"Failed to write blog post. Error: {e}")
        raise RuntimeError(f"Failed to write blog post file '{blog_post_filename}': {e}") from e
    logging.info(f"✅ Blog post written to {blog_post_file_path.resolve()}")

# ----------------------------------------------------------------------
# Main workflow
# ----------------------------------------------------------------------
async def main_cli() -> None:
    start_time = time.time()
    
    # Configure logging with timestamped filename
    log_filename = f"cr_content_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG,  # Will be adjusted based on --verbose flag
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',  # Format without milliseconds
        filename=log_filename,
        filemode='w',
        encoding='utf-8'
    )
    
    parser = argparse.ArgumentParser(
        description="Generate insights and blog‑post drafts using GPT‑Researcher."
    )
    parser.add_argument(
        "--topic",
        required=False,
        help="Broad research topic (e.g., 'remote work productivity').",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Maximum number of blog posts to generate. Default: all insights (len of parsed/generated insights).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed progress logging for the script.",
    )
    parser.add_argument(
        "--gr-verbose",
        action="store_true",
        help="Enable verbose output for GPT-Researcher operations.",
    )
    parser.add_argument(
        "--insights-only",
        action="store_true",
        help="Generate only insights and stop before creating blog posts.",
    )
    parser.add_argument(
        "--insights-input",
        type=str,
        help="Path to JSON file containing structured insights for blog generation. When provided, skips insight generation and creates blog posts from the file.",
    )
    parser.add_argument(
        "--posts-dir",
        type=str,
        default=None,
        help="Directory to save blog post files. If omitted, defaults to topic-{topic} (spaces in topic replaced with underscores). If topic is omitted (e.g., with --insights-input), defaults to 'posts'. Will be created if it doesn't exist.",
    )
    args = parser.parse_args()

    # Validate that topic is provided unless insights-input is used
    if not args.insights_input and not args.topic:
        parser.error("--topic is required unless --insights-input is provided")

    # Compute effective posts_dir: always under posts/ base directory
    if args.posts_dir is None:
        if args.topic:
            # Replace spaces with underscores in topic for directory name
            topic_slug = re.sub(r'\s+', '_', args.topic.strip())
            subdir = f"topic-{topic_slug}"
        else:
            # Fallback for cases like --insights-input without --topic - use posts root
            subdir = ""
    else:
        # Sanitize user-provided posts_dir
        subdir = args.posts_dir.strip().lstrip("/").lstrip("\\")
    
    # Always nest under posts/ base directory
    posts_dir = Path("posts") / subdir if subdir else Path("posts")

    # Adjust logging level based on --verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)
    
    logging.info(f"📝 Logging to: {log_filename}")
    
    # ------------------------------------------------------------------
    # Prepare environment
    # ------------------------------------------------------------------
    try:
        load_environment()
        logging.info("✅ Environment loaded successfully")
        
    except Exception as e:
        logging.error(f"❌ Environment setup error: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Generate insights list
    # ------------------------------------------------------------------
    try:
        if not args.insights_input:
            # Normal mode - generate insights using GPT-Researcher
            insights = await run_research_pipeline(
            args.topic, 
            posts_dir=posts_dir, 
            verbose=args.verbose, 
            gr_verbose=args.gr_verbose 
            )        
        else:
            # Load insights from external JSON file
            logging.info(f"📂 Loading insights from file: {args.insights_input}")
            insights_file_path = Path(args.insights_input)
            insights = load_insights_from_file(insights_file_path)
            logging.info(f"✅ Loaded {len(insights)} insights from {args.insights_input}")
    except Exception as e:
        logging.error(f"❌ Error while generating insights: {e}")
        sys.exit(1)

    if not insights:
        logging.warning("⚠️ No insights were returned – aborting.")
        sys.exit(0)

    logging.info(f"✅ Retrieved {len(insights)} structured insights.")

    # Calculate and print total execution time
    end_time = time.time()
    elapsed_time = end_time - start_time
    logging.info(f"⏱️ Total execution time: {elapsed_time:.2f} seconds")

    # ------------------------------------------------------------------
    # Exit early if insights-only mode is enabled
    # ------------------------------------------------------------------
    if args.insights_only:
        logging.info(f"✅ Insights-only mode: Generated {len(insights)} insights and stopped before blog post creation.")
        logging.debug(f"✅ Insights saved to {insights_path.resolve()}")
        sys.exit(0)

    # ------------------------------------------------------------------
    # Compute effective max_posts after insights are available
    # ------------------------------------------------------------------
    max_posts_effective = args.max_posts if args.max_posts is not None else len(insights)
    if args.max_posts is None:
        logging.debug(f"ℹ️ --max-posts not provided; defaulting to {max_posts_effective} (number of insights).")
    else:
        logging.info(f" --maxp-posts was provided and will use the value of {args.max_posts}")

    # ------------------------------------------------------------------
    # Generate blog posts
    # ------------------------------------------------------------------
    for idx, insight_obj in enumerate(insights[:max_posts_effective], start=1):
        try:
            logging.info(f"📝 Processing insight {idx}/{max_posts_effective}: {insight_obj.title[:50]}...")
            blog_post_md = await draft_blog_post(
                args.topic,
                insight_obj,
                posts_dir=posts_dir,  # Pass posts_dir to enable decision file writing
                verbose=args.verbose,
                gr_verbose=args.gr_verbose
            )
            
            # Save the blog post file inside try block with correct variables
            save_post_file(blog_post_md, insight_obj.id, insight_obj.title, posts_dir)
            logging.info(f"✅ Completed insight {idx}/{max_posts_effective}")

        except Exception as e:
            logging.error(f"❌ Error processing insight {idx}: {e}", exc_info=True)
            logging.warning(f"⚠️ Skipping insight due to error: {e}")
 
    logging.info(f"✅ Blog post generation completed for {len(insights)} insights.")
    
    # Save updated insights back to main_insights.json with blog post content
    logging.info("💾 Saving updated insights to main_insights.json...")
    try:
        save_main_insights_json(insights if isinstance(insights, list) else insights[0])
        logging.info("✅ Main insights file updated with blog post content")
    except Exception as e:
        logging.error(f"❌ Failed to save main insights file: {e}")

    # Calculate and print total execution time
    end_time = time.time()
    elapsed_time = end_time - start_time
    logging.info(f"⏱️ Total execution time: {elapsed_time:.2f} seconds")

# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main_cli())
