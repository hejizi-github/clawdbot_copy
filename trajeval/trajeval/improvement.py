"""Improvement loop: analyze evaluation results and generate actionable recommendations."""

from __future__ import annotations

from enum import Enum
from statistics import mean, stdev

from pydantic import BaseModel, Field

from .metrics import EvalReport
from .scorer import JudgeResult


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    metric: str
    pattern: str
    severity: Priority
    evidence: str


class Recommendation(BaseModel):
    title: str
    priority: Priority
    finding: str
    suggestion: str


class ImprovementReport(BaseModel):
    num_evaluations: int = 0
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    metric_summary: dict[str, dict] = Field(default_factory=dict)


_METRIC_ADVICE = {
    "step_efficiency": {
        "low": "Agent takes too many steps. Consider condensing multi-step reasoning into fewer, more decisive actions.",
        "declining": "Step efficiency is trending downward. Recent changes may have introduced unnecessary intermediate steps.",
    },
    "tool_accuracy": {
        "low": "Tool calls frequently fail. Review tool descriptions and ensure the agent has clear guidance on when to use each tool.",
        "declining": "Tool accuracy is dropping. Check if tool APIs or expected formats have changed.",
    },
    "loop_detection": {
        "low": "Agent enters repetitive patterns. Consider adding explicit loop-breaking logic or diversifying the agent's strategy selection.",
        "declining": "Loop frequency is increasing. The agent may be encountering new edge cases that trigger repetitive behavior.",
    },
    "error_recovery": {
        "low": "Agent struggles to recover from errors. Add retry logic with backoff, or teach the agent alternative strategies when initial approaches fail.",
        "declining": "Error recovery is getting worse. New error types may not be handled by existing recovery strategies.",
    },
    "token_efficiency": {
        "low": "Token usage is high relative to baseline. Consider shorter prompts, fewer reasoning steps, or caching repeated context.",
        "declining": "Token consumption is trending upward. Check for prompt drift or unnecessarily verbose tool outputs.",
    },
    "latency_budget": {
        "low": "Execution exceeds latency budget. Identify the slowest steps and consider parallel tool calls or cached results.",
        "declining": "Latency is increasing. Profile individual step durations to find the bottleneck.",
    },
}

_FAIL_RATE_HIGH = 0.5
_FAIL_RATE_MEDIUM = 0.3
_SCORE_LOW = 0.5
_TREND_THRESHOLD = 0.1


def analyze_results(reports: list[EvalReport]) -> ImprovementReport:
    """Analyze multiple evaluation reports and produce an improvement report.

    Reports should be ordered chronologically for accurate trend detection.
    If reports have ``timestamp`` set, they are sorted automatically.
    """
    if not reports:
        return ImprovementReport()

    if all(r.timestamp is not None for r in reports):
        reports = sorted(reports, key=lambda r: r.timestamp)  # type: ignore[arg-type]

    metric_scores: dict[str, list[float]] = {}
    metric_passed: dict[str, list[bool]] = {}

    for report in reports:
        for m in report.metrics:
            metric_scores.setdefault(m.name, []).append(m.score)
            metric_passed.setdefault(m.name, []).append(m.passed)

    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    metric_summary: dict[str, dict] = {}

    for name in sorted(metric_scores.keys()):
        scores = metric_scores[name]
        passed = metric_passed[name]
        avg = mean(scores)
        fail_rate = 1.0 - (sum(passed) / len(passed))
        sd = stdev(scores) if len(scores) > 1 else 0.0

        summary = {
            "mean_score": round(avg, 4),
            "fail_rate": round(fail_rate, 4),
            "std_dev": round(sd, 4),
            "num_evaluations": len(scores),
            "scale": 1.0,
        }

        if len(scores) >= 3:
            half = len(scores) // 2
            first_half_avg = mean(scores[:half]) if half > 0 else avg
            second_half_avg = mean(scores[half:])
            trend = second_half_avg - first_half_avg
            summary["trend"] = round(trend, 4)
        else:
            trend = 0.0

        metric_summary[name] = summary

        if fail_rate >= _FAIL_RATE_HIGH:
            severity = Priority.HIGH
            pattern = "consistently_failing"
            evidence = f"Fails {fail_rate:.0%} of evaluations (mean score: {avg:.2f})"
            findings.append(Finding(metric=name, pattern=pattern, severity=severity, evidence=evidence))
            advice = _METRIC_ADVICE.get(name, {}).get("low", f"Investigate why {name} consistently scores low.")
            recommendations.append(Recommendation(
                title=f"Fix {name}",
                priority=Priority.HIGH,
                finding=evidence,
                suggestion=advice,
            ))
        elif fail_rate >= _FAIL_RATE_MEDIUM:
            severity = Priority.MEDIUM
            pattern = "frequently_failing"
            evidence = f"Fails {fail_rate:.0%} of evaluations (mean score: {avg:.2f})"
            findings.append(Finding(metric=name, pattern=pattern, severity=severity, evidence=evidence))
            advice = _METRIC_ADVICE.get(name, {}).get("low", f"Improve {name} to reduce failure rate.")
            recommendations.append(Recommendation(
                title=f"Improve {name}",
                priority=Priority.MEDIUM,
                finding=evidence,
                suggestion=advice,
            ))

        if avg < _SCORE_LOW and fail_rate < _FAIL_RATE_MEDIUM:
            findings.append(Finding(
                metric=name,
                pattern="low_scoring",
                severity=Priority.MEDIUM,
                evidence=f"Mean score {avg:.2f} is below threshold {_SCORE_LOW}",
            ))

        if trend < -_TREND_THRESHOLD and len(scores) >= 3:
            findings.append(Finding(
                metric=name,
                pattern="declining",
                severity=Priority.HIGH if trend < -0.2 else Priority.MEDIUM,
                evidence=f"Score declining by {abs(trend):.2f} (first half avg: {mean(scores[:len(scores)//2]):.2f}, second half: {mean(scores[len(scores)//2:]):.2f})",
            ))
            advice = _METRIC_ADVICE.get(name, {}).get("declining", f"{name} is trending downward — investigate recent changes.")
            recommendations.append(Recommendation(
                title=f"Investigate declining {name}",
                priority=Priority.HIGH if trend < -0.2 else Priority.MEDIUM,
                finding=f"Score declined by {abs(trend):.2f}",
                suggestion=advice,
            ))

        if sd > 0.25 and len(scores) >= 3:
            findings.append(Finding(
                metric=name,
                pattern="high_variance",
                severity=Priority.LOW,
                evidence=f"Score std dev {sd:.2f} indicates inconsistent performance",
            ))

    recommendations.sort(key=lambda r: (
        0 if r.priority == Priority.HIGH else 1 if r.priority == Priority.MEDIUM else 2
    ))

    return ImprovementReport(
        num_evaluations=len(reports),
        findings=findings,
        recommendations=recommendations,
        metric_summary=metric_summary,
    )


_DIMENSION_ADVICE = {
    "task_completion": {
        "low": "Agent frequently fails to complete tasks. Review whether task descriptions are clear and whether the agent has access to all required tools.",
        "declining": "Task completion is declining. Recent prompt or tool changes may have degraded the agent's ability to finish tasks.",
    },
    "reasoning_quality": {
        "low": "Reasoning is weak. Consider adding chain-of-thought prompting or breaking complex tasks into explicit sub-steps.",
        "declining": "Reasoning quality is dropping. Check for prompt drift or overly compressed system instructions.",
    },
    "tool_use_appropriateness": {
        "low": "Tool selection is poor. Improve tool descriptions, add usage examples, or constrain available tools per task type.",
        "declining": "Tool use appropriateness is declining. New tools may be confusing the agent or tool descriptions may have drifted.",
    },
    "information_synthesis": {
        "low": "Agent struggles to combine information from multiple sources. Consider structured output formats or explicit synthesis prompts.",
        "declining": "Information synthesis is getting worse. The agent may be handling more complex multi-source tasks without adequate prompting.",
    },
    "harm_avoidance": {
        "low": "Agent takes unsafe actions. Add explicit safety constraints, confirmation steps for destructive operations, and PII handling rules.",
        "declining": "Safety behavior is degrading. Review recent prompt changes for weakened safety instructions.",
    },
}

_JUDGE_SCORE_LOW = 3
_JUDGE_FAIL_RATE_HIGH = 0.5
_JUDGE_FAIL_RATE_MEDIUM = 0.3
_JUDGE_TREND_THRESHOLD = 0.5


def analyze_judge_results(
    results: list[JudgeResult],
    *,
    pass_threshold: int = 3,
) -> ImprovementReport:
    """Analyze multiple LLM judge results and produce an improvement report.

    Scores are on a 0-5 integer scale. A dimension "passes" when score >= pass_threshold.
    """
    valid = [r for r in results if r.error is None]
    if not valid:
        return ImprovementReport()

    dim_scores: dict[str, list[int]] = {}
    for r in valid:
        for d in r.dimensions:
            dim_scores.setdefault(d.name, []).append(d.score)

    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    metric_summary: dict[str, dict] = {}

    for name in sorted(dim_scores.keys()):
        scores = dim_scores[name]
        avg = mean(scores)
        fail_rate = sum(1 for s in scores if s < pass_threshold) / len(scores)
        sd = stdev(scores) if len(scores) > 1 else 0.0

        summary: dict = {
            "mean_score": round(avg, 4),
            "fail_rate": round(fail_rate, 4),
            "std_dev": round(sd, 4),
            "num_evaluations": len(scores),
            "scale": 5.0,
        }

        trend = 0.0
        if len(scores) >= 3:
            half = len(scores) // 2
            first_half_avg = mean(scores[:half]) if half > 0 else avg
            second_half_avg = mean(scores[half:])
            trend = second_half_avg - first_half_avg
            summary["trend"] = round(trend, 4)

        metric_summary[f"judge:{name}"] = summary

        if fail_rate >= _JUDGE_FAIL_RATE_HIGH:
            evidence = f"Fails {fail_rate:.0%} of evaluations (mean score: {avg:.1f}/5)"
            findings.append(Finding(metric=f"judge:{name}", pattern="consistently_failing", severity=Priority.HIGH, evidence=evidence))
            advice = _DIMENSION_ADVICE.get(name, {}).get("low", f"Investigate why {name} consistently scores low.")
            recommendations.append(Recommendation(title=f"Fix {name}", priority=Priority.HIGH, finding=evidence, suggestion=advice))
        elif fail_rate >= _JUDGE_FAIL_RATE_MEDIUM:
            evidence = f"Fails {fail_rate:.0%} of evaluations (mean score: {avg:.1f}/5)"
            findings.append(Finding(metric=f"judge:{name}", pattern="frequently_failing", severity=Priority.MEDIUM, evidence=evidence))
            advice = _DIMENSION_ADVICE.get(name, {}).get("low", f"Improve {name} to reduce failure rate.")
            recommendations.append(Recommendation(title=f"Improve {name}", priority=Priority.MEDIUM, finding=evidence, suggestion=advice))

        if avg < _JUDGE_SCORE_LOW and fail_rate < _JUDGE_FAIL_RATE_MEDIUM:
            findings.append(Finding(metric=f"judge:{name}", pattern="low_scoring", severity=Priority.MEDIUM, evidence=f"Mean score {avg:.1f}/5 is below threshold {_JUDGE_SCORE_LOW}"))

        if trend < -_JUDGE_TREND_THRESHOLD and len(scores) >= 3:
            severity = Priority.HIGH if trend < -1.0 else Priority.MEDIUM
            evidence = f"Score declining by {abs(trend):.1f} (first half avg: {mean(scores[:len(scores)//2]):.1f}, second half: {mean(scores[len(scores)//2:]):.1f})"
            findings.append(Finding(metric=f"judge:{name}", pattern="declining", severity=severity, evidence=evidence))
            advice = _DIMENSION_ADVICE.get(name, {}).get("declining", f"{name} is trending downward — investigate recent changes.")
            recommendations.append(Recommendation(title=f"Investigate declining {name}", priority=severity, finding=f"Score declined by {abs(trend):.1f}", suggestion=advice))

        if sd > 1.0 and len(scores) >= 3:
            findings.append(Finding(metric=f"judge:{name}", pattern="high_variance", severity=Priority.LOW, evidence=f"Score std dev {sd:.2f} indicates inconsistent judging"))

    recommendations.sort(key=lambda r: (0 if r.priority == Priority.HIGH else 1 if r.priority == Priority.MEDIUM else 2))

    return ImprovementReport(
        num_evaluations=len(valid),
        findings=findings,
        recommendations=recommendations,
        metric_summary=metric_summary,
    )
