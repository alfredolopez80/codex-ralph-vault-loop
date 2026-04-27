---
name: scorecard
description: Maintain and apply RASS v1 scorecards with fixed weights, hard gates, and anti-gaming protections.
---
# Scorecard

## RASS v1

RASS v1 uses five weighted categories. Effectiveness is 35%. Efficiency is 20%. Reliability and safety are 20%. Memory and research quality are 15%. Maintainability and simplicity are 10%.

Every scorecard must include these hard gates. Tests pass. No secret leak. Eval files unchanged. No scope violation. No eval gaming.

## Authoring Rules

Version scorecards explicitly. Keep metric names concrete and observable. Prefer a small set of metrics that a script can normalize to 0..1. Do not change a scorecard during the run that uses it.

Fixtures are protected eval inputs. Do not rewrite them during candidate evaluation. If a fixture or scorecard needs improvement, open a separate phase or commit and re-baseline before using it for candidate decisions.

## Applying A Scorecard

Use `scripts/evals/run_scorecard.py` for single fixtures and suite-specific scripts for richer flows. A candidate can be kept only when the hard gates pass and the documented threshold is met.
