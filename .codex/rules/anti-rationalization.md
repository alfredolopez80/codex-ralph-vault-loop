# Anti-Rationalization Stop Rules

These Stop-hook patterns block finalization when the agent is closing with
probability, excuses, or unverifiable completion claims instead of evidence.

| Pattern                      | Why it blocks                                          | Expected recovery                                    |
| ---------------------------- | ------------------------------------------------------ | ---------------------------------------------------- |
| should work                  | Predictive wording is not verification.                | Run tests, lint, build, or cite concrete validation. |
| probably                     | Probability is not done.                               | Replace with factual evidence.                       |
| I think this is done         | Completion must be evidenced.                          | Provide VERIFIED_DONE evidence.                      |
| no further action is needed  | Often hides missing validation.                        | State what was validated.                            |
| tests are not necessary      | Tests require explicit justification.                  | Run tests or explain verified alternative evidence.  |
| cannot continue              | Stopping needs a factual blocker.                      | Name the blocker and evidence.                       |
| blocked                      | A blocker without evidence is an excuse.               | Provide exact failure or dependency.                 |
| assuming                     | Assumptions must be resolved or called out as risk.    | Verify or document the assumption.                   |
| seems complete               | Appearance is not verification.                        | Provide factual completion criteria.                 |
| good enough                  | Quality gate bypass phrasing.                          | Finish the expected checks.                          |
| manual verification required | Valid only with a specific manual checklist or result. | Run or describe the manual verification evidence.    |

Clear evidence includes passed tests, lint, typecheck, build, reviewed diff,
`VERIFIED_DONE`, or a state file with `verified_done: true`.
