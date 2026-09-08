#!/usr/bin/env bash
# Verify which data sources are reachable FROM YOUR machine.
# The research pack was assembled behind a restricted network, so several
# endpoints below could not be tested there. Run this first.
#
# Usage: bash scripts/verify_sources.sh
set -uo pipefail

PASS=0; FAIL=0
BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; OFF=$'\033[0m'

check() {  # check <label> <url> [expect_substring]
  local label="$1" url="$2" expect="${3:-}"
  local code size body tmp
  tmp=$(mktemp)
  code=$(curl -sSL --max-time 45 -o "$tmp" -w '%{http_code}' "$url" 2>/dev/null) || true
  code=${code:-000}
  size=$(wc -c < "$tmp" | tr -d ' ')
  if [[ "$code" == "200" && "$size" -gt 200 ]]; then
    if [[ -n "$expect" ]] && ! grep -qi -- "$expect" "$tmp"; then
      printf "  %s~%s %-46s HTTP %s, %s bytes, but %q not found\n" "$YEL" "$OFF" "$label" "$code" "$size" "$expect"
    else
      printf "  %s✓%s %-46s HTTP %s, %s bytes\n" "$GREEN" "$OFF" "$label" "$code" "$size"; PASS=$((PASS+1))
    fi
  else
    printf "  %s✗%s %-46s HTTP %s, %s bytes\n" "$RED" "$OFF" "$label" "$code" "$size"; FAIL=$((FAIL+1))
  fi
  rm -f "$tmp"
}

echo "${BOLD}== Tier 1: core datasets ==${OFF}"
check "OurAirports airports.csv" \
      "https://davidmegginson.github.io/ourairports-data/airports.csv" "iso_region"
check "OurAirports runways.csv" \
      "https://davidmegginson.github.io/ourairports-data/runways.csv" "length_ft"
check "BTS TranStats (T-100 field list)" \
      "https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FIL" "Passengers"
check "BTS TranStats home" \
      "https://www.transtats.bts.gov/"
check "FAA TAF portal" \
      "https://taf.faa.gov/"
check "FAA TAF landing page" \
      "https://www.faa.gov/data_research/aviation/taf"

echo
echo "${BOLD}== Tier 2: FAA supplements ==${OFF}"
check "FAA enplanements (CY2024 xlsx)" \
      "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/ARP-cy2024-all-enplanements.xlsx"
check "FAA enplanements index page" \
      "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger"
check "FAA AC 150/5060-5 (capacity & delay)" \
      "https://www.faa.gov/documentlibrary/media/advisory_circular/150_5060_5.pdf"
check "FAA SFO capacity profile" \
      "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/profiles/SFO-Airport-Capacity-Profile-2019.pdf"
check "FAA NPIAS" \
      "https://www.faa.gov/airports/planning_capacity/npias"
check "FAA NAS status (live delays, XML)" \
      "https://nasstatus.faa.gov/api/airport-status-information"

echo
echo "${BOLD}== Tier 3: optional / nice-to-have ==${OFF}"
check "aviationapi.com (KSFO)" \
      "https://api.aviationapi.com/v1/airports?apt=KSFO"
check "OpenSky (anonymous states)" \
      "https://opensky-network.org/api/states/all?lamin=37.5&lomin=-122.6&lamax=37.8&lomax=-122.2"
check "data.transportation.gov (Socrata)" \
      "https://data.transportation.gov/api/catalog/v1?q=T-100&limit=1"
check "US Census API discovery" \
      "https://api.census.gov/data.json"

echo
echo "${BOLD}== BTS bulk pre-zipped mirror (filenames drift — probe) ==${OFF}"
for f in T_T100D_SEGMENT_ALL_CARRIER.zip T_T100_SEGMENT_ALL_CARRIER.zip T_MASTER_CORD.zip; do
  code=$(curl -sSI --max-time 30 -o /dev/null -w '%{http_code}' "https://transtats.bts.gov/PREZIP/$f" 2>/dev/null) || true
  code=${code:-000}
  if [[ "$code" == "200" ]]; then
    printf "  %s✓%s PREZIP/%-38s HTTP %s\n" "$GREEN" "$OFF" "$f" "$code"; PASS=$((PASS+1))
  else
    printf "  %s✗%s PREZIP/%-38s HTTP %s\n" "$RED" "$OFF" "$f" "$code"; FAIL=$((FAIL+1))
  fi
done

echo
echo "${BOLD}== LLM / voice provider keys ==${OFF}"
for v in GROQ_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY; do
  if [[ -n "${!v:-}" ]]; then printf "  %s✓%s %s is set\n" "$GREEN" "$OFF" "$v"
  else printf "  %s–%s %s not set\n" "$YEL" "$OFF" "$v"; fi
done
if [[ -n "${GROQ_API_KEY:-}" ]]; then
  code=$(curl -sS --max-time 25 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models 2>/dev/null) || true
  code=${code:-000}
  [[ "$code" == "200" ]] && printf "  %s✓%s Groq key valid (models endpoint 200)\n" "$GREEN" "$OFF" \
                         || printf "  %s✗%s Groq key check returned HTTP %s\n" "$RED" "$OFF" "$code"
fi

echo
echo "${BOLD}Summary: ${GREEN}${PASS} reachable${OFF}, ${RED}${FAIL} not reachable${OFF}"
echo "A failure here may mean the endpoint moved, or just that your network blocks it."
echo "Anything red that you planned to depend on: find the current URL before you build on it."
