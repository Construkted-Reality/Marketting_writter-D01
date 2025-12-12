#!/usr/bin/env python3
"""
Simple script to generate marketing blog posts using a local OpenAI compliant API endpoint.
Based on the reference implementation pattern from cr_content_pipeline.py
Uses built-in system and user prompts for Construkted Reality marketing content.

Enhanced with 6-stage article synthesis pipeline: CANDIDATES → EXTRACT → SCORE → SELECT → SYNTHESIZE → VALIDATE

Includes comprehensive metrics tracking for words, tokens, and execution times.
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
# METRICS TRACKING SYSTEM
# ============================================================================

@dataclass
class StageMetrics:
    """Metrics for a single pipeline stage."""
    stage_name: str
    input_words: int = 0
    input_tokens: int = 0
    output_words: int = 0
    output_tokens: int = 0
    execution_time: float = 0.0
    llm_calls: int = 0
    
    def add_input(self, text: str):
        """Add input text and calculate tokens."""
        words = len(text.split())
        tokens = int(words / 0.75)  # Simple token estimator: word count / 0.75
        self.input_words += words
        self.input_tokens += tokens
    
    def add_output(self, text: str):
        """Add output text and calculate tokens."""
        words = len(text.split())
        tokens = int(words / 0.75)  # Simple token estimator: word count / 0.75
        self.output_words += words
        self.output_tokens += tokens
    
    def add_execution_time(self, duration: float):
        """Add execution time."""
        self.execution_time += duration
    
    def get_total_words(self) -> int:
        """Get total words (input + output)."""
        return self.input_words + self.output_words
    
    def get_total_tokens(self) -> int:
        """Get total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

@dataclass
class PipelineMetrics:
    """Complete metrics for the entire pipeline execution."""
    candidates_stage: StageMetrics = field(default_factory=lambda: StageMetrics("CANDIDATES"))
    extract_stage: StageMetrics = field(default_factory=lambda: StageMetrics("EXTRACT"))
    score_stage: StageMetrics = field(default_factory=lambda: StageMetrics("SCORE"))
    select_stage: StageMetrics = field(default_factory=lambda: StageMetrics("SELECT"))
    synthesize_stage: StageMetrics = field(default_factory=lambda: StageMetrics("SYNTHESIZE"))
    validate_stage: StageMetrics = field(default_factory=lambda: StageMetrics("VALIDATE"))
    total_execution_time: float = 0.0
    
    def get_stage_metrics(self) -> List[StageMetrics]:
        """Get list of all stage metrics."""
        return [
            self.candidates_stage,
            self.extract_stage,
            self.score_stage,
            self.select_stage,
            self.synthesize_stage,
            self.validate_stage
        ]
    
    def get_total_words_all_stages(self) -> int:
        """Get total words across all stages."""
        return sum(stage.get_total_words() for stage in self.get_stage_metrics())
    
    def get_total_tokens_all_stages(self) -> int:
        """Get total tokens across all stages."""
        return sum(stage.get_total_tokens() for stage in self.get_stage_metrics())
    
    def get_total_llm_calls(self) -> int:
        """Get total LLM calls across all stages."""
        return sum(stage.llm_calls for stage in self.get_stage_metrics())
    
    def print_comprehensive_summary(self):
        """Print detailed metrics summary."""
        print(f"\n{'='*100}")
        print("COMPREHENSIVE PIPELINE METRICS SUMMARY")
        print(f"{'='*100}")
        
        # Stage-by-stage breakdown
        for stage in self.get_stage_metrics():
            if stage.llm_calls > 0:  # Only show stages that executed
                print(f"\n{stage.stage_name} STAGE:")
                print(f"  LLM Calls: {stage.llm_calls}")
                print(f"  Input: {stage.input_words:,} words ({stage.input_tokens:,} tokens)")
                print(f"  Output: {stage.output_words:,} words ({stage.output_tokens:,} tokens)")
                print(f"  Total: {stage.get_total_words():,} words ({stage.get_total_tokens():,} tokens)")
                print(f"  Execution Time: {stage.execution_time:.2f} seconds")
        
        # Totals
        total_words = self.get_total_words_all_stages()
        total_tokens = self.get_total_tokens_all_stages()
        total_calls = self.get_total_llm_calls()
        
        print(f"\n{'='*100}")
        print("OVERALL TOTALS:")
        print(f"{'='*100}")
        print(f"Total LLM Calls: {total_calls}")
        print(f"Total Words Processed: {total_words:,}")
        print(f"Total Tokens Processed: {total_tokens:,}")
        print(f"Total Execution Time: {self.total_execution_time:.2f} seconds")
        if total_calls > 0:
            print(f"Average Time per LLM Call: {self.total_execution_time/total_calls:.2f} seconds")
        print(f"{'='*100}\n")

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


def extract_json_from_response(text: str) -> str:
    """
    Extract JSON from LLM response, handling markdown code blocks.
    
    Args:
        text: The text potentially containing JSON
        
    Returns:
        Extracted JSON string
    """
    # Remove think tags first
    text = filter_think_tags(text)
    
    # Try to extract JSON from markdown code blocks
    # Pattern for ```json ... ``` or ``` ... ```
    code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
    match = re.search(code_block_pattern, text, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    
    # If no code block found, return the text as-is (might already be pure JSON)
    return text.strip()


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
# PIPELINE STAGE 2: EXTRACT
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
    system_prompt = read_reference_file("prompts/pipeline_stage2_extract_system.md")

    user_prompt = f"""Extract the article card for Article #{article_id}.

<article>
{article_content}
</article>

Respond with only the JSON object."""

    for attempt in range(retry_count):
        try:
            # Prepare input text for metrics tracking
            input_text = system_prompt + "\n\n" + user_prompt
            
            # Send to LLM with timing
            llm_start_time = time.time()
            response = send_to_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,  # Low temp for consistent extraction
                max_tokens=4000,
                verbose=verbose
            )
            llm_end_time = time.time()
            execution_time = llm_end_time - llm_start_time
            
            # Extract JSON from response (handles markdown code blocks and think tags)
            json_str = extract_json_from_response(response)
            
            # Parse and validate JSON
            card_data = json.loads(json_str)
            
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
            
            # Track LLM call metrics
            track_llm_call("EXTRACT", input_text, json_str, execution_time)
            
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
        print("PIPELINE STAGE 2: EXTRACT")
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
# PIPELINE STAGE 3: SCORE
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
    system_prompt = read_reference_file("prompts/pipeline_stage3_score_system.md")

    user_prompt = f"""Score the following article card against the provided criteria.

## Article Card
{json.dumps(card.__dict__, indent=2)}

## Scoring Criteria
{json.dumps(criteria, indent=2)}

Respond with only the JSON object containing scores and justifications."""

    # Prepare input text for metrics tracking
    input_text = system_prompt + "\n\n" + user_prompt
    
    # Send to LLM with timing
    llm_start_time = time.time()
    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.2,  # Low temp for consistent evaluation
        max_tokens=4000,
        verbose=verbose
    )
    llm_end_time = time.time()
    execution_time = llm_end_time - llm_start_time
    
    # Extract JSON from response (handles markdown code blocks and think tags)
    json_str = extract_json_from_response(response)
    
    score_data = json.loads(json_str)
    
    # Calculate weighted overall score
    total_score = 0.0
    for criterion_name, criterion_info in criteria.items():
        if criterion_name in score_data["scores"]:
            score_value = score_data["scores"][criterion_name]["score"]
            weight = criterion_info["weight"]
            total_score += score_value * weight
    
    score_data["overall_score"] = round(total_score, 2)
    
    # Track LLM call metrics
    track_llm_call("SCORE", input_text, json_str, execution_time)
    
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
        print("PIPELINE STAGE 3: SCORE")
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
# PIPELINE STAGE 4: SELECT
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
        print("PIPELINE STAGE 4: SELECT")
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
    
    system_prompt = read_reference_file("prompts/pipeline_stage4_select_system.md")

    user_prompt = f"""Analyze these {len(cards)} article drafts and create a synthesis blueprint.

## Article Summaries and Scores
{json.dumps(analysis_input, indent=2)}

Create a synthesis blueprint that combines the best elements into one superior article.

Respond with only the JSON object."""

    # Prepare input text for metrics tracking
    input_text = system_prompt + "\n\n" + user_prompt
    
    # Send to LLM with timing
    llm_start_time = time.time()
    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.4,  # Some analytical creativity
        max_tokens=6000,
        verbose=verbose
    )
    llm_end_time = time.time()
    execution_time = llm_end_time - llm_start_time
    
    # Extract JSON from response (handles markdown code blocks and think tags)
    json_str = extract_json_from_response(response)
    
    # Debug: Check if response is empty after extraction
    if not json_str or json_str.isspace():
        raise ValueError("Empty response after filtering. LLM may have only returned thinking content or invalid format.")
    
    try:
        blueprint_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Provide more context in error message
        if verbose:
            print(f"\nFailed to parse JSON response:")
            print(f"Extracted JSON preview: {json_str[:500]}")
        raise ValueError(f"Invalid JSON response from LLM: {e}. JSON preview: {json_str[:200]}")
    
    # Create blueprint with all required fields including confidence
    blueprint_dict = blueprint_data["synthesis_blueprint"].copy()
    blueprint_dict["confidence"] = blueprint_data["confidence"]
    
    blueprint = SynthesisBlueprint(**blueprint_dict)
    
    # Track LLM call metrics
    track_llm_call("SELECT", input_text, json_str, execution_time)
    
    if verbose:
        print(f"✓ Blueprint created. Confidence: {blueprint.confidence['level']}\n")
    
    return blueprint


# ============================================================================
# PIPELINE STAGE 5: SYNTHESIZE
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
        print("PIPELINE STAGE 5: SYNTHESIZE")
        print(f"{'='*80}")
        print(f"Generating final article from blueprint...")
    
    # Load prompt template and substitute variables
    prompt_template = read_reference_file("prompts/pipeline_stage5_synthesize_system.md")
    system_prompt = prompt_template.format(
        brand_guidelines=brand_guidelines,
        target_word_count=target_word_count
    )

    user_prompt = f"""Write a marketing blog article following this synthesis blueprint.

## Original Brief
{original_user_prompt}

## Synthesis Blueprint
{json.dumps(blueprint.__dict__, indent=2)}

Write the complete article now. Start directly with the headline."""

    # Prepare input text for metrics tracking
    input_text = system_prompt + "\n\n" + user_prompt
    
    # Send to LLM with timing
    llm_start_time = time.time()
    article = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.7,  # Higher temp for creative writing
        max_tokens=8000,
        verbose=verbose
    )
    llm_end_time = time.time()
    execution_time = llm_end_time - llm_start_time
    
    # Filter out think tags from reasoning model output
    article = filter_think_tags(article)
    
    # Track LLM call metrics
    track_llm_call("SYNTHESIZE", input_text, article, execution_time)
    
    if verbose:
        word_count = len(article.split())
        print(f"✓ Synthesized article generated ({word_count} words)\n")
    
    return article


# ============================================================================
# PIPELINE STAGE 6: VALIDATE
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
        print("PIPELINE STAGE 6: VALIDATE")
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

    # Prepare input text for metrics tracking
    input_text = system_prompt + "\n\n" + user_prompt
    
    # Send to LLM with timing
    llm_start_time = time.time()
    response = send_to_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.2,  # Low temp for consistent judgment
        max_tokens=4000,
        verbose=verbose
    )
    llm_end_time = time.time()
    execution_time = llm_end_time - llm_start_time
    
    # Extract JSON from response (handles markdown code blocks and think tags)
    json_str = extract_json_from_response(response)
    
    validation_data = json.loads(json_str)
    result = ValidationResult(**validation_data)
    
    # Track LLM call metrics
    track_llm_call("VALIDATE", input_text, json_str, execution_time)
    
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
) -> tuple[str, ValidationResult | None]:
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
            # STAGE 2: EXTRACT
            cards = extract_all_article_cards(candidates, self.verbose)
            self.artifacts['cards'] = cards
            
            # STAGE 3: SCORE
            scores = score_all_cards_with_voting(
                cards,
                votes=scoring_votes,
                verbose=self.verbose
            )
            self.artifacts['scores'] = scores
            
            # STAGE 4: SELECT
            blueprint = select_best_elements(cards, scores, self.verbose)
            self.artifacts['blueprint'] = blueprint
            
            # STAGE 5 & 6: SYNTHESIZE + VALIDATE (with retry loop)
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


# ============================================================================
# GLOBAL METRICS TRACKING
# ============================================================================

# Global metrics object to track all pipeline stages
pipeline_metrics = PipelineMetrics()

def track_llm_call(stage_name: str, input_text: str, output_text: str, execution_time: float):
    """Track a single LLM call with timing and token metrics."""
    stage_mapping = {
        "CANDIDATES": pipeline_metrics.candidates_stage,
        "EXTRACT": pipeline_metrics.extract_stage,
        "SCORE": pipeline_metrics.score_stage,
        "SELECT": pipeline_metrics.select_stage,
        "SYNTHESIZE": pipeline_metrics.synthesize_stage,
        "VALIDATE": pipeline_metrics.validate_stage
    }
    
    if stage_name in stage_mapping:
        stage = stage_mapping[stage_name]
        stage.add_input(input_text)
        stage.add_output(output_text)
        stage.add_execution_time(execution_time)
        stage.llm_calls += 1

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
        #system_prompt = build_system_prompt()

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

        #user_prompt = build_user_prompt(args.topic_file)
        user_prompt = read_reference_file(args.topic_file)
        
        if args.verbose:
            print("Built system and user prompts from reference context files")
        
        # ====================================================================
        # STAGE 1: Generation of candidate articles
        # ====================================================================
        
        candidates = []
        stage_start_time = time.time()
        
        for iteration in range(1, args.iterations + 1):
            if args.verbose:
                print(f"\nGenerating candidate {iteration}/{args.iterations}...")
            
            # Prepare input text for metrics tracking
            input_text = system_prompt + "\n\n" + user_prompt
            
            # Send to LLM with timing
            llm_start_time = time.time()
            response = send_to_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                retry_count=args.retry_count,
                retry_delay=args.retry_delay,
                verbose=args.verbose
            )
            llm_end_time = time.time()
            execution_time = llm_end_time - llm_start_time
            
            # Apply think tag filtering if requested
            if args.filter_think:
                if args.verbose:
                    print("Filtering out content between <think> tags...")
                response = filter_think_tags(response)
            
            # Track LLM call metrics
            track_llm_call("CANDIDATES", input_text, response, execution_time)
            
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
        
        # Add total execution time for candidates stage
        stage_end_time = time.time()
        pipeline_metrics.candidates_stage.add_execution_time(stage_end_time - stage_start_time)
        
        # ====================================================================
        # STAGES 2-6: SYNTHESIS PIPELINE
        # ====================================================================
        
        if args.enable_synthesis:
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
        
        # Track total execution time
        total_end_time = time.time()
        pipeline_metrics.total_execution_time = total_end_time - stage_start_time
        
        # Print comprehensive metrics summary
        pipeline_metrics.print_comprehensive_summary()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())