import os
import requests
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
import memory 
from dotenv import load_dotenv
from openai import OpenAI
import datetime
import logging
import time
import sys
import datetime
today = datetime.date.today().strftime("%Y-%m-%d")
# 1. LOGGING SETUP (Google Standard)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SparkStock-Core")

load_dotenv()
_stream_cancel = False
today = datetime.date.today().strftime("%Y-%m-%d")

# --- ROTATOR CONFIGS ---
NVIDIA_KEYS = [k for k in [os.getenv("NVIDIA_API_KEY_1"), os.getenv("NVIDIA_API_KEY_2")] if k]
current_llm_idx = 0

DATA_SOURCES = ["YAHOO", "FINNHUB", "ALPHA"]
current_source_idx = 0
_stock_cache = {}

# --- CORE UTILITIES ---
def get_engine_client():
    global current_llm_idx
    selected_key = NVIDIA_KEYS[current_llm_idx]
    current_llm_idx = (current_llm_idx + 1) % len(NVIDIA_KEYS)
    logger.info(f"LLM Rotation: Slot {current_llm_idx + 1}")
    return OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=selected_key)

def cancel_streaming():
    global _stream_cancel
    _stream_cancel = True
    logger.warning("!!! USER INTERRUPT: CANCELING STREAM !!!")

def is_stream_cancelled():
    return _stream_cancel

# --- DATA SOURCE LOGIC ---
def fetch_latest_news(symbol):
    try:
        api_key = os.getenv("NEWS_API_KEY")
        query = symbol.split('.')[0]
        url = f"https://newsapi.org/v2/everything?q={query}&apiKey={api_key}&pageSize=3&sortBy=publishedAt"
        res = requests.get(url).json()
        headlines = [art['title'] for art in res.get('articles', [])]
        return headlines if headlines else ["No recent news."]
    except:
        return ["News service busy."]

def fetch_from_finnhub(symbol):
    try:
        api_key = os.getenv("FINNHUB_API_KEY")
        clean_symbol = symbol.split('.')[0].upper()
        url = f"https://finnhub.io/api/v1/quote?symbol={clean_symbol}&token={api_key}"
        res = requests.get(url).json()
        if 'c' in res and res['c'] != 0: return res['c']
        return None
    except: return None

def fetch_stock_data(symbol):
    global _stock_cache, current_source_idx
    now = time.time()
    
    # 1. Micro-Cache (60s)
    if symbol in _stock_cache:
        timestamp, cached_df, cached_price = _stock_cache[symbol]
        if now - timestamp < 60:
            logger.info(f"Micro-Cache HIT: {symbol}")
            return cached_df, cached_price

    # 2. Source Rotation
    source = DATA_SOURCES[current_source_idx]
    current_source_idx = (current_source_idx + 1) % len(DATA_SOURCES)
    logger.info(f"Fetching {symbol} via {source}")

    try:
        if source == "YAHOO" or source == "ALPHA": # Alpha logic merged with Yahoo for stability
            stock = yf.Ticker(symbol)
            df = stock.history(period="1y")
            if df.empty: raise ValueError("Yahoo/Alpha returned empty")
            
            # Indicators
            df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
            macd = MACD(close=df['Close'])
            df['MACD'] = macd.macd()
            df['MACD_Signal'] = macd.macd_signal()
            df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()
            
            price = df['Close'].iloc[-1]
            _stock_cache[symbol] = (now, df, price)
            return df, price
        
        else: # FINNHUB
            price = fetch_from_finnhub(symbol)
            if not price: raise ValueError("Finnhub Fail")
            # Reuse historical data for indicators if available
            if symbol in _stock_cache:
                return _stock_cache[symbol][1], price
            else:
                # Fallback to Yahoo for history
                stock = yf.Ticker(symbol)
                df = stock.history(period="1y")
                df['RSI'] = RSIIndicator(close=df['Close']).rsi()
                return df, price
    except Exception as e:
        logger.error(f"Source {source} failed: {e}. Emergency fallback to Yahoo.")
        stock = yf.Ticker(symbol)
        df = stock.history(period="1mo", interval="1h")
        df['RSI'] = RSIIndicator(close=df['Close']).rsi()
        return df, df['Close'].iloc[-1]

# --- AI LOGIC ---
def smart_processor(user_input, session_id):
    """
    Advanced Intent Processor:
    1. Context Check: 'Iska chart dikha' -> Samjhega pichla stock kya tha.
    2. Accurate Search: 'Reliance' -> Filter karega .NS (NSE) ko priority dene ke liye.
    3. Error Resilience: Garbage tickers (GDR/RIGD) ko skip karega.
    """
    client = get_engine_client()
    
    # 1. Memory Retrieval for Pronoun Resolution (Context)
    try:
        past_messages = memory.get_chat_history(session_id)
        # Context summary for LLM reasoning
        context_summary = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in past_messages[-4:]])
    except:
        context_summary = "Fresh session, no context."

    # 2. Dynamic Instructions from prompt.txt
    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            base_instructions = f.read()
    except:
        base_instructions = "Identify stock/crypto name."

    # 3. AI Intent Decision
    system_msg = f"""
    {base_instructions}
    
    Today's Date: {today}
    ---
    CHAT HISTORY:
    {context_summary}
    ---
    STRICT RULES:
    - If user uses 'it', 'this', 'ye', 'isko', identify the LAST stock mentioned.
    - If user asks for an audit of that stock, return ONLY: TICKER: <SYMBOL>
    - If new entity, return ONLY the company name (e.g., 'Tesla Inc').
    - If it's a greeting, return ONLY: CHAT: <your response>
    """
    
    try:
        res = client.chat.completions.create(
            model="meta/llama-3.3-70b-instruct",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_input}
            ]
        )
        decision = res.choices[0].message.content.strip()

        # Handle Direct AI Decision (Contextual Ticker or Chat)
        if decision.upper().startswith("TICKER:"): return decision
        if decision.upper().startswith("CHAT:"): return decision

        # 4. ROBUST SEARCH LOGIC (Filtering Garbage)
        logger.info(f"Entity identified: {decision}. Searching for best ticker...")
        search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={decision}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        search_res = requests.get(search_url, headers=headers).json()
        
        quotes = search_res.get('quotes', [])
        
        # Filtering for tradeable assets (EQUITY/CRYPTO)
        # We prioritize .NS for India and direct Alphas for US
        best_match = None
        for q in quotes:
            symbol = q.get('symbol', '').upper()
            q_type = q.get('quoteType')
            
            if q_type in ['EQUITY', 'CRYPTOCURRENCY']:
                # Priority 1: Indian Stock (NSE)
                if ".NS" in symbol:
                    return f"TICKER: {symbol}"
                # Priority 2: Standard US Ticker (e.g., TSLA, AAPL)
                if symbol.isalpha() and q_type == 'EQUITY' and not best_match:
                    best_match = symbol
                # Priority 3: Crypto
                if "-USD" in symbol or "-INR" in symbol:
                    return f"TICKER: {symbol}"

        if best_match:
            return f"TICKER: {best_match}"
        
        # Fallback to first available if no ideal match found
        if quotes:
            return f"TICKER: {quotes[0].get('symbol')}"
            
        return f"CHAT: I found '{decision}' but couldn't find a tradeable ticker."

    except Exception as e:
        logger.error(f"Intent Error: {e}")
        return "CHAT: Engine is recalibrating. Can you name the stock again?"
def get_deep_analysis_stream(symbol, df, user_query):
    global _stream_cancel
    _stream_cancel = False
    client = get_engine_client()
    
    latest = df.iloc[-1]
    news = fetch_latest_news(symbol)
    past_ctx = memory.search_memory(user_query)

    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            base_prompt = f.read()
    except:
        base_prompt = "Perform a deep financial audit."

    final_prompt = f"""
    {base_prompt}
    ---
    MARKET CONTEXT:
    DATE: {today} | SYMBOL: {symbol}
    PRICE: {latest['Close']:.2f} | RSI: {latest['RSI']:.2f}
    EMA200: {latest.get('EMA_200', 0):.2f}
    NEWS: {news}
    ---
    PAST MEMORY: {past_ctx}
    USER QUERY: {user_query}
    """
    
    return client.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=[{"role": "user", "content": final_prompt}],
        stream=True
    )