import sys, pandas as pd, numpy as np
a = pd.read_csv(sys.argv[1], low_memory=False)
a['rec_side'] = a.rec_side.where(a.rec_side.notna(), None)
spot = a.fum_yl_desc.fillna(a.fum_yl_nfl)
den = a[spot >= 100].copy()


def cat(x):
    if pd.isna(x.rec_side):
        return 'out_of_bounds_no_recovery' if x.oob_text else 'no_recovery_parsed'
    if x.rec_side == 'defense' and x.rec_zone == 'posteam_EZ': return 'defense_recovers_in_offense_EZ'
    if x.rec_side == 'offense' and x.rec_zone == 'posteam_EZ': return 'offense_recovers_in_own_EZ'
    if x.rec_side == 'defense': return 'defense_recovers_in_field_or_own_EZ'
    return 'offense_recovers_in_field_or_opp_EZ'


den['cat'] = den.apply(cat, axis=1)
print('DENOMINATOR: fumble spot at or past offense goal line, by era')
print(pd.crosstab(den.era, den.official, margins=True).to_string())
print('\nDENOMINATOR by category x official (all eras)')
print(pd.crosstab(den.cat, den.official, margins=True).to_string())
print('\nOWN END ZONE RECOVERIES (recovery spot beyond offense goal line), by era')
oz = a[a.rec_zone == 'posteam_EZ'].copy()
oz['cat'] = oz.apply(cat, axis=1)
print(pd.crosstab([oz.era, oz.cat], oz.official, margins=True).to_string())
print('\nDIRICHLET POSTERIOR MEAN for outcome given fumble at or past goal line, prior = 1 each')
classes = ['touchdown', 'safety', 'none', 'touchback']
rows = []
for era_name, g in list(den.groupby('era')) + [('1999-2025 pooled', den), ('2010-2025 modern', den[den.era != '1999-2009'])]:
    counts = g.official.value_counts().reindex(classes).fillna(0).astype(int)
    alpha = counts + 1
    mean = alpha / alpha.sum()
    rows.append({'era': era_name, 'n': int(counts.sum()), **{f'{c}_n': int(counts[c]) for c in classes},
                 **{f'{c}_p': round(float(mean[c]), 3) for c in classes}})
print(pd.DataFrame(rows).to_string(index=False))
print('\nPARSE COVERAGE by era (rows with a recovery spot read)')
print(a.groupby('era').apply(lambda g: f"{int(g.rec_side.notna().sum())}/{len(g)}").to_string())
print('\nRECONCILIATION (expected from recovery spot vs official flags, parsed rows)')
p = a[a.rec_side.notna()]
print(pd.crosstab(p.expected, p.official).to_string())
