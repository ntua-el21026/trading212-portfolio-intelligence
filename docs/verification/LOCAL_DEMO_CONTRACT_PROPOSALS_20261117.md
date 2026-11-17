# LOCAL/DEMO qualification contract proposals

**Decision boundary:** LOCAL/DEMO acceptance on 17 November 2026 does not approve
these proposals. They remain proposed future contracts; original thresholds,
scanner policies and failed execution results are unchanged. See the
[owner acceptance](../implementation/LOCAL_DEMO_ACCEPTANCE_20261117.md).

**Prepared for:** Michail Athanasios Peppas. **Date:** 17 November 2026.
**Status:** proposals for owner review; no accepted policy or original gate changed.

The current LOCAL/DEMO scope permits documented limitations without changing
Checkpoint B acceptance. These proposals do not convert historical failures into
passes or authorize distribution, production, P3-10 or CI.

## A. Web artifact reproducibility

The retained paired builds report 277 differences, including build identifiers,
cryptographic preview/action material, membership changes and build traces.
The original whole-tree comparison remains FAIL. Source identity and two successful
build exits alone do not demonstrate artifact equivalence.

Proposed future contract:

1. Identify complete source, lockfiles, toolchain, environment, build commands,
   file membership, encoded byte sizes, modes and SHA-256 for both complete trees.
   Preserve every original file and difference, including build/runtime metadata.
2. Require byte equality for deterministic application assets and generated
   contracts after establishing the framework's actual transformation graph.
   No blanket directory, extension or server-code exclusion is permitted.
3. Classify each remaining difference by a versioned, narrowly defined verifier:
   fresh cryptographic material, explicit build identity, local trace metadata,
   or unresolved content. Verify relationships to dependent manifests/assets;
   do not strip arbitrary strings or normalize substantive JavaScript.
4. Preserve cryptographic randomness. Never pin or reuse encryption keys merely
   to obtain equality. Verify their required structure and linkage in memory;
   do not publish key values or retained private build material.
5. Fail the proposed equivalence gate on unclassified differences, changed
   executable behavior, missing artifacts, unexpected dependency changes or
   inconsistent manifest references. Independently review the verifier and add
   adversarial tests before applying it to acceptance.

Owner decision requested: authorize specification and review of this separate
semantic reproducibility gate, retaining the original byte-equality observation.
Implementation of that gate is outside this UI package. No current PASS is claimed.

## B. Independently classified nonsecret scanner matches

Historical Gitleaks and the high-confidence checker returned nonzero exits.
Separate evidence classifies public receipt identifiers, documentary metadata and
recomputable digests as nonsecret. Those classifications retain their own source,
rule, span and proof; they do not change the scanner's actual outcome.

Proposed future decision model:

- Keep the configured scanner, rules, full source/history coverage, raw exit and
  finding inventory intact. Store sensitive raw findings only in protected
  evidence; public records contain bounded references and closed classifications.
- Apply a second independent disposition step to exact findings, requiring source
  SHA, scanner/rule version, path/span, finding fingerprint and reproducible proof.
  A digest classification must recompute its declared content; a public-code
  classification must prove its origin and use without inferring from its shape.
- New or moved matches require new review. Unknown, ambiguous or genuine secret
  findings fail closed. Never broadly allowlist UUIDs, hashes, documentation,
  tokens or paths. Do not add ignore rules to hide unresolved findings.
- Report scanner status and reviewed-secret-risk status separately. The owner may
  explicitly accept proved nonsecret observations for a specified source scope;
  that decision never becomes a claim of a zero-exit scanner execution.

Owner decision requested: approve this two-result reporting contract and nominate
an independent reviewer for exact classified findings. No scanner configuration,
ignore list, history or security threshold is changed here.

## C. Admission performance

The original 0.750-second p95 requirement remains failed in retained cohorts.
No causal production bottleneck has been demonstrated. The LOCAL/DEMO milestone
permits that limitation without another expensive diagnostic cycle. A future
performance-contract review should first define supported hardware, cold-start
semantics, measured boundary and reproducibility conditions. It must retain all
samples and historical failures. No revised threshold or performance PASS is
proposed or implemented in this package.
