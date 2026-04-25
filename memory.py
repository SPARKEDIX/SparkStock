import os
import uuid
import streamlit as st
from pinecone import Pinecone
from openai import OpenAI
from dotenv import load_dotenv

# 1. ENVIRONMENT SETUP
load_dotenv()

PINECONE_KEY = os.getenv("PINECONE_API_KEY")
NVIDIA_KEY = os.getenv("NVIDIA_API_KEY")

# 2. PINECONE CLIENT INITIALIZATION
pc = Pinecone(api_key=PINECONE_KEY)
# Index dashboard se match karna chahiye
INDEX_NAME = "sparkstock"
index = pc.Index(INDEX_NAME)

# 3. NVIDIA EMBEDDING (Fixed for Hindi/Devanagari Tokens)
def get_nvidia_embedding(text):
    if not NVIDIA_KEY: return [0.0] * 1024
    
    client_nv = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=NVIDIA_KEY
    )
    
    # HINDI TOKEN FIX: 
    # Hindi/Devanagari characters 2-3 tokens lete hain. 
    # Isliye 400 characters hi bhej rahe hain safe rehne ke liye.
    safe_text = text[:400] 
    
    try:
        response = client_nv.embeddings.create(
            input=[safe_text],
            model="nvidia/nv-embedqa-e5-v5",
            encoding_format="float",
            extra_body={"input_type": "query"}
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Embedding API Error: {e}")
        return [0.0] * 1024

# 4. CHUNKING LOGIC (Fixes Metadata Limit)
def split_text_for_storage(text, max_len=800):
    """Bade answers ko 800 characters ke tukdon mein todta hai"""
    return [text[i:i+max_len] for i in range(0, len(text), max_len)]

# 5. CORE FUNCTIONS
def save_chat_message(session_id, role, content, title="New Audit", symbol=""):
    """Saves message with chunking to avoid Pinecone 400 errors"""
    chunks = split_text_for_storage(content)
    
    for i, chunk in enumerate(chunks):
        vector = get_nvidia_embedding(chunk)
        msg_id = str(uuid.uuid4())
        
        metadata = {
            "session_id": session_id,
            "role": role,
            "title": title,
            "content": chunk,
            "symbol": symbol if i == 0 else "", # Sirf pehle chunk pe ticker lagao
            "time": str(uuid.uuid1()),
            "chunk_idx": i
        }
        
        index.upsert(vectors=[(msg_id, vector, metadata)])

def get_sessions_with_titles():
    """Fetches unique session titles for the sidebar"""
    try:
        # Dummy vector search to get latest 100 metadata records
        results = index.query(vector=[0.0] * 1024, top_k=100, include_metadata=True)
        
        session_map = {}
        # Sort by time latest first
        matches = sorted(results['matches'], key=lambda x: x['metadata'].get('time', ''), reverse=True)
        for match in matches:
            m = match['metadata']
            s_id = m['session_id']
            if s_id not in session_map:
                session_map[s_id] = m.get('title', 'Untitled Audit')
        return session_map
    except:
        return {}

def get_chat_history(session_id):
    """Loads and MERGES chunks back into single messages for the UI"""
    try:
        results = index.query(
            vector=[0.0] * 1024,
            filter={"session_id": {"$eq": session_id}},
            top_k=100,
            include_metadata=True
        )
        
        raw_history = []
        for match in results['matches']:
            m = match['metadata']
            raw_history.append({
                "role": m['role'], 
                "content": m['content'], 
                "symbol": m.get("symbol", ""), 
                "time": m.get("time", "")
            })
        
        # Chronological sort
        raw_history.sort(key=lambda x: x['time'])
        
        # MERGE LOGIC: Same role + No symbol = Next part of previous message
        merged_history = []
        if raw_history:
            current = raw_history[0]
            for next_msg in raw_history[1:]:
                if next_msg['role'] == current['role'] and not next_msg['symbol']:
                    current['content'] += next_msg['content']
                else:
                    merged_history.append(current)
                    current = next_msg
            merged_history.append(current)
            
        return merged_history
    except:
        return []
def delete_session(session_id):
    """Specific session ko database se permanent delete karna"""
    try:
        index.delete(filter={"session_id": {"$eq": session_id}})
        return True
    except Exception as e:
        print(f"Delete Error: {e}")
        return False        

def search_memory(query):
    """Semantic search for AI context window"""
    try:
        query_vector = get_nvidia_embedding(query)
        results = index.query(vector=query_vector, top_k=3, include_metadata=True)
        return "\n".join([match['metadata']['content'] for match in results['matches']])
    except:
        return ""