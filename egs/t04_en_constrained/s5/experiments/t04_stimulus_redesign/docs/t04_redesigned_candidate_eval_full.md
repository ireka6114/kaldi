# T04 Candidate Set Evaluation

- mode: `full`
- n_replacement_pairs: `10`
- n_control_pairs: `3`
- template_balance: `{'counts': {'CVC': 10, 'CVCE': 10}, 'max_to_min_ratio': 1.0}`
- real_word_proximity: `{'mean_nearest_distance_short': 1.0, 'mean_nearest_distance_long': 1.0, 'close_distance_ratio_le1': 1.0}`
- risk_flags: `high_real_word_proximity`

## Source Coverage
- gop:gope: `3`
- jop:jope: `3`
- vop:vope: `3`
- wot:wote: `1`

## Pilot Replacements
- bop/bope (source=gop:gope, nearest=1/1)
- kop/kope (source=gop:gope, nearest=1/1)
- zop/zope (source=gop:gope, nearest=1/1)
- bop/bope (source=vop:vope, nearest=1/1)
- kop/kope (source=vop:vope, nearest=1/1)
- zop/zope (source=vop:vope, nearest=1/1)
- kot/kote (source=wot:wote, nearest=1/1)
- bop/bope (source=jop:jope, nearest=1/1)
- kop/kope (source=jop:jope, nearest=1/1)
- zop/zope (source=jop:jope, nearest=1/1)

## Controls
- fot/fote (existing_control_anchor)
- zot/zote (existing_control_anchor)
- jop/jope (existing_control_anchor)
