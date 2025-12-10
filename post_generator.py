#!/usr/bin/env python3
"""
Simple script to generate marketing blog posts using a local OpenAI compliant API endpoint.
Based on the reference implementation pattern from cr_content_pipeline.py
Uses built-in system and user prompts for Construkted Reality marketing content.

Enhanced with 5-stage article synthesis pipeline: EXTRACT → SCORE → SELECT → SYNTHESIZE → VALIDATE
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================================
# DATA STRUCTURES FOR ARTICLE SYNTHESIS PIPELINE
# ============================================================================

@dataclass
class ArticleCandidate:
    """Container for a generated article candidate."""
    article_id: int
    content: str
    word_count: int
    generation_timestamp: float

@dataclass
class ArticleCard:
    """Structured extraction from a candidate article (EXTRACT stage output)."""
    article_id: int
    headline_candidates: List[str]
    opening_hook: str
    core_argument: str
    key_points: List[str]
    memorable_phrases: List[str]
    structural_approach: str
    evidence_used: List[str]
    tone: str
    target_audience_signals: str
    weaknesses: List[str]
    word_count_estimate: int

@dataclass
class ArticleScore:
    """Quality scores for an article card (SCORE stage output)."""
    article_id: int
    scores: Dict[str, Dict[str, any]]  # criterion_name -> {score: int, justification: str}
    overall_score: float
    standout_strengths: List[str]
    critical_weaknesses: List[str]

@dataclass
class SynthesisBlueprint:
    """Specification for combining best elements (SELECT stage output)."""
    selected_headline: Dict[str, any]
    selected_opening: Dict[str, any]
    selected_structure: Dict[str, any]
    selected_arguments: Dict[str, any]
    selected_evidence: List[Dict[str, any]]
    phrases_to_preserve: List[Dict[str, any]]
    elements_to_avoid: List[str]
    synthesis_notes: str
    confidence: Dict[str, any]

@dataclass
class ValidationResult:
    """Quality assessment of synthesized article (VALIDATE stage output)."""
    passed: bool
    blueprint_compliance: Dict[str, any]
    quality_scores: Dict[str, int]
    coherence_assessment: Dict[str, bool]
    issues: List[str]
    improvement_suggestions: List[str]
    target_threshold: float
    threshold_met: bool

# ============================================================================
# PIPELINE CONSTANTS
# ============================================================================

SCORING_CRITERIA = {
    "hook_strength": {
        "description": "How compelling is the opening? Does it create curiosity, tension, or immediate value?",
        "weight": 0.15
    },
    "argument_clarity": {
        "description": "Is the core message immediately clear? Can you summarize it in one sentence?",
        "weight": 0.20
    },
    "evidence_quality": {
        "description": "Are claims supported with specifics? Statistics, examples, case studies?",
        "weight": 0.15
    },
    "structural_coherence": {
        "description": "Does the structure serve the argument? Is there a logical flow?",
        "weight": 0.15
    },
    "originality": {
        "description": "Does it offer a fresh angle? Or is it generic advice anyone could write?",
        "weight": 0.15
    },
    "memorability": {
        "description": "Are there phrases or ideas that stick? Would someone quote this?",
        "weight": 0.10
    },
    "actionability": {
        "description": "Does the reader know what to do after reading? Is there a clear next step?",
        "weight": 0.10
    }
}

def load_environment() -> None:
    """Load .env file and set environment variables."""
    load_dotenv()
    
    # Validate required OpenAI configuration
    openai_api_base = os.getenv("OPENAI_API_BASE")
    if not openai_api_base:
        raise ValueError("OPENAI_API_BASE environment variable is not set.")
    os.environ["OPENAI_API_BASE"] = openai_api_base
    
    # Set API key (use dummy key if server doesn't require authentication)
    os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "sk-dummy-key-if-not-needed")
    
    # Validate model name
    openai_model_name = os.getenv("OPENAI_MODEL_NAME")
    if not openai_model_name:
        raise ValueError("OPENAI_MODEL_NAME environment variable is not set.")
    os.environ["OPENAI_MODEL_NAME"] = openai_model_name


def read_reference_file(file_path: str) -> str:
    """Read and return the content of a reference file."""
    try:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Reference file not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to read reference file {file_path}: {e}")


def build_system_prompt() -> str:
    """
    Build the system prompt by combining content from reference files.
    
    Returns:
        The complete system prompt string
    """
    try:
        # Read the three reference context files
        writing_style_content = read_reference_file("reference_context/writing_style-enhanced.md")
        market_analysis_content = read_reference_file("reference_context/Combined_Small_Team_Geospatial_Market_Analysis.md")
        construkted_context_content = read_reference_file("reference_context/construkted_context.md")
        
        # Build the system prompt by combining all content
        system_prompt = f"""You are a masterful marketing copywriter for the company Construkted Reality. You generate engaging blog articles using the style guide provided.

WRITING STYLE GUIDE:
{writing_style_content}

COMPANY CONTEXT:
{construkted_context_content}

MARKET RESEARCH CONTEXT:
{market_analysis_content}

When writing marketing content, always:
1. Follow the writing style guidelines precisely
2. Incorporate company context and mission naturally
3. Reference market insights where relevant to strengthen arguments
4. Maintain an engaging, conversational tone that educates while exciting
5. Focus on the benefits of user-generated 3D data and community collaboration
6. Avoid corporate jargon and speak directly to both professionals and hobbyists"""
        
        return system_prompt
        
    except Exception as e:
        raise RuntimeError(f"Failed to build system prompt: {e}")


def filter_think_tags(text: str) -> str:
    """
    Filter out content between <think> and </think> tags.
    
    Args:
        text: The text to filter
        
    Returns:
        The filtered text with think tag content removed
    """
    # Pattern to match content between <think> and </think> tags
    pattern = r'<think>.*?</think>'
    # Use DOTALL flag to match across newlines
    filtered_text = re.sub(pattern, '', text, flags=re.DOTALL)
    # Clean up any extra whitespace that might be left
    filtered_text = re.sub(r'\n\s*\n', '\n\n', filtered_text)
    return filtered_text.strip()


def build_user_prompt(topic_file: str) -> str:
    """
    Build the user prompt for blog post generation.
    
    Args:
        topic_file: Path to a file containing the specific blog post topic/idea
        
    Returns:
        The user prompt string
    """
    return read_reference_file(topic_file)

def create_output_directory(base_name: str) -> Path:
    """Create organized output directory structure."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = Path(f"outputs/{date_str}/{base_name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create subdirectories
    (output_dir / "candidates").mkdir(exist_ok=True)
    
    return output_dir

def cleanup_old_outputs(days_to_keep: int = 30) -> None:
    """Remove output directories older than specified days."""
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    outputs_dir = Path("outputs")
    
    if outputs_dir.exists():
        for output_dir in outputs_dir.iterdir():
            if output_dir.is_dir():
                # Check directory modification time
                if datetime.fromtimestamp(output_dir.stat().st_mtime) < cutoff_date:
                    print(f"Found old output directory: {output_dir}")
                    response = input(f"Remove old output directory: {output_dir}? (y/N): ")
                    if response.lower() == 'y':
                        shutil.rmtree(output_dir)
                        print(f"Removed: {output_dir}")

def send_to_llm(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    retry_count: int = 3,
    retry_delay: float = 1.0,
    verbose: bool = False
) -> str:
    """
    Send prompt to the local OpenAI compliant API endpoint.
    
    Args:
        user_prompt: User prompt/instruction
        system_prompt: System prompt (uses built-in prompt if None)
        temperature: Sampling temperature (default 0.7)
        max_tokens: Maximum tokens to generate (default 4000)
        retry_count: Number of API call retries (default 3)
        retry_delay: Delay between retries in seconds (default 1.0)
        verbose: Enable verbose logging (default False)
        
    Returns:
        The LLM response content as a string
    """
    # Create OpenAI client using the configured vLLM endpoint
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "sk-dummy-key-if-not-needed"),
        base_url=os.getenv("OPENAI_API_BASE")
    )
    
    # Use built-in system prompt if none provided
    if system_prompt is None:
        system_prompt = build_system_prompt()
    
    # Prepare messages for the API
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # Get model name from environment
    model_name = os.getenv("OPENAI_MODEL_NAME")
    if not model_name:
        raise ValueError("OPENAI_MODEL_NAME environment variable is not set")
    
    last_error = None
    for attempt in range(retry_count):
        try:
            # Make API call to the local OpenAI compliant endpoint
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Extract and return the response content
            response_content = response.choices[0].message.content
            if response_content is None:
                raise ValueError("Empty response from LLM")
                
            return response_content.strip()
            
        except Exception as e:
            last_error = e
            if verbose:
                print(f"API call attempt {attempt + 1} failed: {e}")
            
            if attempt < retry_count - 1:  # Don't sleep on the last attempt
                if verbose:
                    print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
    
    # If we get here, all retries failed
    raise RuntimeError(f"Failed to get response from LLM after {retry_count} attempts. Last error: {last_error}")


# ============================================================================
# PIPELINE STAGE 1: EXTRACT
# Purpose: Convert full articles into structured article cards
# ============================================================================

def extract_article_card(
    article_content: str,
    article_id: int,
    verbose: bool = False,
    retry_count: int = 3
) -> ArticleCard:
    """
    Extract structured card from a single article.
    
    Args:
        article_content: Full article text
        article_id: Unique identifier for this article
        verbose: Enable progress logging
        retry_count: Number of retry attempts for failed extractions
        
    Returns:
        ArticleCard with structured data
    """
    system_prompt = """You are a content analysis agent. Your job is to extract the essential elements from a marketing blog article into a structured format.

You must respond with ONLY a valid JSON object. No markdown, no explanation, no preamble.

## Output Schema

{
  "article_id": <integer>,
  "headline_candidates": [
    "<headline 1 from article>",
    "<headline 2 - alternative or subheading that could work as main>"
  ],
  "opening_hook": "<The first 2-3 sentences verbatim. This is the hook that draws readers in.>",
  "core_argument": "<A 2-3 sentence summary of the article's central thesis or value proposition. What is this article really saying?>",
  "key_points": [
    "<Key supporting point 1>",
    "<Key supporting point 2>",
    "<Key supporting point 3>",
    "<Key supporting point 4 if present>",
    "<Key supporting point 5 if present>"
  ],
  "memorable_phrases": [
    "<Verbatim quote of a particularly well-written phrase or sentence>",
    "<Another strong phrase worth preserving>",
    "<Up to 5 total>"
  ],
  "structural_approach": "<Brief description: How is this article organized? (e.g., 'Problem-Solution-CTA', 'Listicle with intro/outro', 'Story-driven with embedded lessons', 'Question-answer format')>",
  "evidence_used": [
    "<Type of evidence: statistic, case study, expert quote, analogy, etc.>"
  ],
  "tone": "<1-3 words describing the tone: e.g., 'conversational and urgent', 'professional and authoritative', 'playful and accessible'>",
  "target_audience_signals": "<Who does this article seem written for? What assumptions does it make about the reader?>",
  "weaknesses": [
    "<Identified weakness 1: e.g., 'Opening is generic', 'Lacks concrete examples', 'Too long before getting to the point'>",
    "<Identified weakness 2 if present>"
  ],
  "word_count_estimate": <integer>
}

## Rules
- Extract what IS there, don't invent or improve
- For "memorable_phrases", copy VERBATIM - these are candidates for preservation
- Be specific in weaknesses - vague criticism isn't useful
- If the article lacks something (e.g., no statistics), note it in weaknesses"""

    user_prompt = f"""Extract the article card for Article #{article_id}.

<article>
{article_content}
</article>

Respond with only the JSON object."""

    for attempt in range(retry_count):
        try:
            response = send_to_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,  # Low temp for consistent extraction
                max_tokens=4000,
                verbose=verbose
            )
            
            # Filter out think tags from reasoning model output
            response = filter_think_tags(response)
            
            # Parse and validate JSON
            card_data = json.loads(response)
            
            # Validate required fields
            required_fields = [
                "article_id", "headline_candidates", "opening_hook",
                "core_argument", "key_points", "memorable_phrases",
                "structural_approach", "evidence_used", "tone",
                "target_audience_signals", "weaknesses"
            ]
            
            for field in required_fields:
                if field not in card_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Create ArticleCard object
            card = ArticleCard(**card_data)
            
            if verbose:
                print(f"  ✓ Extracted card for Article #{article_id}")
            
            return card
            
        except (json.JSONDecodeError, ValueError) as e:
            if verbose:
                print(f"  ⚠ Extraction attempt {attempt + 1} failed: {e}")
            if attempt == retry_count - 1:
                raise RuntimeError(f"Failed to extract valid card after {retry_count} attempts")
    
    raise RuntimeError("Extraction failed unexpectedly")


def extract_all_article_cards(
    candidates: List[ArticleCandidate],
    verbose: bool = False
) -> List[ArticleCard]:
    """
    Extract article cards from all candidates.
    
    Args:
        candidates: List of generated article candidates
        verbose: Enable progress logging
        
    Returns:
        List of ArticleCard objects
    """
    if verbose:
        print(f"\n{'='*80}")
        print("PIPELINE STAGE 1: EXTRACT")
        print(f"{'='*80}")
        print(f"Extracting structured cards from {len(candidates)} articles...")
    
    cards = []
    for candidate in candidates:
        try:
            card = extract_article_card(
                article_content=candidate.content,
                article_id=candidate.article_id,
                verbose=verbose
            )
            cards.append(card)
        except Exception as e:
            if verbose:
                print(f"  ✗ Failed to extract Article #{candidate.article_id}: {e}")
            # Continue with other cards rather than failing entire pipeline
    
    if verbose:
        print(f"✓ Successfully extracted {len(cards)}/{len(candidates)} article cards\n")
    
    return cards


# ============================================================================
# PIPELINE STAGE 2: SCORE
# Purpose: Evaluate article cards on quality dimensions with voting
# ============================================================================

def score_article_card(
    card: ArticleCard,
    criteria: Dict[str, Dict[str, any]],
    verbose: bool = False
) -> ArticleScore:
    """
    Score a single article card on all criteria.
    
    Args:
        card: ArticleCard to evaluate
        criteria: Scoring criteria dictionary
        verbose: Enable progress logging
        
    Returns:
        ArticleScore with scores and justifications
    """
    system_prompt = """You are a content quality evaluator. You will receive an article card (a structured summary of a blog article) and a set of scoring criteria.

Score the article on each criterion from 1-10, and provide a brief justification for each score.

You must respond with ONLY a valid JSON object. No markdown, no explanation.

## Scoring Guidelines

- 1-3: Poor. Significant problems or missing entirely.
- 4-5: Below average. Present but weak.
- 6-7: Acceptable. Meets basic expectations.
- 8-9: Strong. Notably good, few improvements needed.
- 10: Exceptional. Could be used as an example of excellence.

Be discriminating. If everything scores 7-8, you're not being critical enough.
Reserve 9-10 for genuinely standout elements.

## Output Schema

{
  "article_id": <integer>,
  "scores": {
    "<criterion_name>": {
      "score": <integer 1-10>,
      "justification": "<1-2 sentences explaining the score>"
    },
    ...
  },
  "overall_score": <float - weighted average>,
  "standout_strengths": ["<what this article does notably well>"],
  "critical_weaknesses": ["<what would need fixing>"]
}"""

    user_prompt = f"""Score the following article card against the provided criteria.

## Article Card
{json.dumps(card.__dict__, indent=2)}

## Scoring Criteria
{json.dumps(criteria, indent=2)}

Respond with only the JSON object containing scores and justifications."""

    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.2,  # Low temp for consistent evaluation
        max_tokens=4000,
        verbose=verbose
    )
    
    # Filter out think tags from reasoning model output
    response = filter_think_tags(response)
    
    score_data = json.loads(response)
    
    # Calculate weighted overall score
    total_score = 0.0
    for criterion_name, criterion_info in criteria.items():
        if criterion_name in score_data["scores"]:
            score_value = score_data["scores"][criterion_name]["score"]
            weight = criterion_info["weight"]
            total_score += score_value * weight
    
    score_data["overall_score"] = round(total_score, 2)
    
    return ArticleScore(**score_data)


def average_score_votes(votes: List[ArticleScore]) -> ArticleScore:
    """
    Average multiple scoring votes for the same article.
    
    Args:
        votes: List of ArticleScore objects from multiple votes
        
    Returns:
        Averaged ArticleScore
    """
    if not votes:
        raise ValueError("No votes to average")
    
    # Use first vote as template
    averaged = votes[0]
    
    # Average numeric scores for each criterion
    for criterion_name in averaged.scores.keys():
        scores_sum = sum(
            vote.scores[criterion_name]["score"]
            for vote in votes
            if criterion_name in vote.scores
        )
        averaged.scores[criterion_name]["score"] = round(scores_sum / len(votes), 1)
        # Keep first justification (they should be similar)
    
    # Average overall score
    averaged.overall_score = round(
        sum(vote.overall_score for vote in votes) / len(votes), 2
    )
    
    # Merge strengths and weaknesses (unique items only)
    all_strengths = set()
    all_weaknesses = set()
    for vote in votes:
        all_strengths.update(vote.standout_strengths)
        all_weaknesses.update(vote.critical_weaknesses)
    
    averaged.standout_strengths = list(all_strengths)
    averaged.critical_weaknesses = list(all_weaknesses)
    
    return averaged


def score_all_cards_with_voting(
    cards: List[ArticleCard],
    criteria: Dict[str, Dict[str, any]] = SCORING_CRITERIA,
    votes: int = 3,
    verbose: bool = False
) -> List[ArticleScore]:
    """
    Score all cards with voting to reduce variance.
    
    Args:
        cards: List of ArticleCards to score
        criteria: Scoring criteria dictionary
        votes: Number of voting rounds per card (default: 3)
        verbose: Enable progress logging
        
    Returns:
        List of averaged ArticleScore objects
    """
    if verbose:
        print(f"\n{'='*80}")
        print("PIPELINE STAGE 2: SCORE")
        print(f"{'='*80}")
        print(f"Scoring {len(cards)} cards with {votes} votes each...")
    
    all_scores = []
    
    for card in cards:
        if verbose:
            print(f"  Scoring Article #{card.article_id}...")
        
        # Collect multiple votes
        card_votes = []
        for vote_num in range(votes):
            try:
                score = score_article_card(card, criteria, verbose=False)
                card_votes.append(score)
                if verbose:
                    print(f"    Vote {vote_num + 1}/{votes}: Overall score = {score.overall_score}")
            except Exception as e:
                if verbose:
                    print(f"    ⚠ Vote {vote_num + 1} failed: {e}")
        
        # Average the votes
        if card_votes:
            averaged_score = average_score_votes(card_votes)
            all_scores.append(averaged_score)
            if verbose:
                print(f"  ✓ Average score: {averaged_score.overall_score}\n")
    
    if verbose:
        scores_list = [s.overall_score for s in all_scores]
        print(f"✓ Scoring complete. Range: {min(scores_list):.1f} - {max(scores_list):.1f}\n")
    
    return all_scores


# ============================================================================
# PIPELINE STAGE 3: SELECT
# Purpose: Analyze scores and select best elements for synthesis
# ============================================================================

def select_best_elements(
    cards: List[ArticleCard],
    scores: List[ArticleScore],
    verbose: bool = False
) -> SynthesisBlueprint:
    """
    Analyze all cards and scores to select best elements for synthesis.
    
    Args:
        cards: List of ArticleCards
        scores: List of corresponding ArticleScore objects
        verbose: Enable progress logging
        
    Returns:
        SynthesisBlueprint specifying how to combine elements
    """
    if verbose:
        print(f"\n{'='*80}")
        print("PIPELINE STAGE 3: SELECT")
        print(f"{'='*80}")
        print(f"Analyzing {len(cards)} articles to select best elements...")
    
    # Build analysis input (compressed view)
    analysis_input = []
    for card, score in zip(cards, scores):
        analysis_input.append({
            "article_id": card.article_id,
            "headline_candidates": card.headline_candidates,
            "opening_hook": card.opening_hook[:200] + "...",  # Truncate for context
            "core_argument": card.core_argument,
            "key_points": card.key_points,
            "structural_approach": card.structural_approach,
            "memorable_phrases": card.memorable_phrases,
            "scores": {k: v["score"] for k, v in score.scores.items()},
            "overall_score": score.overall_score
        })
    
    system_prompt = """You are a content strategy agent. You will receive summaries and scores for multiple article drafts on the same topic.

Your job is to analyze them and create a "synthesis blueprint" - a specification for combining the best elements into one superior article.

You must respond with ONLY a valid JSON object.

## Your Task

1. Identify which article has the best version of each element
2. Note when elements should be combined from multiple sources
3. Create a clear specification the synthesis agent can follow

## Selection Principles

- Don't just pick the highest-scoring article. Recombine strengths.
- A 6-scoring article might have ONE element that's a 10.
- Look for complementary strengths (Article A's hook + Article B's structure + Article C's evidence)
- Note potential conflicts (if combining arguments that might contradict)

## Output Schema

{
  "synthesis_blueprint": {
    "selected_headline": {
      "source_article": <article_id>,
      "headline": "<the selected headline>",
      "rationale": "<why this headline wins>"
    },
    "selected_opening": {
      "source_article": <article_id>,
      "approach": "<description of the opening approach to use>",
      "key_elements": ["<specific elements to preserve>"],
      "rationale": "<why>"
    },
    "selected_structure": {
      "source_article": <article_id>,
      "structure_type": "<e.g., Problem-Solution-CTA>",
      "section_flow": ["<section 1>", "<section 2>", "..."],
      "rationale": "<why this structure>"
    },
    "selected_arguments": {
      "primary_source": <article_id>,
      "core_thesis": "<the main argument to use>",
      "supporting_points": [
        {
          "point": "<the point>",
          "source_article": <article_id>
        }
      ],
      "rationale": "<why these arguments>"
    },
    "selected_evidence": [
      {
        "evidence": "<specific statistic, example, or proof point>",
        "source_article": <article_id>,
        "where_to_use": "<which section this supports>"
      }
    ],
    "phrases_to_preserve": [
      {
        "phrase": "<verbatim memorable phrase>",
        "source_article": <article_id>,
        "suggested_placement": "<where in the final article>"
      }
    ],
    "elements_to_avoid": [
      "<specific weakness from source articles to NOT carry over>"
    ],
    "synthesis_notes": "<any additional guidance for the synthesis agent about tone, length, or approach>"
  },
  "confidence": {
    "level": "<high/medium/low>",
    "concerns": ["<any concerns about combining these elements>"]
  }
}"""

    user_prompt = f"""Analyze these {len(cards)} article drafts and create a synthesis blueprint.

## Article Summaries and Scores
{json.dumps(analysis_input, indent=2)}

Create a synthesis blueprint that combines the best elements into one superior article.

Respond with only the JSON object."""

    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.4,  # Some analytical creativity
        max_tokens=6000,
        verbose=verbose
    )
    
    # Filter out think tags from reasoning model output
    response = filter_think_tags(response)
    
    blueprint_data = json.loads(response)
    
    # Create blueprint with all required fields including confidence
    blueprint_dict = blueprint_data["synthesis_blueprint"].copy()
    blueprint_dict["confidence"] = blueprint_data["confidence"]
    
    blueprint = SynthesisBlueprint(**blueprint_dict)
    
    if verbose:
        print(f"✓ Blueprint created. Confidence: {blueprint.confidence['level']}\n")
    
    return blueprint


# ============================================================================
# PIPELINE STAGE 4: SYNTHESIZE
# Purpose: Generate final article from synthesis blueprint
# ============================================================================

def synthesize_final_article(
    blueprint: SynthesisBlueprint,
    original_user_prompt: str,
    brand_guidelines: str,
    target_word_count: int = 1500,
    verbose: bool = False
) -> str:
    """
    Generate final article from synthesis blueprint.
    
    Args:
        blueprint: SynthesisBlueprint with specifications
        original_user_prompt: The original topic/brief
        brand_guidelines: Company brand guidelines (from existing system prompt)
        target_word_count: Desired article length
        verbose: Enable progress logging
        
    Returns:
        Final synthesized article text
    """
    if verbose:
        print(f"\n{'='*80}")
        print("PIPELINE STAGE 4: SYNTHESIZE")
        print(f"{'='*80}")
        print(f"Generating final article from blueprint...")
    
    system_prompt = f"""You are a professional content writer. You will receive a synthesis blueprint that specifies exactly what elements to include in a marketing blog article.

Your job is to write a cohesive, polished article that incorporates all specified elements naturally.

## Brand Guidelines
{brand_guidelines}

## Target Length
Approximately {target_word_count} words.

## Writing Instructions

1. USE THE SPECIFIED HEADLINE exactly as provided
2. FOLLOW THE SPECIFIED STRUCTURE - use the section flow as your outline
3. INCORPORATE THE CORE ARGUMENT as the thesis
4. WEAVE IN THE SUPPORTING POINTS in the appropriate sections
5. INCLUDE THE SELECTED EVIDENCE where specified
6. PRESERVE THE MEMORABLE PHRASES - work them in naturally, verbatim
7. AVOID THE LISTED WEAKNESSES - don't repeat these mistakes

## Critical Rules

- Do NOT invent new arguments or evidence not in the blueprint
- Do NOT change the core thesis
- The memorable phrases should appear VERBATIM - they were selected for a reason
- Transitions between sections should feel natural, not forced
- The tone should be consistent throughout

## Output Format

Return ONLY the article text. No meta-commentary, no "Here's the article:", just the article itself starting with the headline.

Format:
# [Headline]

[Article body with natural paragraph breaks]"""

    user_prompt = f"""Write a marketing blog article following this synthesis blueprint.

## Original Brief
{original_user_prompt}

## Synthesis Blueprint
{json.dumps(blueprint.__dict__, indent=2)}

Write the complete article now. Start directly with the headline."""

    article = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.7,  # Higher temp for creative writing
        max_tokens=8000,
        verbose=verbose
    )
    
    # Filter out think tags from reasoning model output
    article = filter_think_tags(article)
    
    if verbose:
        word_count = len(article.split())
        print(f"✓ Synthesized article generated ({word_count} words)\n")
    
    return article


# ============================================================================
# PIPELINE STAGE 5: VALIDATE
# Purpose: Verify synthesized article meets quality standards
# ============================================================================

def validate_synthesized_article(
    article: str,
    blueprint: SynthesisBlueprint,
    original_scores: List[ArticleScore],
    verbose: bool = False
) -> ValidationResult:
    """
    Validate that synthesized article meets quality standards.
    
    Args:
        article: Synthesized article text
        blueprint: SynthesisBlueprint it should follow
        original_scores: Scores from source articles
        verbose: Enable progress logging
        
    Returns:
        ValidationResult with pass/fail and detailed feedback
    """
    if verbose:
        print(f"\n{'='*80}")
        print("PIPELINE STAGE 5: VALIDATE")
        print(f"{'='*80}")
        print("Validating synthesized article...")
    
    # Calculate target threshold (should beat average of sources)
    avg_source_score = sum(s.overall_score for s in original_scores) / len(original_scores)
    target_threshold = avg_source_score + 0.5
    
    system_prompt = f"""You are a content quality assurance agent. You will receive:
1. A synthesized article
2. The blueprint it was supposed to follow
3. A target quality threshold

Your job is to verify the article meets requirements and identify any issues.

You must respond with ONLY a valid JSON object.

## Validation Checks

1. BLUEPRINT COMPLIANCE
   - Does the article use the specified headline?
   - Does it follow the specified structure?
   - Does it include the core argument?
   - Are the supporting points present?
   - Is the evidence included where specified?
   - Are the memorable phrases preserved verbatim?
   - Does it avoid the listed weaknesses?

2. QUALITY ASSESSMENT
   - Score the final article on the same criteria used for source articles
   - Compare to target threshold

3. COHERENCE CHECK
   - Does the article flow naturally?
   - Are transitions smooth?
   - Is the tone consistent?
   - Does it feel like one coherent piece (not Frankenstein'd together)?

## Output Schema

{{
  "passed": <boolean>,
  "blueprint_compliance": {{
    "headline_used": <boolean>,
    "structure_followed": <boolean>,
    "core_argument_present": <boolean>,
    "supporting_points_included": <float 0-1, what percentage>,
    "evidence_included": <float 0-1>,
    "phrases_preserved": <float 0-1>,
    "weaknesses_avoided": <boolean>,
    "compliance_score": <float 0-1>
  }},
  "quality_scores": {{
    "hook_strength": <1-10>,
    "argument_clarity": <1-10>,
    "evidence_quality": <1-10>,
    "structural_coherence": <1-10>,
    "originality": <1-10>,
    "memorability": <1-10>,
    "actionability": <1-10>,
    "overall": <float>
  }},
  "coherence_assessment": {{
    "flow_natural": <boolean>,
    "transitions_smooth": <boolean>,
    "tone_consistent": <boolean>,
    "feels_unified": <boolean>
  }},
  "issues": [
    "<specific issue 1>",
    "<specific issue 2>"
  ],
  "improvement_suggestions": [
    "<specific suggestion if failed>"
  ],
  "target_threshold": {target_threshold},
  "threshold_met": <boolean>
}}"""

    user_prompt = f"""Validate this synthesized article against its blueprint.

## Synthesized Article
{article}

## Blueprint It Should Follow
{json.dumps(blueprint.__dict__, indent=2)}

## Target Quality Threshold
The article should achieve an overall score of at least {target_threshold:.1f}

Evaluate and respond with the validation JSON."""

    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.2,  # Low temp for consistent judgment
        max_tokens=4000,
        verbose=verbose
    )
    
    # Filter out think tags from reasoning model output
    response = filter_think_tags(response)
    
    validation_data = json.loads(response)
    result = ValidationResult(**validation_data)
    
    if verbose:
        status = "✓ PASSED" if result.passed else "✗ FAILED"
        print(f"{status} - Overall score: {result.quality_scores['overall']:.1f} (threshold: {target_threshold:.1f})")
        if not result.passed and result.issues:
            print(f"  Issues identified: {len(result.issues)}")
            for issue in result.issues[:3]:  # Show first 3
                print(f"    - {issue}")
        print()
    
    return result


def synthesize_with_validation_loop(
    blueprint: SynthesisBlueprint,
    original_user_prompt: str,
    brand_guidelines: str,
    original_scores: List[ArticleScore],
    target_word_count: int = 1500,
    max_retries: int = 3,
    verbose: bool = False
) -> tuple[str, ValidationResult]:
    """
    Synthesize article with validation retry loop.
    
    Args:
        blueprint: SynthesisBlueprint
        original_user_prompt: Original topic/brief
        brand_guidelines: Company brand guidelines
        original_scores: Scores from source articles
        target_word_count: Desired article length
        max_retries: Maximum synthesis attempts
        verbose: Enable progress logging
        
    Returns:
        Tuple of (final_article, validation_result)
    """
    article = ""
    validation = None
    
    for attempt in range(1, max_retries + 1):
        if verbose and attempt > 1:
            print(f"  Retry attempt {attempt}/{max_retries}...")
        
        # Generate article
        article = synthesize_final_article(
            blueprint=blueprint,
            original_user_prompt=original_user_prompt,
            brand_guidelines=brand_guidelines,
            target_word_count=target_word_count,
            verbose=verbose
        )
        
        # Validate
        validation = validate_synthesized_article(
            article=article,
            blueprint=blueprint,
            original_scores=original_scores,
            verbose=verbose
        )
        
        if validation.passed:
            if verbose:
                print(f"✓ Validation passed on attempt {attempt}")
            break
        
        # Add feedback to blueprint for next attempt
        if attempt < max_retries:
            feedback = f"\n\nPREVIOUS ATTEMPT FAILED. Issues: {', '.join(validation.issues[:3])}"
            blueprint.synthesis_notes += feedback
    
    return article, validation


# ============================================================================
# PIPELINE ORCHESTRATION
# Purpose: Coordinate all 5 stages and handle errors
# ============================================================================

class ArticleSynthesisPipeline:
    """Orchestrates the complete 5-stage synthesis pipeline."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.artifacts = {}  # Store intermediate results
    
    def run(
        self,
        candidates: List[ArticleCandidate],
        original_user_prompt: str,
        brand_guidelines: str,
        target_word_count: int = 1500,
        scoring_votes: int = 3,
        max_synthesis_retries: int = 3
    ) -> Dict:
        """
        Execute complete pipeline.
        
        Args:
            candidates: List of generated article candidates
            original_user_prompt: Original topic/brief
            brand_guidelines: Company brand guidelines
            target_word_count: Desired final article length
            scoring_votes: Number of voting rounds for scoring
            max_synthesis_retries: Max synthesis attempts on validation failure
            
        Returns:
            Dict with final_article, validation, and all intermediate artifacts
        """
        try:
            # STAGE 1: EXTRACT
            cards = extract_all_article_cards(candidates, self.verbose)
            self.artifacts['cards'] = cards
            
            # STAGE 2: SCORE
            scores = score_all_cards_with_voting(
                cards,
                votes=scoring_votes,
                verbose=self.verbose
            )
            self.artifacts['scores'] = scores
            
            # STAGE 3: SELECT
            blueprint = select_best_elements(cards, scores, self.verbose)
            self.artifacts['blueprint'] = blueprint
            
            # STAGE 4 & 5: SYNTHESIZE + VALIDATE (with retry loop)
            final_article, validation = synthesize_with_validation_loop(
                blueprint=blueprint,
                original_user_prompt=original_user_prompt,
                brand_guidelines=brand_guidelines,
                original_scores=scores,
                target_word_count=target_word_count,
                max_retries=max_synthesis_retries,
                verbose=self.verbose
            )
            
            return {
                'final_article': final_article,
                'validation': validation,
                'artifacts': self.artifacts,
                'num_source_articles': len(candidates)
            }
            
        except Exception as e:
            if self.verbose:
                print(f"\n{'='*80}")
                print(f"PIPELINE ERROR: {e}")
                print(f"{'='*80}\n")
            raise


def save_pipeline_artifacts(
    result: Dict,
    output_base: str,
    verbose: bool = False
):
    """
    Save all pipeline artifacts to organized directory structure.
    
    Args:
        result: Pipeline result dictionary
        output_base: Base filename for outputs
        verbose: Enable progress logging
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = create_output_directory(output_base)
    
    # Save final synthesized article
    final_path = output_dir / f"{output_base}_FINAL.md"
    final_path.write_text(result['final_article'], encoding='utf-8')
    if verbose:
        print(f"✓ Final article saved: {final_path}")
    
    # Save validation report
    validation_path = output_dir / f"{output_base}_validation.json"
    validation_path.write_text(
        json.dumps(result['validation'].__dict__, indent=2),
        encoding='utf-8'
    )
    if verbose:
        print(f"✓ Validation report saved: {validation_path}")
    
    # Save all artifacts (cards, scores, blueprint)
    artifacts_path = output_dir / f"{output_base}_pipeline_artifacts.json"
    
    # Convert dataclass objects to dicts for JSON serialization
    serializable_artifacts = {
        'cards': [c.__dict__ for c in result['artifacts']['cards']],
        'scores': [s.__dict__ for s in result['artifacts']['scores']],
        'blueprint': result['artifacts']['blueprint'].__dict__,
        'metadata': {
            'num_source_articles': result['num_source_articles'],
            'timestamp': timestamp
        }
    }
    
    artifacts_path.write_text(
        json.dumps(serializable_artifacts, indent=2),
        encoding='utf-8'
    )
    if verbose:
        print(f"✓ Pipeline artifacts saved: {artifacts_path}")


def main():
    """Main function with integrated synthesis pipeline."""
    parser = argparse.ArgumentParser(
        description="Generate marketing blog posts with optional synthesis pipeline. Can run multiple iterations with numbered output files."
    )
    
    # Existing generation arguments
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature (default: 0.7)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=40000,
        help="Maximum tokens to generate (default: 4000)"
    )
    parser.add_argument(
        "--output",
        help="Base filename (without extension) to save LLM responses. Will create numbered markdown files when using multiple iterations."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of times to run the LLM generation routine (default: 1). Creates numbered output files when > 1."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--retry-count",
        type=int,
        default=3,
        help="Number of API call retries (default: 3)"
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="Delay between retries in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--filter-think",
        action="store_true",
        help="Filter out content between <think> tags from the LLM response"
    )
    parser.add_argument(
        "--topic-file",
        help="Path to file containing the specific blog post topic/idea"
    )
    
    # New synthesis pipeline arguments
    parser.add_argument(
        "--enable-synthesis",
        action="store_true",
        help="Enable 5-stage synthesis pipeline (requires --iterations >= 10)"
    )
    parser.add_argument(
        "--synthesis-votes",
        type=int,
        default=3,
        help="Number of scoring votes in synthesis pipeline (default: 3)"
    )
    parser.add_argument(
        "--synthesis-retries",
        type=int,
        default=3,
        help="Max synthesis attempts on validation failure (default: 3)"
    )
    parser.add_argument(
        "--target-word-count",
        type=int,
        default=1500,
        help="Target word count for synthesized article (default: 1500)"
    )
    parser.add_argument(
        "--cleanup-old",
        type=int,
        default=0,
        help="Remove output directories older than N days (0 = disabled)"
    )
    
    args = parser.parse_args()
    
    # Validation for synthesis pipeline
    if args.enable_synthesis and args.iterations < 10:
        print("Warning: Synthesis pipeline recommended with --iterations >= 10")
        print("Proceeding anyway...")
    
    # Handle cleanup if requested
    if args.cleanup_old > 0:
        if args.verbose:
            print(f"Cleaning up output directories older than {args.cleanup_old} days...")
        cleanup_old_outputs(args.cleanup_old)
        return 0
    
    try:
        # Load environment variables
        if args.verbose:
            print("Loading environment variables...")
        load_environment()
        
        if args.verbose:
            print(f"API Base URL: {os.getenv('OPENAI_API_BASE')}")
            print(f"Model Name: {os.getenv('OPENAI_MODEL_NAME')}")
            print("Using built-in system and user prompts for Construkted Reality marketing content")
        
        # Build prompts
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(args.topic_file)
        
        if args.verbose:
            print("Built system and user prompts from reference context files")
        
        # ====================================================================
        # PHASE 1: GENERATION (existing code, modified to store candidates)
        # ====================================================================
        
        candidates = []
        
        for iteration in range(1, args.iterations + 1):
            if args.verbose:
                print(f"\nGenerating candidate {iteration}/{args.iterations}...")
            
            # Send to LLM
            response = send_to_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                retry_count=args.retry_count,
                retry_delay=args.retry_delay,
                verbose=args.verbose
            )
            
            # Apply think tag filtering if requested
            if args.filter_think:
                if args.verbose:
                    print("Filtering out content between <think> tags...")
                response = filter_think_tags(response)
            
            # Store candidate in memory
            candidate = ArticleCandidate(
                article_id=iteration,
                content=response,
                word_count=len(response.split()),
                generation_timestamp=time.time()
            )
            candidates.append(candidate)
            
            # Save individual candidate files to organized structure
            if args.output:
                output_dir = create_output_directory(args.output)
                
                if args.iterations == 1:
                    filename = output_dir / f"{args.output}.md"
                else:
                    filename = output_dir / "candidates" / f"{args.output}_candidate_{iteration:02d}.md"
                
                filename.write_text(
                    response + f"\n\n---\n**Word Count: {candidate.word_count}**",
                    encoding='utf-8'
                )
                if args.verbose:
                    print(f"Candidate saved: {filename}")
        
        # ====================================================================
        # PHASE 2: SYNTHESIS PIPELINE (new code)
        # ====================================================================
        
        if args.enable_synthesis:
            print(f"\n{'='*80}")
            print("STARTING SYNTHESIS PIPELINE")
            print(f"{'='*80}\n")
            
            pipeline = ArticleSynthesisPipeline(verbose=args.verbose)
            
            result = pipeline.run(
                candidates=candidates,
                original_user_prompt=user_prompt,
                brand_guidelines=system_prompt,
                target_word_count=args.target_word_count,
                scoring_votes=args.synthesis_votes,
                max_synthesis_retries=args.synthesis_retries
            )
            
            # Save all pipeline outputs
            if args.output:
                save_pipeline_artifacts(
                    result,
                    args.output,
                    verbose=args.verbose
                )
            
            # Print final summary
            print(f"\n{'='*80}")
            print("SYNTHESIS PIPELINE COMPLETE")
            print(f"{'='*80}")
            print(f"Source articles: {result['num_source_articles']}")
            print(f"Validation passed: {result['validation'].passed}")
            print(f"Final article quality score: {result['validation'].quality_scores['overall']:.1f}/10")
            print(f"{'='*80}\n")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())