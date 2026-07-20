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


_PII_SCORE_THRESHOLD = 0.85

# Entity types that are not sensitive — org/location names in project context are expected
_PII_IGNORE_TYPES = {"ORGANIZATION", "LOCATION", "DATE_TIME", "NRP"}

# Product/tool names spaCy misclassifies as PERSON
_KNOWN_NON_PERSONS = {
    "jira", "confluence", "github", "gitlab", "slack", "eoms", "brd",
    # Product/system names misclassified as PERSON by spaCy
    "active directory", "active", "directory", "azure", "ldap", "okta", "workday",
    "servicenow", "sap", "oracle", "salesforce", "sharepoint", "teams",
    # Jira/agile terms misclassified as PERSON
    "sprint", "backlog", "epic", "scrum", "kanban", "agile",
}


def pii_validator(text: str) -> dict[str, Any]:
    results = _analyzer.analyze(text=text, language="en")
    findings = [
        r.entity_type for r in results
        if r.score >= _PII_SCORE_THRESHOLD
        and r.entity_type not in _PII_IGNORE_TYPES
        and text[r.start:r.end].lower() not in _KNOWN_NON_PERSONS
    ]
    return {"safe": not findings, "findings": findings}


def redact(text: str) -> str:
    results = _analyzer.analyze(text=text, language="en")
    if not results:
        return text
    return _anonymizer.anonymize(text=text, analyzer_results=results).text
