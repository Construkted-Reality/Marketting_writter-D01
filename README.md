# Marketing Blog Post Generator

A sophisticated marketing blog post generation tool that uses a local OpenAI-compliant API endpoint. The tool features a 6-stage article synthesis pipeline that generates, evaluates, and refines marketing content for Construkted Reality.

## Features

- **Parallel Article Generation**: Generate multiple article candidates concurrently using ThreadPoolExecutor
- **6-Stage Synthesis Pipeline**: CANDIDATES → EXTRACT → SCORE → SELECT → SYNTHESIZE → VALIDATE
- **Quality Scoring**: Evaluates articles on 7 quality dimensions with two scoring modes (absolute and pairwise) for improved consistency
- **Validation Loop**: Automatically regenerates content that doesn't meet quality thresholds
- **Comprehensive Metrics**: Tracks words, tokens, execution times, and LLM calls across all stages
- **Thread-Safe Operations**: Safe parallel processing with progress tracking and error collection

## Installation

```bash
# Install dependencies using pipenv
pipenv install

# Or with pip
pip install python-dotenv openai pyyaml

# Set up environment variables
cp .env.example .env  # Create your .env file with API keys
```

## Configuration

### Model Configuration (`models.yaml`)

The tool uses a YAML configuration file to manage LLM providers and models. This allows easy switching between different models without editing environment variables.

**Example `models.yaml`:**

```yaml
providers:
  local:
    base_url: "http://192.168.8.90:42069/v1"
    api_key_env: "LOCAL_API_KEY"  # References .env variable
    models:
      - minimax-m2.1
      - qwen3-vl-30b-inst
      - glm-45-air

  openai:
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    models:
      - gpt-4o
      - gpt-4o-mini

presets:
  local-minimax:
    provider: local
    model: minimax-m2.1
    description: "Local vLLM server with MiniMax M2.1"

  openai-4o:
    provider: openai
    model: gpt-4o
    description: "OpenAI GPT-4o"

default_preset: local-minimax  # Used when no --preset flag specified
```

### Environment Variables (`.env`)

Create a `.env` file with **API keys only** (secrets that shouldn't be in version control):

```env
# API Keys for LLM Providers
LOCAL_API_KEY=outsider
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Note:** Provider endpoints and model names are now configured in `models.yaml`, not `.env`.

### Managing Models

**Adding a new provider:**

1. Edit `models.yaml` and add a new provider entry:
```yaml
providers:
  anthropic:
    base_url: "https://api.anthropic.com/v1"
    api_key_env: "ANTHROPIC_API_KEY"
    models:
      - claude-3-5-sonnet-20241022
```

2. Add the corresponding API key to `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Adding a new preset:**

```yaml
presets:
  anthropic-sonnet:
    provider: anthropic
    model: claude-3-5-sonnet-20241022
    description: "Anthropic Claude 3.5 Sonnet"
```

**Changing the default model:**

```yaml
default_preset: local-qwen  # Change this to any preset name
```

## Command Line Flags

### Model Selection Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--preset` | string | - | Model preset to use (e.g., 'local-minimax', 'local-qwen'). Overrides the default preset from `models.yaml`. |
| `--list-models` | flag | False | List all available model presets and exit. Shows providers, models, and descriptions. |

### Generation Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--temperature` | float | 0.7 | Sampling temperature for LLM generation. Higher values (0.8) produce more creative output, lower values (0.3) produce more focused content. |
| `--max-tokens` | int | 4000 | Maximum number of tokens to generate per LLM call. |
| `--output` | string | - | Base filename (without extension) to save LLM responses. Creates numbered markdown files when using multiple iterations. |
| `--iterations` | int | 1 | Number of times to run the LLM generation routine. Creates numbered output files when > 1. |
| `--verbose` | flag | False | Enable verbose output for detailed progress tracking. |
| `--retry-count` | int | 3 | Number of API call retries on failure. |
| `--retry-delay` | float | 1.0 | Delay between retry attempts in seconds. |
| `--filter-think` | flag | False | Filter out content between `<think>` tags from the LLM response (useful for reasoning models outputs). |
| `--topic-file` | string | - | Path to a file containing the specific blog post topic/idea. |

### Pipeline Control Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--candidates-only` | flag | False | Generate candidate articles only, skip the synthesis pipeline. Useful for creating a pool of candidates to review before synthesis. |
| `--candidates-dir` | string | - | Path to a folder containing candidate markdown files. Skips candidate generation and loads from files. Enables running synthesis on previously generated candidates. |
| `--synthesis-votes` | int | 5 | Number of scoring votes in the synthesis pipeline (absolute mode only). More votes increase consistency but take longer. |
| `--synthesis-retries` | int | 3 | Maximum synthesis attempts on validation failure. The pipeline will retry up to this many times. |
| `--target-word-count` | int | 1500 | Target word count for the synthesized article. The final article will aim to meet this length. |
| `--scoring-mode` | string | absolute | Scoring method: `absolute` (1-10 scores per criterion with voting) or `pairwise` (head-to-head article comparison). Pairwise mode is more stable but requires more LLM calls. |

### Parallel Processing Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--parallel` | flag | False | Enable parallel article generation. Recommended for `--iteration >= 5`. Uses ThreadPoolExecutor for concurrent LLM requests. |
| `--max-concurrent` | int | 5 | Maximum concurrent LLM requests when using `--parallel`. Higher values increase throughput but may strain the API. |

### Utility Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--cleanup-old` | int | 0 | Remove output directories older than N days. Set to 0 to disable cleanup. |

## Usage Examples

### List Available Models

View all configured model presets:

```bash
python post_generator.py --list-models
```

### Basic Single Article Generation

Generate a single marketing blog post using the default preset:

```bash
python post_generator.py --topic-file prompts/construkted_globe.txt --output my_article
```

### Generate with a Specific Model

Use a different model preset:

```bash
python post_generator.py \
  --preset local-qwen \
  --topic-file prompts/construkted_globe.txt \
  --output my_article
```

### Multiple Candidate Generation

Generate 5 candidate articles in parallel using a specific model:

```bash
python post_generator.py \
  --preset local-minimax \
  --topic-file prompts/construkted_globe.txt \
  --output blog_candidates \
  --iterations 5 \
  --parallel \
  --max-concurrent 5
```

### Candidates Only Mode

Generate candidates without running synthesis (useful for reviewing before selection):

```bash
python post_generator.py \
  --preset local-qwen-think \
  --topic-file prompts/construkted_globe.txt \
  --output review_candidates \
  --iterations 3 \
  --candidates-only \
  --verbose
```

### Run Synthesis on Existing Candidates

Load previously generated candidates and run the full synthesis pipeline:

```bash
python post_generator.py \
  --candidates-dir outputs/2024-01-15/blog_candidates \
  --output final_article \
  --synthesis-votes 5 \
  --verbose
```

### Pairwise Scoring Mode

Use pairwise comparison for more stable, consistent scoring (compares articles head-to-head):

```bash
python post_generator.py \
  --candidates-dir outputs/2024-01-15/blog_candidates \
  --output final_article \
  --scoring-mode pairwise \
  --verbose
```

### Pairwise Scoring with Parallel Processing

Run pairwise comparisons in parallel for faster execution:

```bash
python post_generator.py \
  --candidates-dir outputs/2024-01-15/blog_candidates \
  --output final_article \
  --scoring-mode pairwise \
  --parallel \
  --max-concurrent 10 \
  --verbose
```

### Custom Temperature and Word Count

Generate with creative temperature and custom target length:

```bash
python post_generator.py \
  --topic-file prompts/construkted_globe.txt \
  --output creative_article \
  --temperature 0.8 \
  --target-word-count 2000 \
  --verbose
```

### Parallel with Retry Configuration

High-throughput generation with custom retry settings:

```bash
python post_generator.py \
  --topic-file prompts/construkted_globe.txt \
  --output batch_articles \
  --iteration 10 \
  --parallel \
  --max-concurrent 10 \
  --retry-count 5 \
  --retry-delay 2.0 \
  --verbose
```

### Filter Think Tags

Generate content from reasoning models and filter internal reasoning:

```bash
python post_generator.py \
  --topic-file prompts/construkted_globe.txt \
  --output clean_article \
  --filter-think
```

### Cleanup Old Outputs

Remove output directories older than 30 days:

```bash
python post_generator.py --cleanup-old 30
```

### Full Pipeline with Custom Settings

Complete synthesis pipeline with all options customized:

```bash
python post_generator.py \
  --topic-file prompts/construkted_globe.txt \
  --output full_synthesis \
  --iteration 5 \
  --parallel \
  --max-concurrent 5 \
  --synthesis-votes 3 \
  --synthesis-retries 3 \
  --target-word-count 1500 \
  --verbose
```

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ARTICLE SYNTHESIS PIPELINE                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  STAGE 1: CANDIDATES                                               │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Generate N article candidates (parallel or sequential)    │  │
│  │  Each candidate is a complete marketing blog post           │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                    │
│  STAGE 2: EXTRACT                                                 │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Convert full articles into structured ArticleCards         │  │
│  │  Extract: headlines, hook, argument, structure, etc.       │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                    │
│  STAGE 3: SCORE                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Evaluate each card on 7 quality dimensions                │  │
│  │  - hook_strength (15%)  - argument_clarity (20%)           │  │
│  │  - evidence_quality (15%) - structural_coherence (15%)    │  │
│  │  - originality (15%)     - memorability (10%)              │  │
│  │  - actionability (10%)                                   │  │
│  │  Multiple votes per card for consistency                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                    │
│  STAGE 4: SELECT                                                  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Analyze all cards and scores to create SynthesisBlueprint │  │
│  │  Select best elements from each candidate for synthesis   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                    │
│  STAGE 5: SYNTHESIZE                                              │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Generate final article from blueprint                     │  │
│  │  Combine selected elements into one coherent piece        │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                    │
│  STAGE 6: VALIDATE                                                │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Verify article meets quality standards                    │  │
│  │  Check blueprint compliance, quality score, coherence     │  │
│  │  Retry synthesis if validation fails                       │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Scoring Modes

The pipeline supports two scoring modes to evaluate article quality:

### Absolute Mode (Default)

Each article is scored independently on a 1-10 scale for each criterion. Multiple votes are taken and averaged to reduce variance.

**Improvements in absolute mode:**
- Temperature set to 0.0 for maximum consistency
- 5 votes per article (configurable via `--synthesis-votes`)
- Median-based outlier detection removes scores >2 std from median
- Reports high-variance criteria for debugging

**Best for:** Smaller candidate sets (2-5 articles), when you need interpretable 1-10 scores.

### Pairwise Mode

Articles are compared head-to-head on each criterion: "Which article has a stronger hook, A or B?" Win counts are converted to 1-10 scores.

**How it works:**
- For N articles: N×(N-1)/2 pairs per criterion
- 7 criteria = 21 comparisons for 3 articles, 315 for 10 articles
- Ties give 0.5 wins to each article
- Win counts normalized to 1-10 scale

**Best for:** Larger candidate sets (5-10 articles), when scoring consistency is critical, when you want more stable rankings.

**Trade-off:** More LLM calls, but relative comparisons are cognitively easier for the model than absolute judgments.

## Scoring Criteria

The synthesis pipeline evaluates content on seven key dimensions:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| `hook_strength` | 15% | How compelling is the opening? Does it create curiosity, tension, or immediate value? |
| `argument_clarity` | 20% | Is the core message immediately clear? Can you summarize it in one sentence? |
| `evidence_quality` | 15% | Are claims supported with specifics? Statistics, examples, case studies? |
| `structural_coherence` | 15% | Does the structure serve the argument? Is there a logical flow? |
| `originality` | 15% | Does it offer a fresh angle? Or is it generic advice anyone could write? |
| `memorability` | 10% | Are there phrases or ideas that stick? Would someone quote this? |
| `actionability` | 10% | Does the reader know what to do after reading? Is there a clear next step? |

## Output Structure

When running with `--output`, the following structure is created:

```
outputs/
└── YYYY-MM-DD/
    └── {output_base}/
        ├── {output_base}_FINAL.md           # Final synthesized article
        ├── {output_base}_validation.json    # Validation report
        ├── {output_base}_pipeline_artifacts.json  # All intermediate data
        └── candidates/
            ├── {output_base}_candidate_01.md
            ├── {output_base}_candidate_02.md
            └── ...
```

## Metrics Summary

The tool provides comprehensive metrics including:

- **LLM Calls**: Total API calls per stage
- **Word Count**: Input and output words per stage
- **Token Estimates**: Estimated token usage (word count / 0.75)
- **Execution Time**: Time spent in each stage
- **Overall Totals**: Combined metrics across all stages

Example output:

```
================================================================================
COMPREHENSIVE PIPELINE METRICS SUMMARY
================================================================================

CANDIDATES STAGE:
  LLM Calls: 5
  Input: 15,000 words (20,000 tokens)
  Output: 7,500 words (10,000 token)
  Total: 22,500 words (30,000 token)
  Execution Time: 120.50 seconds

...

OVERALL TOTALS:
================================================================================
Total LLM Calls: 45
Total Words Processed: 67,500
Total Tokens Processed: 90,000
Total Execution Time: 480.25 seconds
Average Time per LLM Call: 10.67 seconds
================================================================================
```

## Prompt Files

The tool uses reference context files located in:

- `reference_context/writing_style-enhanced.md` - Writing style guidelines
- `reference_context/construkted_context.md` - Company context and mission
- `reference_context/Combined_Small_Team_Geospatial_Market_Analysis.md` - Market research

Pipeline stage prompts in `prompts/`:
- `pipeline_stage2_extract_system.md` - Article extraction to structured cards
- `pipeline_stage3_score_system.md` - Absolute scoring (1-10 per criterion)
- `pipeline_stage3_pairwise_system.md` - Pairwise comparison scoring
- `pipeline_stage4_select_system.md` - Best element selection
- `pipeline_stage5_synthesize_system.md` - Final article synthesis
- `pipeline_stage6_validate_system.md` - Quality validation

## Error Handling

- Automatic retry with configurable count and delay
- Thread-safe error collection in parallel mode
- Graceful degradation (continues with successful results on partial failures)
- Detailed error messages for debugging

## License

Internal project for Construkted Reality marketing content generation.