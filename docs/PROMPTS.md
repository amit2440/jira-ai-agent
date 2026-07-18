# Prompt design

The runtime assigns temperatures by intent: planning `0.7`, extraction/review `0.1`, structured ticket output `0.0`, and report prose `0.8`. A production Groq adapter should supply role-specific prompt templates with: source requirement, retrieved context or Jira metrics, output JSON schema, constraints, and prompt version. Persist the prompt version and provider token usage in each event.
