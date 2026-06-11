"""Zone identifiers: ISO 3166-2:IN codes (post-2023 update: IN-CG, IN-OD, IN-UK).

VIDYUT_PRAVAH_SLUGS maps vidyutpravah.in /state-data/<slug> to our zone ids.
Odisha has no state page link on the Vidyut Pravah homepage (only a price span
on the hover map) — slug candidates are tried by the scraper and skipped on 404.
"""

VIDYUT_PRAVAH_SLUGS: dict[str, str] = {
    "andhra-pradesh": "IN-AP",
    "arunachal-pradesh": "IN-AR",
    "assam": "IN-AS",
    "bihar": "IN-BR",
    "chandigarh": "IN-CH",
    "chhattisgarh": "IN-CG",
    "delhi": "IN-DL",
    "goa": "IN-GA",
    "gujarat": "IN-GJ",
    "haryana": "IN-HR",
    "himachal-pradesh": "IN-HP",
    "jammu-kashmir": "IN-JK",
    "jharkhand": "IN-JH",
    "karnataka": "IN-KA",
    "kerala": "IN-KL",
    "madhya-pradesh": "IN-MP",
    "maharashtra": "IN-MH",
    "manipur": "IN-MN",
    "meghalaya": "IN-ML",
    "mizoram": "IN-MZ",
    "nagaland": "IN-NL",
    "odisha": "IN-OD",  # unverified slug, skipped on 404
    "puducherry": "IN-PY",
    "punjab": "IN-PB",
    "rajasthan": "IN-RJ",
    "sikkim": "IN-SK",
    "tamil-nadu": "IN-TN",
    "telangana": "IN-TS",
    "tripura": "IN-TR",
    "uttar-pradesh": "IN-UP",
    "uttarakhand": "IN-UK",
    "west-bengal": "IN-WB",
}

NATIONAL = "IN"
