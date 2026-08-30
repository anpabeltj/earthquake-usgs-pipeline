"""
Generate the region lookup seed used by silver_usgs_location.

USGS has no country or continent field. All it gives is a free text
place description, and the segment after the last comma is either a
country name or, for events inside the United States, a state. Both
forms are produced here from standard libraries:

  1. Country names, for example "Greece" or "Papua New Guinea".
     From country_converter, which also supplies the continent.

  2. US state names and abbreviations, for example "Texas" and "CA".
     From pycountry subdivisions. Both spellings are needed because
     USGS uses the abbreviation for some states and the full name for
     others.

Nothing here is written by hand, so the seed can be regenerated at any
time without losing work.

Ocean events are deliberately left out. Their place field carries a
seismic region name such as "Southwest Indian Ridge", which belongs to
no country, and inventing one would put a claim in the data that does
not exist in the world. Those rows keep a null country and the
dashboard falls back to showing the region name itself.

Run it whenever the libraries are updated:

    python scripts/generate_region_seed.py

To see which regions are still unmatched after a load:

    select region_raw, count(*) as events
    from `PROJECT.silver.silver_usgs_location`
    where country is null
    group by region_raw
    order by events desc
"""

import csv
import os

import country_converter as coco
import pycountry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

OUTPUT_PATH = os.path.join(PROJECT_DIR, "dbt_project", "seeds", "seed_region_country.csv")


def build_country_rows():
    """Every country with its continent, from country_converter."""
    rows = []
    converter = coco.CountryConverter()

    for _, record in converter.data.iterrows():
        name = str(record["name_short"]).strip()
        continent = str(record["continent"]).strip()

        if not name or not continent or continent.lower() == "nan":
            continue

        rows.append((name, name, continent))

    return rows


def build_us_state_rows():
    """
    Every US state, listed twice.

    USGS is inconsistent here: "95 km W of Petrolia, CA" uses the
    abbreviation while "46 km NW of Toyah, Texas" spells it out, so both
    forms have to resolve.
    """
    rows = []

    for subdivision in pycountry.subdivisions.get(country_code="US"):
        full_name = subdivision.name.strip()
        # Codes arrive as "US-CA", and USGS writes only the "CA" part.
        abbreviation = subdivision.code.split("-")[-1].strip()

        rows.append((full_name, "United States", "America"))
        rows.append((abbreviation, "United States", "America"))

    return rows


def write_seed(rows):
    """Write the seed, dropping duplicate region names."""
    merged = {}

    for region, country, continent in rows:
        key = region.strip()
        if key:
            merged[key] = (country.strip(), continent.strip())

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region", "country", "continent"])

        for region in sorted(merged):
            country, continent = merged[region]
            writer.writerow([region, country, continent])

    return len(merged)


def main():
    countries = build_country_rows()
    states = build_us_state_rows()

    print(f"countries from country_converter: {len(countries)}")
    print(f"US state entries from pycountry:   {len(states)}")

    total = write_seed(countries + states)

    print(f"seed written to {OUTPUT_PATH}")
    print(f"unique regions: {total}")


if __name__ == "__main__":
    main()