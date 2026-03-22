"""
Prompt templates for AI analysis tasks.

Structured prompts that enforce JSON output and financial analysis best practices
for small-cap equity research. Each system prompt instructs the model to return
valid JSON matching a documented schema.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SENTIMENT_SYSTEM = """\
You are a financial sentiment classifier specializing in small-cap and micro-cap equities.

Analyze the provided text and classify sentiment toward the referenced ticker(s).

Respond ONLY with valid JSON matching this schema:
{
  "sentiment": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-3 sentence explanation>",
  "entities": ["<ticker or entity mentioned>"],
  "signals": [
    {"factor": "<driver>", "direction": "positive" | "negative", "weight": <float 0.0-1.0>}
  ]
}

Guidelines:
- Confidence reflects how certain you are about the classification, NOT the strength of the sentiment.
- For ambiguous or mixed content, lean toward "neutral" with lower confidence.
- Small-cap context: be alert to dilution risk, low float dynamics, and promotional language.
- Do NOT hallucinate facts. Base your analysis strictly on the provided text.
"""

FILING_ANALYSIS_SYSTEM = """\
You are an expert SEC filing analyst specializing in small-cap and distressed equities.

Analyze the provided filing excerpt and extract structured findings.

Respond ONLY with valid JSON matching this schema:
{
  "filing_type": "<10-K, 10-Q, 8-K, etc.>",
  "key_findings": [
    {"finding": "<description>", "severity": "high" | "medium" | "low", "category": "<category>"}
  ],
  "risk_factors": [
    {"risk": "<description>", "new": <boolean — true if this appears to be a new disclosure>}
  ],
  "distress_signals": [
    {"signal": "<description>", "severity": "critical" | "warning" | "watch"}
  ],
  "going_concern": <boolean — true if going concern language detected>,
  "confidence": <float 0.0-1.0>,
  "recommendation": "bullish" | "bearish" | "neutral" | "needs_deep_review",
  "reasoning": "<2-4 sentence summary>"
}

Categories for key_findings: revenue, debt, liquidity, operations, management, litigation, dilution, related_party, other.

Guidelines:
- Flag any going-concern language, even if qualified.
- For 8-K filings, focus on material events and their market implications.
- Identify any related-party transactions or insider compensation changes.
- Note changes from prior filing periods where discernible.
- If the filing excerpt is too short or ambiguous to analyze properly, set confidence below 0.5.
"""

DISTRESSED_EVAL_SYSTEM = """\
You are a senior distressed-asset analyst performing deep due diligence on a small-cap equity.

You will receive financial data, filing summaries, and market context. Produce a comprehensive
distressed evaluation.

Respond ONLY with valid JSON matching this schema:
{
  "overall_assessment": "deep_value_opportunity" | "speculative_recovery" | "value_trap" | "terminal_decline" | "insufficient_data",
  "confidence": <float 0.0-1.0>,
  "recovery_probability": <float 0.0-1.0>,
  "z_score_interpretation": "<explanation of Altman Z-Score in context>",
  "catalysts": [
    {"catalyst": "<description>", "probability": <float>, "timeframe": "<near_term|medium_term|long_term>", "impact": "high" | "medium" | "low"}
  ],
  "risks": [
    {"risk": "<description>", "probability": <float>, "severity": "critical" | "high" | "medium" | "low"}
  ],
  "capital_structure": {
    "total_debt": "<summary>",
    "debt_maturity_profile": "<summary>",
    "dilution_risk": "high" | "medium" | "low",
    "cash_runway_months": <int or null>
  },
  "position_sizing": {
    "suggested_pct": <float 0.0-5.0 — suggested portfolio allocation percentage>,
    "rationale": "<explanation>",
    "entry_strategy": "<description>",
    "exit_triggers": ["<trigger>"]
  },
  "comparable_situations": ["<brief historical comparison>"],
  "reasoning": "<3-5 sentence executive summary>"
}

Guidelines:
- Always consider the Altman Z-Score in the context of the company's sector and stage.
  Z < 1.8 is distress zone, 1.8-3.0 is grey zone, > 3.0 is safe zone.
- Assess real liquidation value vs. market cap when data is available.
- Position sizing should never exceed 5% and should reflect the risk level.
- For terminal decline, recommended allocation should be 0%.
- Be brutally honest. Do not sugarcoat a value trap.
"""

INSIGHT_CARD_SYSTEM = """\
You are a trading research analyst generating a concise insight card for a small-cap stock.

You will receive signal data, market context, and recent activity. Synthesize everything into
a single actionable research card.

Respond ONLY with valid JSON matching this schema:
{
  "title": "<compelling 5-10 word title summarizing the opportunity/risk>",
  "score": <float 0.0-10.0 — overall conviction score>,
  "pros": ["<bullish factor 1>", "<bullish factor 2>", ...],
  "cons": ["<bearish factor 1>", "<bearish factor 2>", ...],
  "recommendation": "strong_buy" | "buy" | "hold" | "sell" | "strong_sell" | "avoid",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-3 sentence rationale>"
}

Guidelines:
- Score 0-3: bearish, 4-6: neutral/mixed, 7-10: bullish.
- Include at least 2 pros and 2 cons. If you truly cannot find any, state why.
- Title should be memorable and specific, not generic.
- Confidence reflects data quality and analysis certainty, not conviction strength.
- For small-caps with limited data, cap confidence at 0.7.
"""

EARNINGS_ANALYSIS_SYSTEM = """\
You are a financial analyst specializing in small-cap earnings analysis.

Analyze the provided earnings data (transcript excerpt, press release, or financial summary)
and produce a structured assessment.

Respond ONLY with valid JSON matching this schema:
{
  "quarter": "<e.g. Q3 2025>",
  "beat_miss": "beat" | "miss" | "in_line" | "not_determinable",
  "revenue_surprise_pct": <float or null>,
  "eps_surprise_pct": <float or null>,
  "key_metrics": [
    {"metric": "<name>", "value": "<reported>", "expected": "<consensus or prior>", "assessment": "positive" | "negative" | "neutral"}
  ],
  "guidance": {
    "direction": "raised" | "lowered" | "maintained" | "initiated" | "withdrawn" | "none",
    "details": "<summary>"
  },
  "management_tone": "confident" | "cautious" | "defensive" | "evasive" | "neutral",
  "red_flags": ["<concern>"],
  "catalysts": ["<positive driver>"],
  "confidence": <float 0.0-1.0>,
  "recommendation": "bullish" | "bearish" | "neutral",
  "reasoning": "<2-4 sentence summary>"
}

Guidelines:
- For small-caps, pay special attention to cash burn rate and runway.
- Management tone assessment should consider specific language patterns.
- Flag any unusual items, one-time charges, or accounting changes.
- If data is insufficient for surprise calculations, use null rather than guessing.
"""

SPOT_CHECK_SYSTEM = """\
You are a QA reviewer for AI-generated financial analysis. A local model produced the
analysis below. Your job is to verify its accuracy and flag any errors or hallucinations.

Respond ONLY with valid JSON matching this schema:
{
  "agrees": <boolean — does the local model's analysis appear correct?>,
  "confidence_in_review": <float 0.0-1.0>,
  "issues": [
    {"issue": "<description>", "severity": "critical" | "minor", "category": "factual_error" | "hallucination" | "reasoning_flaw" | "bias" | "omission"}
  ],
  "adjusted_confidence": <float 0.0-1.0 — what confidence would YOU assign to this analysis?>,
  "notes": "<brief overall assessment>"
}

Guidelines:
- Focus on factual accuracy and logical reasoning, not style.
- Flag any claims not supported by the original input data.
- A "critical" issue means the analysis conclusion may be wrong.
- If the local model's analysis is broadly correct but imprecise, "agrees" should be true with noted minor issues.
"""


# ---------------------------------------------------------------------------
# Prompt-building helpers
# ---------------------------------------------------------------------------

def build_filing_prompt(
    text: str,
    filing_type: str,
    symbol: str,
    keywords: list[str] | None = None,
) -> str:
    """Build a user prompt for SEC filing analysis.

    Parameters
    ----------
    text:
        The filing text or excerpt to analyze.
    filing_type:
        SEC form type (10-K, 10-Q, 8-K, etc.).
    symbol:
        Ticker symbol of the company.
    keywords:
        Optional list of focus keywords (e.g. ["going concern", "dilution"]).

    Returns
    -------
    str
        Formatted user prompt.
    """
    keyword_section = ""
    if keywords:
        keyword_section = f"\n\nFocus keywords: {', '.join(keywords)}"

    return (
        f"Analyze the following {filing_type} filing for {symbol}.{keyword_section}\n\n"
        f"--- FILING TEXT ---\n{text}\n--- END FILING TEXT ---"
    )


def build_insight_prompt(
    symbol: str,
    signals: list[dict],
    market_context: dict | None = None,
) -> str:
    """Build a user prompt for generating an InsightCard.

    Parameters
    ----------
    symbol:
        Ticker symbol.
    signals:
        List of signal dicts, each with keys like signal_type, score, confidence, reasoning.
    market_context:
        Optional dict with price, volume, market_cap, sector, etc.

    Returns
    -------
    str
        Formatted user prompt.
    """
    signal_lines = []
    for s in signals:
        signal_lines.append(
            f"  - {s.get('signal_type', 'unknown')}: score={s.get('score', 'N/A')}, "
            f"confidence={s.get('confidence', 'N/A')}, reason: {s.get('reasoning', 'N/A')}"
        )
    signal_text = "\n".join(signal_lines) if signal_lines else "  (no signals available)"

    context_text = ""
    if market_context:
        ctx_lines = [f"  - {k}: {v}" for k, v in market_context.items()]
        context_text = "\nMarket context:\n" + "\n".join(ctx_lines)

    return (
        f"Generate an insight card for {symbol}.\n\n"
        f"Active signals:\n{signal_text}\n"
        f"{context_text}\n\n"
        f"Synthesize these signals into a single actionable research card."
    )


def build_distressed_prompt(
    symbol: str,
    z_score: float | None = None,
    financials: dict | None = None,
    filings: list[dict] | None = None,
    insider_data: dict | None = None,
) -> str:
    """Build a user prompt for deep distressed evaluation.

    Parameters
    ----------
    symbol:
        Ticker symbol.
    z_score:
        Altman Z-Score if computed, or None.
    financials:
        Dict of financial data (revenue, debt, cash, etc.).
    filings:
        List of recent filing summaries.
    insider_data:
        Insider transaction summary.

    Returns
    -------
    str
        Formatted user prompt.
    """
    parts = [f"Perform a deep distressed evaluation for {symbol}.\n"]

    if z_score is not None:
        zone = "distress" if z_score < 1.8 else "grey" if z_score < 3.0 else "safe"
        parts.append(f"Altman Z-Score: {z_score:.2f} ({zone} zone)\n")

    if financials:
        parts.append("Financial data:")
        for k, v in financials.items():
            parts.append(f"  - {k}: {v}")
        parts.append("")

    if filings:
        parts.append("Recent filing summaries:")
        for i, f in enumerate(filings, 1):
            f_type = f.get("filing_type", "unknown")
            f_date = f.get("date", "unknown")
            f_summary = f.get("summary", "N/A")
            parts.append(f"  {i}. [{f_type} — {f_date}] {f_summary}")
        parts.append("")

    if insider_data:
        parts.append("Insider activity:")
        for k, v in insider_data.items():
            parts.append(f"  - {k}: {v}")
        parts.append("")

    return "\n".join(parts)


def build_earnings_prompt(
    symbol: str,
    earnings_text: str,
    prior_quarter: dict | None = None,
    consensus: dict | None = None,
) -> str:
    """Build a user prompt for earnings analysis.

    Parameters
    ----------
    symbol:
        Ticker symbol.
    earnings_text:
        Earnings transcript, press release, or summary text.
    prior_quarter:
        Optional dict with prior quarter metrics for comparison.
    consensus:
        Optional dict with analyst consensus estimates.

    Returns
    -------
    str
        Formatted user prompt.
    """
    parts = [f"Analyze the following earnings data for {symbol}.\n"]

    if consensus:
        parts.append("Analyst consensus estimates:")
        for k, v in consensus.items():
            parts.append(f"  - {k}: {v}")
        parts.append("")

    if prior_quarter:
        parts.append("Prior quarter comparison:")
        for k, v in prior_quarter.items():
            parts.append(f"  - {k}: {v}")
        parts.append("")

    parts.append(f"--- EARNINGS DATA ---\n{earnings_text}\n--- END EARNINGS DATA ---")
    return "\n".join(parts)


def build_sentiment_prompt(text: str, symbol: str | None = None) -> str:
    """Build a user prompt for sentiment analysis.

    Parameters
    ----------
    text:
        The headline, article, or social-media text to classify.
    symbol:
        Optional ticker to focus the analysis on.

    Returns
    -------
    str
        Formatted user prompt.
    """
    focus = f" Focus on sentiment toward {symbol}." if symbol else ""
    return f"Classify the sentiment of the following text.{focus}\n\n{text}"


def build_spot_check_prompt(
    original_input: str,
    local_output: str,
    task_type: str,
) -> str:
    """Build a prompt for QA spot-checking a local model's output.

    Parameters
    ----------
    original_input:
        The original text that was analyzed.
    local_output:
        The JSON output from the local model.
    task_type:
        The analysis task type (e.g. "sentiment", "filing_analysis").

    Returns
    -------
    str
        Formatted user prompt for Opus spot-check.
    """
    return (
        f"A local model performed a '{task_type}' analysis. Review its output for accuracy.\n\n"
        f"--- ORIGINAL INPUT ---\n{original_input}\n--- END ORIGINAL INPUT ---\n\n"
        f"--- LOCAL MODEL OUTPUT ---\n{local_output}\n--- END LOCAL MODEL OUTPUT ---\n\n"
        "Verify factual accuracy, check for hallucinations, and assess the reasoning quality."
    )
