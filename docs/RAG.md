# RAG design

Documents are tokenized and scored with a 60% BM25-like lexical score and a 40% vector proxy. Results retain both component scores for observability. The interface is deliberately small: replace the proxy with Groq-compatible embedding generation and a vector database, then rerank top candidates. Retrieved titles and scores are saved on the run.
