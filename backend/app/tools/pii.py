import re
from typing import Any

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

_provider = NlpEngineProvider(nlp_configuration={
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
})
_analyzer = AnalyzerEngine(nlp_engine=_provider.create_engine())
_anonymizer = AnonymizerEngine()

# Only block these sensitive financial/identity entity types
_PII_BLOCK_TYPES = {
    "CREDIT_CARD",       # card numbers
    "EMAIL_ADDRESS",     # email
    "PHONE_NUMBER",      # phone
    "US_SSN",            # US social security number
    "IN_AADHAAR",        # Aadhaar number (12-digit Indian ID)
}

# Aadhaar: 12-digit number (XXXX XXXX XXXX)
_AADHAAR_RE = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")
# SSN: XXX-XX-XXXX or XXX XX XXXX
_SSN_RE = re.compile(r"\b\d{3}[\s\-]\d{2}[\s\-]\d{4}\b")


def pii_validator(text: str) -> dict[str, Any]:
    results = _analyzer.analyze(text=text, language="en")
    findings = [
        r.entity_type for r in results
        if r.entity_type in _PII_BLOCK_TYPES
    ]
    # Regex fallbacks for entities Presidio misses with en_core_web_sm
    if "IN_AADHAAR" not in findings and _AADHAAR_RE.search(text):
        findings.append("IN_AADHAAR")
    if "US_SSN" not in findings and _SSN_RE.search(text):
        findings.append("US_SSN")
    return {"safe": not findings, "findings": findings}


def redact(text: str) -> str:
    results = _analyzer.analyze(text=text, language="en")
    relevant = [r for r in results if r.entity_type in _PII_BLOCK_TYPES]
    if not relevant:
        return text
    return _anonymizer.anonymize(text=text, analyzer_results=relevant).text
