# The expansion plan - terciles, probabilities, 500 hPa height, and the mean

**NOTHING IN HERE HAS BEEN BUILT.**  This is the map-out the owner asked
for on 17 Nov 2026, written down before any of it is started.  The rules
that still hold while it is written: the operational site is not touched
without the owner's explicit approval, and every new data pull gets a
plan first.

## 1. What the CDS actually offers (checked 17 Nov, read-only)

| dataset | what it is | what we would use it for |
|---|---|---|
| `seasonal-monthly-single-levels` | monthly statistics, single levels | the **mean** fields, and the monthly anomalies we already draw |
| `seasonal-monthly-pressure-levels` | monthly statistics, pressure levels | **geopotential at 500 hPa** (`geopotential`) - the mean and the hindcast climate mean, so the anomaly is the model's own |
| `seasonal-postprocessed-single-levels` | **anomalies**, single levels | the existing snowfall / temperature / SST anomalies |
| `seasonal-original-single-levels` | daily and sub-daily, single levels | the daily 10 hPa wind the stratosphere page uses |

**The tercile probabilities are the one open question.**  The CDS's
seasonal datasets carry the mean and the anomaly, but no "probability of
tercile" variable: the tercile products the C3S publishes live on the C3S
charts, not in the CDS seasonal datasets.  That leaves two routes, and
the choice matters:

- **Compute the terciles ourselves** from the ensemble we already pull
  and each model's **own hindcast climate**: the 33rd and 67th
  percentiles of the hindcast for the same month are the tercile
  boundaries, and the fraction of the ensemble members in each tercile is
  the probability.  This keeps the house rule - *the climatology comes
  from the same product as the data it normalises* - and it gives us the
  tercile boundaries as well as the probabilities, which the published
  probability product does not.  **This is the recommended route.**
- Pull the C3S's published tercile probabilities from the C3S's own
  service.  Less work, but the terciles then belong to the C3S's
  climatology rather than to the model's, and the boundaries are not
  ours to draw.

## 2. What the products would be

### a. Terciles and probabilities for the seasonal guidance
The three categories every seasonal centre already speaks in: **below
normal, near normal, above normal**, with the probability of each.

- **The map**: a third mode on the existing maps page - Snowfall /
  Anomaly / **Probability** - painting the three categories in three
  flat house colours (the brown/near/teal of the house anomaly palette),
  with the legend carrying the three categories and each category's
  percentage for the season shown.
- **The static panels**: one probability panel per model per season, in
  the house style, with the tercile boundaries drawn as contours - which
  is the panel that would actually let a reader see *where* the
  boundary is, not just which side of it a place falls.
- **The numbers**: the probability of each tercile, written on the panel
  and in the map's readout.
- **Variables**: 2 m temperature, sea-surface temperature and total
  precipitation (the three the C3S itself uses), plus snowfall, which we
  already have the anomaly for.

### b. 500 hPa geopotential height anomalies
A new product family and a new tab - **Troposphere**, the sibling of the
existing Stratosphere page.

- The route: `seasonal-monthly-pressure-levels`, variable `geopotential`,
  at 500 hPa, with the hindcast climate mean, so the anomaly is the
  model's own.
- The units: the data is geopotential in m2/s2; the geopotential height
  in metres is that divided by 9.80665.  The panel should read in metres
  of height.
- The form: the same house style as the stratosphere panels (the polar
  section's own furniture is fine *here* - this is a new chart family,
  not the snowfall map), plus the interactive map in the same component
  as the snowfall map, with a symmetric ladder of its own.
- The scope: the 500 hPa anomaly is the headline; the question to settle
  is whether one level is enough or whether 850 hPa (the moisture
  transport and the fronts) comes with it.

### c. The actual mean
Today every field we publish is an anomaly. The mean is the other half
of the story and it is the same data: one more mode on the map
(**Mean**), and one more panel set, with the model's own hindcast mean
as the reference rather than the forecast.

### d. The seasons
The panels run Dec -> Jun today. The terciles are usually quoted for
DJF / MAM / JJA / SON. Whether the new products follow the panels'
window or the seasonal convention is a decision to make before
building, because it changes the pulls.

## 3. How it would be built

1. **The pulls** - the same fetch scripts, new variables: the 500 hPa
   forecast plus its hindcast climate mean per centre (about 12 requests
   across the six C3S centres, on the account-wide queue that is capped
   at two requests at a time).  The terciles need **no** new requests -
   they are computed from the members we already have.
2. **The export** - the same manifest-plus-PNG machinery the snowfall
   map uses: one 8-bit greyscale raster per field plus a JSON manifest,
   each with its own ladder table, so the browser never invents a ramp.
3. **The browser** - the map component gains the extra modes (Mean,
   Probability); the tercile mode paints categories rather than a
   continuous field, so its legend is categorical.
4. **The pages** - a new Troposphere tab with the house panels, and the
   probability panels on the snowfall page.
5. **The tests** - the two key-free tests that already exist (the
   exporter against a synthetic model, the page in headless Chromium)
   would be extended to cover the new modes and the new ladders.

**Where it goes first: the development site.**  The operational site is a
separate, deliberate step, as always.

## 4. The questions to settle before the first pull

1. **Terciles: ours or the C3S's?**  (recommend ours - see above)
2. **Which variables get terciles?**  2 m temperature, SST, total
   precipitation, snowfall?
3. **500 hPa alone, or 850 hPa with it?**
4. **The season windows**: the panels' Dec -> Jun, or the seasonal DJF /
   MAM / JJA / SON?
5. **Mean for which fields?**  2 m temperature, SST, precipitation,
   snowfall - all four, or a first one?
6. **Cost**: about 12 new C3S requests (the queue is capped at two at a
   time, so this is hours of queueing, not minutes), roughly a day of
   work for the exporter, the browser modes, the new page and the tests.

## 5. What is NOT in this plan

No new colour ramp invented in the browser; no resampling of a model's
grid; no chart family borrowing another chart family's furniture; no
new background that makes the maps look like another site's; and
nothing on the operational site without the owner's approval.
