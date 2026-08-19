# Verified LinkedIn profiles for named founders/executives/medical directors
# who appear in entity_registry `notes` text but aren't their own entity row.
# Researched 2026-08 via web search + bio cross-reference (name, title, and
# affiliated org must all match before inclusion here).
#
# Names not found with confidence are intentionally omitted — they stay as
# plain text in the Notes panel rather than risk linking to the wrong person.

PEOPLE_LINKEDIN = {
    "Dr. David Greene": "https://www.linkedin.com/in/drdavidgreene/",
    "Dr. Darshan Shah": "https://www.linkedin.com/in/darshanshahmd/",
    "Kevin Peake": "https://www.linkedin.com/in/kevin-peake-8b2a3a3b/",
    "Dr. Gustav Lo": "https://www.linkedin.com/in/gustav-lo-124b39224/",
    "Dr. Terry Matthews": "https://www.linkedin.com/in/dr-terry-matthews-27732531/",
    "Dr. Nathaniel Shober": "https://www.linkedin.com/in/nathaniel-shober-180a6a243/",
    "Peter Diamandis": "https://www.linkedin.com/in/peterdiamandis/",
    "Tony Robbins": "https://www.linkedin.com/in/officialtonyrobbins/",
    "Dr. M. Bradley Calobrace": "https://www.linkedin.com/in/brad-calobrace-4669674a/",
    "Dr. David Robbins": "https://www.linkedin.com/in/dr-david-robbins-a198b538/",
    # Inferred from LinkedIn post URLs (consistent slug across two posts) —
    # LinkedIn blocks direct profile fetches, so this could not be confirmed
    # by loading the profile page itself.
    "Dr. Michael Young": "https://www.linkedin.com/in/michael-young-b11b49267/",
    # Reused from existing KOL entity records (Dr. Mark Berman / Dr. Elliot
    # Lander each have their own entity_registry row with a verified
    # linkedin_url) — duplicated here so mentions of them in OTHER entities'
    # notes (e.g. Cell Surgical Network) also get linked.
    "Dr. Berman": "https://www.linkedin.com/in/markberman",
    "Dr. Lander": "https://www.linkedin.com/in/elliot-lander-3b0a921b5",
}
