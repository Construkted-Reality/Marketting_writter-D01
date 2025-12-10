# Article Synthesis Pipeline: Complete Implementation Guide

## Overview

This guide implements a pipeline for generating high-quality marketing blog posts by:
1. Generating multiple article candidates
2. Extracting structured representations
3. Scoring on multiple criteria
4. Selecting best elements
5. Synthesizing a final article
6. Validating quality

Each step is **stateless**—agents receive only what they need for their specific task.

---

## Architecture Principles

### Key Ideas
- **No history accumulation**: Each agent sees only current state, not conversation history
- **Strict output parsing**: Malformed outputs are rejected and retried (syntax errors signal logic errors)
- **Voting/sampling**: Multiple generations improve reliability

### Applied to Creative Writing
- **State = structured data**, not raw articles
- **Decompose quality** into measurable dimensions
- **Recombine best elements** rather than picking a single winner

---

## Step 1: EXTRACT

### Purpose
Convert each full article (~5000 words) into a compressed "Article Card" (~400-600 words) that captures its essence in a structured format.

### Python Implementation Notes

```python
import json
from openai import OpenAI  # or anthropic, depending on your provider

def extract_article_card(article_text: str, article_id: int, client) -> dict:
    """
    Extract structured card from a single article.
    Run this in parallel for all 10-15 articles.
    """
    
    system_prompt = EXTRACT_SYSTEM_PROMPT
    user_prompt = EXTRACT_USER_PROMPT_TEMPLATE.format(
        article_text=article_text,
        article_id=article_id
    )
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # Small model is fine for extraction
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,  # Low temp for consistent extraction
        response_format={"type": "json_object"}
    )
    
    # Foundational principle: strict parsing, reject malformed outputs
    try:
        card = json.loads(response.choices[0].message.content)
        validate_card_schema(card)  # Raises if invalid
        return card
    except (json.JSONDecodeError, ValidationError) as e:
        # Retry on failure - syntax error = logic error
        return extract_article_card(article_text, article_id, client)
```

### System Prompt: EXTRACT_SYSTEM_PROMPT

```
You are a content analysis agent. Your job is to extract the essential elements from a marketing blog article into a structured format.

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
- If the article lacks something (e.g., no statistics), note it in weaknesses
```

### User Prompt Template: EXTRACT_USER_PROMPT_TEMPLATE

```
Extract the article card for Article #{article_id}.

<article>
{article_text}
</article>

Respond with only the JSON object.
```

### Output Schema (for validation)

```python
EXTRACT_SCHEMA = {
    "type": "object",
    "required": [
        "article_id",
        "headline_candidates", 
        "opening_hook",
        "core_argument",
        "key_points",
        "memorable_phrases",
        "structural_approach",
        "evidence_used",
        "tone",
        "target_audience_signals",
        "weaknesses"
    ],
    "properties": {
        "article_id": {"type": "integer"},
        "headline_candidates": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3
        },
        "opening_hook": {"type": "string"},
        "core_argument": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 7
        },
        "memorable_phrases": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5
        },
        "structural_approach": {"type": "string"},
        "evidence_used": {
            "type": "array",
            "items": {"type": "string"}
        },
        "tone": {"type": "string"},
        "target_audience_signals": {"type": "string"},
        "weaknesses": {
            "type": "array",
            "items": {"type": "string"}
        },
        "word_count_estimate": {"type": "integer"}
    }
}
```

---

## Step 2: SCORE

### Purpose
Evaluate each article card on specific quality dimensions. This produces a scoring matrix that enables intelligent selection.

### Python Implementation Notes

```python
def score_article_card(card: dict, scoring_criteria: dict, client) -> dict:
    """
    Score a single article card on all criteria.
    Returns scores + justifications.
    """
    
    system_prompt = SCORE_SYSTEM_PROMPT
    user_prompt = SCORE_USER_PROMPT_TEMPLATE.format(
        article_card=json.dumps(card, indent=2),
        criteria=json.dumps(scoring_criteria, indent=2)
    )
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)


def score_all_cards_with_voting(cards: list, criteria: dict, client, votes: int = 3) -> list:
    """
    Voting: Score each card multiple times, average the scores.
    This reduces variance from stochastic scoring.
    """
    all_scores = []
    
    for card in cards:
        card_votes = []
        for _ in range(votes):
            score = score_article_card(card, criteria, client)
            card_votes.append(score)
        
        # Average the numeric scores across votes
        averaged = average_score_votes(card_votes)
        all_scores.append(averaged)
    
    return all_scores
```

### System Prompt: SCORE_SYSTEM_PROMPT

```
You are a content quality evaluator. You will receive an article card (a structured summary of a blog article) and a set of scoring criteria.

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
}
```

### User Prompt Template: SCORE_USER_PROMPT_TEMPLATE

```
Score the following article card against the provided criteria.

## Article Card
{article_card}

## Scoring Criteria
{criteria}

Respond with only the JSON object containing scores and justifications.
```

### Scoring Criteria Definition

```python
SCORING_CRITERIA = {
    "hook_strength": {
        "description": "How compelling is the opening? Does it create curiosity, tension, or immediate value?",
        "weight": 0.15,
        "evaluate_from": "opening_hook"
    },
    "argument_clarity": {
        "description": "Is the core message immediately clear? Can you summarize it in one sentence?",
        "weight": 0.20,
        "evaluate_from": "core_argument"
    },
    "evidence_quality": {
        "description": "Are claims supported with specifics? Statistics, examples, case studies?",
        "weight": 0.15,
        "evaluate_from": ["key_points", "evidence_used"]
    },
    "structural_coherence": {
        "description": "Does the structure serve the argument? Is there a logical flow?",
        "weight": 0.15,
        "evaluate_from": "structural_approach"
    },
    "originality": {
        "description": "Does it offer a fresh angle? Or is it generic advice anyone could write?",
        "weight": 0.15,
        "evaluate_from": ["core_argument", "key_points"]
    },
    "memorability": {
        "description": "Are there phrases or ideas that stick? Would someone quote this?",
        "weight": 0.10,
        "evaluate_from": "memorable_phrases"
    },
    "actionability": {
        "description": "Does the reader know what to do after reading? Is there a clear next step?",
        "weight": 0.10,
        "evaluate_from": "key_points"
    }
}
```

### Output Schema (for validation)

```python
SCORE_SCHEMA = {
    "type": "object",
    "required": ["article_id", "scores", "overall_score", "standout_strengths", "critical_weaknesses"],
    "properties": {
        "article_id": {"type": "integer"},
        "scores": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["score", "justification"],
                "properties": {
                    "score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "justification": {"type": "string"}
                }
            }
        },
        "overall_score": {"type": "number"},
        "standout_strengths": {"type": "array", "items": {"type": "string"}},
        "critical_weaknesses": {"type": "array", "items": {"type": "string"}}
    }
}
```

---

## Step 3: SELECT

### Purpose
Analyze the scoring matrix to identify which elements from which articles should be combined. This is the "recombination" step that makes the output better than any single generation.

### Python Implementation Notes

```python
def select_best_elements(cards: list, scores: list, client) -> dict:
    """
    Analyze all cards and scores to select best elements for synthesis.
    This agent sees ALL cards (compressed) and ALL scores.
    """
    
    # Build the analysis input
    analysis_input = []
    for card, score in zip(cards, scores):
        analysis_input.append({
            "article_id": card["article_id"],
            "headline_candidates": card["headline_candidates"],
            "opening_hook": card["opening_hook"][:200] + "...",  # Truncate for context
            "core_argument": card["core_argument"],
            "key_points": card["key_points"],
            "structural_approach": card["structural_approach"],
            "memorable_phrases": card["memorable_phrases"],
            "scores": score["scores"],
            "overall_score": score["overall_score"]
        })
    
    system_prompt = SELECT_SYSTEM_PROMPT
    user_prompt = SELECT_USER_PROMPT_TEMPLATE.format(
        analysis_input=json.dumps(analysis_input, indent=2),
        num_articles=len(cards)
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",  # Use stronger model for this analytical step
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)
```

### System Prompt: SELECT_SYSTEM_PROMPT

```
You are a content strategy agent. You will receive summaries and scores for multiple article drafts on the same topic.

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
}
```

### User Prompt Template: SELECT_USER_PROMPT_TEMPLATE

```
Analyze these {num_articles} article drafts and create a synthesis blueprint.

## Article Summaries and Scores
{analysis_input}

Create a synthesis blueprint that combines the best elements into one superior article.

Respond with only the JSON object.
```

### Output Schema (for validation)

```python
SELECT_SCHEMA = {
    "type": "object",
    "required": ["synthesis_blueprint", "confidence"],
    "properties": {
        "synthesis_blueprint": {
            "type": "object",
            "required": [
                "selected_headline",
                "selected_opening", 
                "selected_structure",
                "selected_arguments",
                "selected_evidence",
                "phrases_to_preserve",
                "elements_to_avoid",
                "synthesis_notes"
            ]
        },
        "confidence": {
            "type": "object",
            "required": ["level", "concerns"],
            "properties": {
                "level": {"type": "string", "enum": ["high", "medium", "low"]},
                "concerns": {"type": "array", "items": {"type": "string"}}
            }
        }
    }
}
```

---

## Step 4: SYNTHESIZE

### Purpose
Generate the final article using ONLY the synthesis blueprint. This agent never sees the original articles—it works from the curated specification.

### Python Implementation Notes

```python
def synthesize_article(
    blueprint: dict,
    original_prompt: str,
    brand_guidelines: str,
    client,
    target_word_count: int = 1500
) -> str:
    """
    Generate final article from synthesis blueprint.
    
    Key: This agent sees the BLUEPRINT, not the original articles.
    The blueprint IS the state.
    """
    
    system_prompt = SYNTHESIZE_SYSTEM_PROMPT.format(
        brand_guidelines=brand_guidelines,
        target_word_count=target_word_count
    )
    
    user_prompt = SYNTHESIZE_USER_PROMPT_TEMPLATE.format(
        original_prompt=original_prompt,
        blueprint=json.dumps(blueprint, indent=2)
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",  # Use strong model for final synthesis
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,  # Higher temp for creative writing
        max_tokens=4000
    )
    
    return response.choices[0].message.content
```

### System Prompt: SYNTHESIZE_SYSTEM_PROMPT

```
You are a professional content writer. You will receive a synthesis blueprint that specifies exactly what elements to include in a marketing blog article.

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

[Article body with natural paragraph breaks]
```

### User Prompt Template: SYNTHESIZE_USER_PROMPT_TEMPLATE

```
Write a marketing blog article following this synthesis blueprint.

## Original Brief
{original_prompt}

## Synthesis Blueprint
{blueprint}

Write the complete article now. Start directly with the headline.
```

---

## Step 5: VALIDATE

### Purpose
Check the synthesized article against the blueprint and quality criteria. This is a verification step that can trigger regeneration if quality is insufficient.

### Python Implementation Notes

```python
def validate_article(
    article: str,
    blueprint: dict,
    original_scores: list,
    client
) -> dict:
    """
    Validate that the synthesized article meets quality standards.
    Returns pass/fail with specific issues if failed.
    """
    
    # Calculate the target quality threshold
    # Final article should score higher than the average of source articles
    avg_source_score = sum(s["overall_score"] for s in original_scores) / len(original_scores)
    target_threshold = avg_source_score + 0.5  # Should beat the average
    
    system_prompt = VALIDATE_SYSTEM_PROMPT
    user_prompt = VALIDATE_USER_PROMPT_TEMPLATE.format(
        article=article,
        blueprint=json.dumps(blueprint, indent=2),
        target_threshold=target_threshold
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)


def synthesis_with_retry(blueprint, original_prompt, brand_guidelines, client, max_retries=3):
    """
    Synthesize with validation loop. Retry if validation fails.
    """
    for attempt in range(max_retries):
        article = synthesize_article(blueprint, original_prompt, brand_guidelines, client)
        validation = validate_article(article, blueprint, original_scores, client)
        
        if validation["passed"]:
            return article, validation
        
        # Add feedback to next synthesis attempt
        blueprint["synthesis_notes"] += f"\n\nPREVIOUS ATTEMPT FAILED. Issues: {validation['issues']}"
    
    # Return best attempt if all retries fail
    return article, validation
```

### System Prompt: VALIDATE_SYSTEM_PROMPT

```
You are a content quality assurance agent. You will receive:
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

{
  "passed": <boolean>,
  "blueprint_compliance": {
    "headline_used": <boolean>,
    "structure_followed": <boolean>,
    "core_argument_present": <boolean>,
    "supporting_points_included": <float 0-1, what percentage>,
    "evidence_included": <float 0-1>,
    "phrases_preserved": <float 0-1>,
    "weaknesses_avoided": <boolean>,
    "compliance_score": <float 0-1>
  },
  "quality_scores": {
    "hook_strength": <1-10>,
    "argument_clarity": <1-10>,
    "evidence_quality": <1-10>,
    "structural_coherence": <1-10>,
    "originality": <1-10>,
    "memorability": <1-10>,
    "actionability": <1-10>,
    "overall": <float>
  },
  "coherence_assessment": {
    "flow_natural": <boolean>,
    "transitions_smooth": <boolean>,
    "tone_consistent": <boolean>,
    "feels_unified": <boolean>
  },
  "issues": [
    "<specific issue 1>",
    "<specific issue 2>"
  ],
  "improvement_suggestions": [
    "<specific suggestion if failed>"
  ],
  "target_threshold": <float>,
  "threshold_met": <boolean>
}
```

### User Prompt Template: VALIDATE_USER_PROMPT_TEMPLATE

```
Validate this synthesized article against its blueprint.

## Synthesized Article
{article}

## Blueprint It Should Follow
{blueprint}

## Target Quality Threshold
The article should achieve an overall score of at least {target_threshold}

Evaluate and respond with the validation JSON.
```

---

## Complete Pipeline Orchestration

```python
import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from openai import OpenAI

class ArticleSynthesisPipeline:
    def __init__(self, client: OpenAI, brand_guidelines: str):
        self.client = client
        self.brand_guidelines = brand_guidelines
    
    def run(
        self,
        articles: List[str],
        original_prompt: str,
        target_word_count: int = 1500,
        extraction_votes: int = 1,
        scoring_votes: int = 3,
        max_synthesis_retries: int = 3
    ) -> Dict:
        """
        Run the complete pipeline.
        
        Args:
            articles: List of 10-15 generated article texts
            original_prompt: The original brief/prompt used to generate articles
            target_word_count: Desired length of final article
            extraction_votes: How many times to extract each article (usually 1)
            scoring_votes: How many times to score each card (3+ recommended)
            max_synthesis_retries: Max attempts at synthesis if validation fails
        
        Returns:
            Dict with final_article, validation_result, and full pipeline data
        """
        
        print(f"Starting pipeline with {len(articles)} articles...")
        
        # STEP 1: EXTRACT (parallel)
        print("Step 1: Extracting article cards...")
        cards = self._extract_all(articles)
        print(f"  Extracted {len(cards)} cards")
        
        # STEP 2: SCORE (with voting)
        print("Step 2: Scoring cards...")
        scores = self._score_all(cards, votes=scoring_votes)
        print(f"  Scored all cards. Score range: {min(s['overall_score'] for s in scores):.1f} - {max(s['overall_score'] for s in scores):.1f}")
        
        # STEP 3: SELECT
        print("Step 3: Selecting best elements...")
        blueprint = self._select_best(cards, scores)
        print(f"  Blueprint created. Confidence: {blueprint['confidence']['level']}")
        
        # STEP 4 & 5: SYNTHESIZE + VALIDATE (with retry loop)
        print("Step 4-5: Synthesizing and validating...")
        final_article, validation = self._synthesize_with_validation(
            blueprint=blueprint["synthesis_blueprint"],
            original_prompt=original_prompt,
            target_word_count=target_word_count,
            original_scores=scores,
            max_retries=max_synthesis_retries
        )
        print(f"  Synthesis complete. Validation passed: {validation['passed']}")
        
        return {
            "final_article": final_article,
            "validation": validation,
            "pipeline_data": {
                "cards": cards,
                "scores": scores,
                "blueprint": blueprint,
                "num_source_articles": len(articles)
            }
        }
    
    def _extract_all(self, articles: List[str]) -> List[Dict]:
        """Extract cards from all articles in parallel."""
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._extract_one, article, idx)
                for idx, article in enumerate(articles)
            ]
            return [f.result() for f in futures]
    
    def _extract_one(self, article: str, article_id: int) -> Dict:
        """Extract a single article card."""
        # Implementation from EXTRACT section
        pass
    
    def _score_all(self, cards: List[Dict], votes: int) -> List[Dict]:
        """Score all cards with voting."""
        # Implementation from SCORE section
        pass
    
    def _select_best(self, cards: List[Dict], scores: List[Dict]) -> Dict:
        """Select best elements for synthesis."""
        # Implementation from SELECT section
        pass
    
    def _synthesize_with_validation(
        self,
        blueprint: Dict,
        original_prompt: str,
        target_word_count: int,
        original_scores: List[Dict],
        max_retries: int
    ) -> tuple:
        """Synthesize article with validation retry loop."""
        # Implementation from SYNTHESIZE and VALIDATE sections
        pass


# Usage Example
if __name__ == "__main__":
    client = OpenAI()
    
    brand_guidelines = """
    Voice: Professional but approachable. We're experts, not academics.
    Tone: Confident, helpful, occasionally witty.
    Avoid: Jargon without explanation, clickbait, hyperbole.
    Audience: Mid-level marketing professionals at B2B SaaS companies.
    """
    
    original_prompt = """
    Write a blog post about why most marketing attribution models fail
    and what companies should do instead. Target length: 1500 words.
    Include practical advice and at least one example.
    """
    
    # Assume you've already generated these
    generated_articles = [...]  # 10-15 articles
    
    pipeline = ArticleSynthesisPipeline(client, brand_guidelines)
    result = pipeline.run(
        articles=generated_articles,
        original_prompt=original_prompt,
        target_word_count=1500
    )
    
    print("\n" + "="*50)
    print("FINAL ARTICLE")
    print("="*50)
    print(result["final_article"])
```

---

## Error Handling 

### Strict Output Parsing

```python
import json
from jsonschema import validate, ValidationError

def parse_with_retry(response_text: str, schema: dict, retry_func, max_retries: int = 3):
    """
    Principle: syntax errors signal logic errors.
    If output doesn't match schema, retry the entire call.
    """
    for attempt in range(max_retries):
        try:
            parsed = json.loads(response_text)
            validate(instance=parsed, schema=schema)
            return parsed
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt < max_retries - 1:
                print(f"  Parsing failed (attempt {attempt + 1}), retrying...")
                response_text = retry_func()
            else:
                raise ValueError(f"Failed to get valid output after {max_retries} attempts: {e}")
```

### Token Length Red Flags

```python
def check_response_length(response, expected_max_tokens: int, tolerance: float = 1.5):
    """
    Principle: abnormally long responses often indicate confusion.
    """
    actual_tokens = response.usage.completion_tokens
    
    if actual_tokens > expected_max_tokens * tolerance:
        print(f"  WARNING: Response unusually long ({actual_tokens} tokens, expected ~{expected_max_tokens})")
        return False  # Consider retrying
    return True
```

---

## Tuning Parameters

| Parameter | Recommended | Notes |
|-----------|-------------|-------|
| Source articles | 10-15 | Enough variety, not too much cost |
| Scoring votes | 3 | Reduces scoring variance |
| Extract temperature | 0.2-0.3 | Consistent extraction |
| Score temperature | 0.2 | Consistent evaluation |
| Select temperature | 0.3-0.4 | Some analytical creativity |
| Synthesize temperature | 0.6-0.8 | Creative writing freedom |
| Validate temperature | 0.2 | Consistent judgment |
| Max synthesis retries | 3 | Usually converges by then |

---

