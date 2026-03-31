# T04 Pseudoword Theory Audit

This audit treats T04 as a stimulus-design problem (not scorer heuristics).

## Key Findings
- likely over-wordlike items: `fote, gope, jope, vope, wote, zote`
- likely too sparse/alien items: `woting, wotting, zoting, zotting`
- problematic pair pattern: `correlated_with_broader_wordlikeness`
- template counts: `{'CVC': 6, 'CVCE': 6, 'ING_SHORT': 6, 'ING_LONG': 3}`
- template max/min ratio: `2.0`

## High-Burden Minimal-Pair Clusters
- none above rule threshold

## Candidate Redesign Summary
### gop:gope
- accepted: `bop/bope, kop/kope, zop/zope`
- rejected_count: `8`
### vop:vope
- accepted: `bop/bope, kop/kope, zop/zope`
- rejected_count: `8`
### wot:wote
- accepted: `kot/kote`
- rejected_count: `10`
### jop:jope
- accepted: `bop/bope, kop/kope, zop/zope`
- rejected_count: `8`

## Suggested Pilot Set
- replacements: `bop/bope, kop/kope, kot/kote, zop/zope`
- controls: `fot/fote, zot/zote, jop/jope`
