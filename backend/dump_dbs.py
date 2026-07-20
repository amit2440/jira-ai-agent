import sqlite3
import json
import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

def dump_db():
    output = {'assistant_db': {}, 'chroma_db': {}}
    
    # 1. Dump assistant.db
    if os.path.exists('assistant.db'):
        conn = sqlite3.connect('assistant.db')
        conn.row_factory = sqlite3.Row
        for table in ['runs', 'knowledge', 'execution_logs']:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                output['assistant_db'][table] = [dict(row) for row in rows]
            except Exception as e:
                output['assistant_db'][table] = f"Error: {e}"
        conn.close()
        
    # 2. Dump Chroma DB
    if os.path.exists('chroma_db'):
        try:
            emb = HuggingFaceEmbeddings(model_name='BAAI/bge-small-en-v1.5')
            chroma = Chroma(persist_directory='chroma_db', embedding_function=emb)
            chroma_data = chroma.get()
            output['chroma_db'] = chroma_data
        except Exception as e:
            output['chroma_db'] = f"Error: {e}"
            
    # Write to file
    with open('db_dump.json', 'w') as f:
        json.dump(output, f, indent=2)

if __name__ == '__main__':
    dump_db()
