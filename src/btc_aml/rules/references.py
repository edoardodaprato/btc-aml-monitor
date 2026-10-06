"""Regulatory and typological references cited by the rules.

References point to the *section* of each source that describes the typology.
Paragraph-level citations should be verified against the official texts before
the tool is used in a regulated context.
"""

FATF_RFI = "FATF (2020) Red Flag Indicators of ML/TF - Virtual Assets"
FATF_SIZE_FREQUENCY = f"{FATF_RFI} - transactions: size and frequency"
FATF_PATTERNS = f"{FATF_RFI} - transactions: patterns"
FATF_ANONYMITY = f"{FATF_RFI} - anonymity"
FATF_SOURCE_OF_FUNDS = f"{FATF_RFI} - source of funds or wealth"

EBA_CASP = (
    "EBA ML/TF Risk Factors Guidelines (EBA/GL/2021/02 as amended by EBA/GL/2024/01), "
    "Guideline 21 (CASPs)"
)
SANCTIONS = "OFAC SDN list; FATF Recommendation 6 (targeted financial sanctions)"
TFR = "Regulation (EU) 2023/1113 (Transfer of Funds Regulation), self-hosted address transfers"
