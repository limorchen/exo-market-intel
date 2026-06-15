"""Pricing tier classification for active entities, keyed by entity name.

Tiers feed `calculate_gtm_score()` (utils/scoring.py): entities pricing their
products/services more aggressively run on better margins and tend to be more
open to adopting new/improved products — making them better first-wave GTM
targets. Premium = highest weight, mass = lowest.

Classification is segment-specific (apples-to-apples), since the three pricing
universes are not directly comparable:

- Distributors (B2B, per-vial / per-SKU pricing):
    premium   ~ branded high-potency MSC exosome lines, $800-1,300+/vial
                 (e.g. Kimera Labs XoGlo, ExoCoBio/Benev ERC+)
    mid-market ~ broad regenerative-biologics catalogs where exosomes are one
                 SKU among PRP/allografts/peptides
    mass      ~ large diversified pharma/medical distributors (exosomes a
                 negligible commodity line)

- MSO / KOL (patient-facing, per-session or per-protocol pricing):
    mass      ~ $200-700/session — exosome is a low-cost add-on at
                 high-volume franchise wellness chains
    mid-market ~ $700-2,500/session — dedicated exosome facial/hair line at
                 an independent regen/medspa clinic
    premium   ~ $2,500-10,000+ per protocol/cycle or membership — systemic /
                 orthopedic exosome injections, concierge longevity programs
                 (e.g. R3 Stem Cell $3,950-10,500, QC Kinetix $2,500-10,000,
                 Fountain Life $2,995-21,500/yr)

- CME (course / certification pricing):
    mass      ~ low-cost or institution-subsidized CME credits
    mid-market ~ large annual congress/membership registration, $1,000-3,000
                 (e.g. Empire Medical Training $1,699-1,899)
    premium   ~ hands-on certification with live-patient procedures,
                 $3,000-7,000+ (e.g. R3 Medical Training, Cell Surgical
                 Network training)

KOL (individual specialist practices) are classified premium across the
board: their boutique/concierge positioning and systemic-injection protocols
align with the premium MSO benchmark above.
"""

from __future__ import annotations

PRICING_TIERS: dict[str, str] = {
    # ---- Distributors (B2B, per-vial) ----------------------------------
    # premium: branded high-potency MSC exosome product lines
    "BioRegenEx": "premium",
    "JuveXO": "premium",
    "Predictive Biotech": "premium",
    "Kimera Labs": "premium",
    "Benev Company (ExoCoBio)": "premium",
    "RegenOMedix": "premium",
    "Regen Suppliers": "premium",
    "ExaVeyra Sciences": "premium",
    # mid-market: broad regenerative biologics distributors (exosomes one SKU among many)
    "Emcyte Corporation": "mid-market",
    "Liveyon": "mid-market",
    "Regen Lab USA": "mid-market",
    "BioXcellerator": "mid-market",
    "Vivex Biologics": "mid-market",
    "Aesthetics Distributions": "mid-market",
    "Zeo Scientifix": "mid-market",
    "OmniGenix": "mid-market",
    "MedShift": "mid-market",
    "Prime Regenerative": "mid-market",
    "APEX Biologix": "mid-market",
    # mass: large diversified pharma/medical distributor
    "McKesson Corporation": "mass",

    # ---- CME (course / certification pricing) -------------------------
    # mid-market: large annual congress / membership registration ($1,000-3,000)
    "A4M — American Academy of Anti-Aging Medicine": "mid-market",
    "AMMG — Age Management Medicine Group": "mid-market",
    "Empire Medical Training — Exosome CME": "mid-market",
    # premium: hands-on certification with live-patient procedures / high-end summit
    "The Stem Cell Conference": "premium",
    "R3 Medical Training": "premium",
    "Cell Surgical Network — Physician Training Program": "premium",
    # mass: institution-subsidized CME
    "Baptist Health CME — Lifestyle & Longevity Medicine": "mass",

    # ---- KOL (individual specialist / concierge practices) ------------
    # all premium: boutique positioning, systemic/orthopedic injection protocols
    "Dr. Harry Adelson": "premium",
    "Dr. Joy Kong": "premium",
    "Dr. Amy Killen": "premium",
    "Dr. Todd Ovokaitys": "premium",
    "Dr. Mark Berman": "premium",
    "Dr. Elliot Lander": "premium",
    "Dr. John Lieurance": "premium",
    "Dr. Ravi Patel — LivWell Method": "premium",
    "Dr. Travis Whitney — Innate Healthcare Institute": "premium",
    "Dr. Farhan Malik — Atlanta Innovative Medicine": "premium",
    "Dr. Joseph Purita": "premium",
    "Dr. Douglas Spiel": "premium",
    "Dr. Ian White": "premium",

    # ---- MSO (patient-facing, per-session / per-protocol pricing) -----
    # premium: $2,500-10,000+ per protocol/cycle, systemic/orthopedic or concierge longevity
    "R3 Stem Cell": "premium",
    "Fountain Life": "premium",
    "Next Health": "premium",
    "Agentis Longevity": "premium",
    "Humanaut Health": "premium",
    "QC Kinetix": "premium",
    "LifeSpan Medicine": "premium",
    "Cendant Stem Cell Center": "premium",
    "Stem Cell Therapy Center of Nashville": "premium",
    "American Stem Cells & Peptides": "premium",
    "New Hampshire Regenerative Center": "premium",
    "Greystone Regenerative Medicine": "premium",
    "Charleston Regenerative Medicine": "premium",
    "Vitality Forever": "premium",
    "Las Vegas Medical Institute": "premium",
    "Carolina Healthspan Institute": "premium",
    "The Alchemy Clinic": "premium",
    "Allure Medical": "premium",
    # mid-market: $700-2,500/session, dedicated exosome facial/hair line at independent medspa
    "Ascend Aesthetic Partners": "mid-market",
    "MedSpa Partners": "mid-market",
    "Serene Med Spas": "mid-market",
    "CSLC RegenCen": "mid-market",
    "Dermani MEDSPA": "mid-market",
    "LivingYoung Center": "mid-market",
    "Princeton Medspa Partners": "mid-market",
    "Alpha Aesthetics Partners": "mid-market",
    "Metropolis Dermatology": "mid-market",
    "Skin Perfect Medical Aesthetics": "mid-market",
    "Aesthetic Partners": "mid-market",
    "Advanced MedAesthetic Partners (AMP)": "mid-market",
    "Spa 43 — RENEW Longevity Program": "mid-market",
    "Skin Boss Med Spa": "mid-market",
    "Michigan Integrative Health": "mid-market",
    "Ageless Center Kentucky": "mid-market",
    "CaloSpa Rejuvenation Center": "mid-market",
    "RevitaLife MD": "mid-market",
    "Advanced Skin & Vein Care Centers KY": "mid-market",
    "Coachlight Clinic & Spa": "mid-market",
    "GVO Partners": "mid-market",
    "Denver Wellness & Aesthetics Center": "mid-market",
    "National Laser Institute": "mid-market",
    "Omnigenix — Atlanta": "mid-market",
    # mass: $200-700/session, low-cost add-on at high-volume franchise wellness chains
    "Restore Hyper Wellness": "mass",
    "Serotonin Centers": "mass",
    "4Ever Young Anti-Aging Solutions": "mass",
    "VIO Med Spa": "mass",
    "Liquivida Wellness Centers": "mass",
    "The DRIPBaR": "mass",
    "Anderson Longevity Clinic": "mass",
    "Optimize Wellness & Aesthetics": "mass",
}


# Segment + tier benchmark description, shown for entities without an
# entity-specific confirmed price (see PRICING_BASIS_OVERRIDES below).
PRICING_BASIS: dict[tuple[str, str], str] = {
    ("distributor", "premium"): "Branded high-potency MSC exosome line, ~$800-1,300+/vial",
    ("distributor", "mid-market"): "Broad regenerative-biologics catalog — exosomes one SKU among PRP/allografts/peptides",
    ("distributor", "mass"): "Large diversified pharma/medical distributor — exosomes a negligible commodity line",
    ("MSO", "premium"): "Systemic/orthopedic exosome protocol or concierge longevity program, ~$2,500-10,000+ per cycle/membership",
    ("MSO", "mid-market"): "Dedicated exosome facial/hair-restoration line at independent medspa, ~$700-2,500/session",
    ("MSO", "mass"): "Low-cost exosome add-on at high-volume franchise wellness chain, ~$200-700/session",
    ("KOL", "premium"): "Boutique/concierge specialist practice, systemic exosome injections, ~$2,500-10,000+ per protocol",
    ("CME", "premium"): "Hands-on certification with live-patient procedures / high-end summit, ~$3,000-7,000+",
    ("CME", "mid-market"): "Large annual congress/membership registration, ~$1,000-3,000",
    ("CME", "mass"): "Institution-subsidized CME credits, low/no cost",
}

# Entity-specific confirmed prices from web research (override the generic
# segment+tier benchmark above when available).
PRICING_BASIS_OVERRIDES: dict[str, str] = {
    "R3 Stem Cell": "Confirmed: $3,950-10,500 per 100B-exosome treatment; combo packages up to $10,500",
    "QC Kinetix": "Confirmed: $2,500-10,000 per regenerative treatment cycle",
    "Fountain Life": "Confirmed: $2,995-21,500/yr membership tiers (CORE to APEX)",
    "Empire Medical Training — Exosome CME": "Confirmed: $1,699-1,899 exosome certification course",
    "Kimera Labs": "Confirmed: ~$950/vial (XoGlo branded MSC exosome line)",
    "Benev Company (ExoCoBio)": "Confirmed: $800-1,300/vial (ERC+ branded MSC exosome line)",
}


def get_pricing_basis(entity_type: str, pricing_tier: str, name: str) -> str:
    """Return the pricing evidence used to assign this entity's tier."""
    if name in PRICING_BASIS_OVERRIDES:
        return PRICING_BASIS_OVERRIDES[name]
    return PRICING_BASIS.get((entity_type, pricing_tier), "No comparable pricing data found — defaulted to 'unknown'")
