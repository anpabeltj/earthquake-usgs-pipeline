"""
Generate the region lookup seed used by the silver models.

Neither earthquake source gives a country in a form that can be joined
on directly, and the two fail in different ways:

  USGS has no country field at all, only a free text place description.
  The segment after the last comma is either a country name or, for
  events inside the United States, a state.

  NCEI does have a country column, but writes it uppercase and in its
  own style: "USA", "UK", "MYANMAR (BURMA)".

The seed resolves both, and is built from three parts:

  1. Country names, for example "Greece" or "Papua New Guinea".
     From country_converter, which also supplies the continent.

  2. US state names and abbreviations, for example "Texas" and "CA".
     From pycountry subdivisions. Both spellings are needed because
     USGS uses the abbreviation for some states and the full name for
     others.

  3. A short list of spellings the sources use that no library matches.
     See SOURCE_ALIASES below.

The ISO3 code is carried alongside the country name so earthquake data
can be joined to other country level sources on a stable code rather
than on a display name. World Bank writes "Russian Federation" where
country_converter writes "Russia", and matching those by text would
silently drop rows.

Nothing here is written by hand except the alias list, so the seed can
be regenerated at any time without losing work.

Events with no country are deliberately left unmatched. In USGS that
means open ocean names such as "Southwest Indian Ridge"; in NCEI it
means "ATLANTIC OCEAN", distant dependencies, and the ambiguous
"CONGO". Inventing a country would put a claim in the data that does
not exist in the source. Those rows keep a null country and the
dashboard shows the region name itself.

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

# Spellings the earthquake sources use that country_converter does not
# produce, mapped to the ISO3 of the country they mean. Keyed on ISO3
# rather than on the library's display name so a rename upstream does
# not break the alias.
#
# From USGS, whose place text is free form:
#   TUR  writes "Turkey"; the library follows the 2022 rename to
#        "Türkiye".
#   FSM  writes "Micronesia"; the library appends the form of
#        government, "Micronesia, Fed. Sts.".
#   WLF  writes "Wallis and Futuna"; the library appends "Islands".
#
# From NCEI, whose country column is uppercase and uses its own naming:
#   USA  writes "USA"; the library writes "United States". 62 events.
#   MMR  writes "MYANMAR (BURMA)". 13 events.
#   KGZ  writes "KYRGYZSTAN"; the library writes "Kyrgyz Republic".
#   GBR  writes "UK"; the library writes "United Kingdom".
#   BIH  writes "BOSNIA-HERZEGOVINA", hyphenated where the library
#        spells out "and".
#   CZE  writes "CZECH REPUBLIC"; the library follows the rename to
#        "Czechia".
#
# Matching is case insensitive downstream, so the case written here
# does not matter.
#
# Deliberately not listed: NCEI's "CONGO", which does not say whether
# it means DR Congo or Congo Republic, and picking one would be a
# guess. Also excluded are dependencies far from the mainland that
# administers them, such as "USA TERRITORY", "KERMADEC ISLANDS (NEW
# ZEALAND)" and "SOUTH GEORGIA AND THE SOUTH SANDWICH", and open ocean
# names like "ATLANTIC OCEAN". Those follow the same rule already
# applied to the USGS place text: no country is claimed where the
# source does not name one.
SOURCE_ALIASES = {
    "Turkey": "TUR",
    "Micronesia": "FSM",
    "Wallis and Futuna": "WLF",
    "USA": "USA",
    "MYANMAR (BURMA)": "MMR",
    "KYRGYZSTAN": "KGZ",
    "UK": "GBR",
    "BOSNIA-HERZEGOVINA": "BIH",
    "CZECH REPUBLIC": "CZE",
}


def build_country_rows():
    """Every country with its ISO3 code and continent, from country_converter."""
    rows = []
    converter = coco.CountryConverter()

    for _, record in converter.data.iterrows():
        name = str(record["name_short"]).strip()
        continent = str(record["continent"]).strip()
        iso3 = str(record["ISO3"]).strip()

        if not name or not continent or continent.lower() == "nan":
            continue

        if not iso3 or iso3.lower() == "nan":
            iso3 = ""

        rows.append((name, name, iso3, continent))

    return rows


def build_alias_rows(country_rows):
    """
    Add the source specific spellings from SOURCE_ALIASES.

    Each alias reuses the country name and continent already produced
    for that ISO3, so an alias can never introduce a country the
    libraries do not know about. An alias whose ISO3 is missing is
    reported rather than skipped quietly, since that means the library
    changed and the alias needs revisiting.
    """
    by_iso3 = {}
    for _, country, iso3, continent in country_rows:
        if iso3:
            by_iso3[iso3] = (country, continent)

    rows = []
    for source_name, iso3 in SOURCE_ALIASES.items():
        if iso3 not in by_iso3:
            print(f"  warning: alias {source_name!r} points at {iso3}, which is not in the library data")
            continue

        country, continent = by_iso3[iso3]
        rows.append((source_name, country, iso3, continent))

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

        rows.append((full_name, "United States", "USA", "America"))
        rows.append((abbreviation, "United States", "USA", "America"))

    return rows


def write_seed(rows):
    """Write the seed, dropping duplicate region names."""
    merged = {}

    for region, country, iso3, continent in rows:
        key = region.strip()
        if key:
            merged[key] = (country.strip(), iso3.strip(), continent.strip())

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region", "country", "iso3", "continent"])

        for region in sorted(merged):
            country, iso3, continent = merged[region]
            writer.writerow([region, country, iso3, continent])

    return len(merged)


def main():
    countries = build_country_rows()
    aliases = build_alias_rows(countries)
    states = build_us_state_rows()

    print(f"countries from country_converter: {len(countries)}")
    print(f"source spelling aliases:          {len(aliases)}")
    print(f"US state entries from pycountry:   {len(states)}")

    total = write_seed(countries + aliases + states)

    print(f"seed written to {OUTPUT_PATH}")
    print(f"unique regions: {total}")


if __name__ == "__main__":
    main()