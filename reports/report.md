# Media story comparison report

## Story #2

- Files: 3
- Sources: Le Monde, Brut, ARTE
- Weighted support: 2.51
- Local similarity: 0.30
- Similarity coverage: 1.00
- Best-neighbour similarity: 0.31
- Date/location guardrail score: 1.00
- Prototype score: 2.29
- Date signals: 2026-07-08
- Location signals: Lyon
- Recap confidence: High (81.0/100) — The recap is well supported by this local corpus. Still verify any volatile details before publishing.

**Date/location guardrails:**
- Date guardrail: shared primary date signal 2026-07-08.
- Location guardrail: shared location signal(s) Lyon.

**Suggested headline:** Fire at chemical factory injures fifteen people

Fire at chemical factory injures fifteen people: (71%) 15 injured | (29%) 2 dead and 13 injured. A fire broke out on Wednesday morning at a chemical factory near Lyon, forcing emergency services to evacuate nearby streets. According to local authorities, fifteen people were injured, most of them lightly, after inhaling smoke. The prefecture said the fire was under control by midday and that air-quality checks were continuing around the site. Residents near an industrial area outside Lyon were briefly evacuated after a fire at a chemical plant. Emergency services said smoke spread over several blocks before the blaze was contained. This dry-run recap is based on 3 local .txt file(s), reported by Le Monde, Brut, ARTE, with weighted support 2.51 and local similarity 0.30.

**Conflict / uncertain details:**
- casualty count: (71%) 15 injured | (29%) 2 dead and 13 injured
  Reason: Different casualty claims appear in Le Monde, ARTE and Brut.

**Files in cluster:**
- Le Monde: `samples/lemonde_factory_fire.txt` — Fire at chemical factory injures fifteen people
- Brut: `samples/brut_factory_fire.txt` — Huge smoke cloud after factory fire near Lyon
- ARTE: `samples/arte_factory_fire.txt` — Chemical plant fire near Lyon prompts evacuations

## Story #1

- Files: 3
- Sources: Independent / Unknown, France24, CNews
- Weighted support: 1.85
- Local similarity: 0.27
- Similarity coverage: 1.00
- Best-neighbour similarity: 0.30
- Date/location guardrail score: 0.80
- Prototype score: 1.90
- Date signals: 2026-07-07
- Location signals: Asia
- Recap confidence: High (78.4/100) — The recap is well supported by this local corpus. Still verify any volatile details before publishing.

**Date/location guardrails:**
- Date guardrail: shared primary date signal 2026-07-07.
- Location guardrail: location data is limited to one source or not corroborated; do not treat the place as fully confirmed.

**Suggested headline:** Sea surface temperatures keep rising, partly due to the appearance of a new El Niño

This year's El Niño likely to become a record-breaker, top expert says. France24 carries an AFP report saying the current El Niño is likely to become record-breaking in its overall strength. The article cites Tim Stockdale, an El Niño specialist at the European Centre for Medium-Range Weather Forecasts, who says forecast models are unusually strong and consistent in pointing toward an extreme event. The article explains that El Niño warms the central and eastern equatorial Pacific, changing global wind, pressure and rainfall patterns. CNews reports that forecast models are pointing toward a potentially extreme El Niño episode in 2026. The article presents El Niño as a climate phenomenon capable of disrupting weather patterns far beyond the tropical Pacific, with a stronger event increasing the likelihood of heat waves, droughts, heavy rain, floods and other extreme weather events. This dry-run recap is based on 3 local .txt file(s), reported by Independent / Unknown, France24, CNews, with weighted support 1.85 and local similarity 0.27.

**Files in cluster:**
- Independent / Unknown: `samples/jeuxvideo_ocean_temperature_el_nino.txt` — Sea surface temperatures keep rising, partly due to the appearance of a new El Niño
- France24: `samples/france24_el_nino_record_breaker.txt` — This year's El Niño likely to become a record-breaker, top expert says
- CNews: `samples/cnews_el_nino_extreme_forecast.txt` — El Niño forecast models point toward an "extreme" event

## Story #3

- Files: 1
- Sources: Independent / Unknown
- Weighted support: 0.47
- Local similarity: 1.00
- Similarity coverage: 0.00
- Best-neighbour similarity: 0.00
- Date/location guardrail score: 0.80
- Prototype score: 0.56
- Date signals: 2026-07-08
- Recap confidence: Low (6.3/100) — Treat the recap as a lead only. Search for more independent sources before relying on it.

**Date/location guardrails:**
- Date guardrail: shared primary date signal 2026-07-08.
- Location guardrail: no usable location signal found.

**Suggested headline:** Government presents new housing bill

Government presents new housing bill. The government presented a new housing bill on Wednesday aimed at increasing construction in dense urban areas. Ministers said the plan would simplify permits and encourage local authorities to open more land for residential projects. Opposition lawmakers criticised the proposal, saying it did not provide enough funding for social housing. This dry-run recap is based on 1 local .txt file(s), reported by Independent / Unknown, with weighted support 0.47 and local similarity 1.00.

**Files in cluster:**
- Independent / Unknown: `samples/independent_housing_bill.txt` — Government presents new housing bill
