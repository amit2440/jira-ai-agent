# Testing strategy

Run `PYTHONPATH=backend pytest backend/tests`. Unit-test every tool (especially PII and Jira request formation), each graph edge and approval branch, retrieval ranking, and API error paths. Add mocked Groq/Jira integration tests, browser tests for the approval gate, load tests, and security tests for PII bypass attempts.
