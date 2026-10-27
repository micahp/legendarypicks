# 2024 validation decision: emergency QB3 counts as inactive

Micah’s validation rule is that `emergency_qb3` counts as an inactive when validating the roster `INA` designation, matching the official inactive list. Keep the emergency-QB3 flag separate for the availability target; this decision changes the validation numerator only.

## Precision of roster `INA`

| Comparison | Ordinary official inactives | Including emergency QB3 |
|---|---:|---:|
| NFL.com JSONL only | 3,426 / 3,611 = **94.88%** | (3,426 + 151) / 3,611 = **99.06%** |
| Adjudication-adjusted, unresolved key excluded | 3,449 / 3,610 = **95.54%** | (3,449 + 151) / 3,610 = **99.72%** |

The 151 emergency-QB3 identities on roster `INA` rows are included only in the right-hand validation metric. One additional emergency-QB3 identity has roster status `ACT`, so it is not part of `INA` precision. In the availability target, all emergency-QB3 identities retain their separate label.

The source counts and adjudication are documented in [the existing 2024 rate report](official-inactive-designation-rates-2024.md) and [adjudication report](roster-ina-adjudication-2024.md); those files were left unchanged.
