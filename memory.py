#import libries
import os
import uuid
import streamlit as st
from pinecone import Pinecone
from openai import OpenAI
from dotenv import load_dotenv
import logging

# 1. SETUP & LOGGING
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SparkStock-Memory")

PINECONE_KEY = os.getenv("PINECONE_API_KEY")
NVIDIA_KEY = os.getenv("NVIDIA_API_KEY")

# Connection to Pinecone
pc = Pinecone(api_key=PINECONE_KEY)
index = pc.Index("sparkstock")

# 2. NVIDIA EMBEDDING (With Zero-Vector Safety)
def get_nvidia_embedding(text):
    if not NVIDIA_KEY: return None
    client_nv = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_KEY)
    
    # HINDI TOKEN SAFETY: Hindi characters take more tokens, so keeping it 400 chars.
    safe_text = text[:400] 
    try:
        response = client_nv.embeddings.create(
            input=[safe_text],
            model="nvidia/nv-embedqa-e5-v5",
            encoding_format="float",
            extra_body={"input_type": "query"}
        )
        vector = response.data[0].embedding
        # Fallback if vector is all zeros (Pinecone requirement)
        if not vector or all(v == 0 for v in vector): 
            return [0.1] * 1024 
        return vector
    except Exception as e:
        logger.error(f"Embedding API Error: {e}")
        return [0.1] * 1024

# 3. CHUNKING LOGIC (To handle Pinecone Metadata limits)
def split_text_for_storage(text, max_len=800):
    return [text[i:i+max_len] for i in range(0, len(text), max_len)]

# 4. CORE FUNCTIONS
def save_chat_message(session_id, role, content, title="New Audit", symbol=""):
    """Saves message with strict validation and chunking."""
    chunks = split_text_for_storage(content)
    for i, chunk in enumerate(chunks):
        vector = get_nvidia_embedding(chunk)
        
        # Validation: Ensure vector is never None
        if vector is None or not isinstance(vector, list):
            vector = [0.1] * 1024
            
        msg_id = str(uuid.uuid4())
        metadata = {
            "session_id": session_id,
            "role": role,
            "title": title,
            "content": chunk,
            "symbol": symbol if i == 0 else "", # Symbol only on first chunk for recovery
            "time": str(uuid.uuid1()),
            "chunk_idx": i
        }
        
        try:
            index.upsert(vectors=[(msg_id, vector, metadata)])
        except Exception as e:
            logger.error(f"Pinecone Upsert Failed: {e}")

def get_sessions_with_titles():
    """Sidebar titles fetch logic with proper metadata sorting."""
    try:
        # Querying with a non-zero vector to pull metadata entries
        results = index.query(vector=[0.1] * 1024, top_k=100, include_metadata=True)
        session_map = {}
        matches = results.get('matches', [])
        
        # Sort by time metadata to show newest chats first
        sorted_matches = sorted(matches, key=lambda x: x['metadata'].get('time', ''), reverse=True)
        
        for match in sorted_matches:
            m = match['metadata']
            s_id = m.get('session_id')
            if s_id and s_id not in session_map:
                session_map[s_id] = m.get('title', 'Untitled Audit')
        return session_map
    except Exception as e:
        logger.error(f"Sidebar history load fail: {e}")
        return {}

def get_chat_history(session_id):
    """Loads and reconstructs history using strict metadata filters."""
    try:
        # We use a dummy vector but strict metadata filter for 100% accuracy
        results = index.query(
            vector=[0.1] * 1024,
            filter={"session_id": {"$eq": session_id}},
            top_k=100,
            include_metadata=True
        )
        
        raw_h = []
        for m in results.get('matches', []):
            meta = m['metadata']
            raw_h.append({
                "role": meta['role'], 
                "content": meta['content'], 
                "symbol": meta.get("symbol", ""), 
                "time": meta.get("time", "")
            })
        
        # Chronological sort using UUID1 time component
        raw_h.sort(key=lambda x: x['time'])
        
        # RECONSTRUCTION: Merge chunks back into single bubbles
        merged = []
        if raw_h:
            curr = raw_h[0]
            for nxt in raw_h[1:]:
                # If same role and no new symbol, it's a chunk of the same message
                if nxt['role'] == curr['role'] and not nxt['symbol']:
                    curr['content'] += nxt['content']
                else:
                    merged.append(curr)
                    curr = nxt
            merged.append(curr)
        return merged
    except Exception as e:
        logger.error(f"Chat history reconstruction fail: {e}")
        return []

def delete_session(session_id):
    """Permanent delete from Pinecone cloud."""
    try:
        index.delete(filter={"session_id": {"$eq": session_id}})
        return True
    except Exception as e:
        logger.error(f"Delete session failed: {e}")
        return False

def search_memory(query):
    """Deep semantic reasoning search."""
    try:
        vec = get_nvidia_embedding(query)
        if vec:
            results = index.query(vector=vec, top_k=3, include_metadata=True)
            return "\n".join([m['metadata']['content'] for m in results['matches']])
    except Exception as e:
        logger.warning(f"Memory search error: {e}")
    return ""
