import os
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands
import memory 
from dotenv import load_dotenv
from openai import OpenAI
import datetime

load_dotenv()
today = datetime.date.today().strftime("%Y-%m-%d")
_stream_cancel = False

def cancel_streaming():
    global _stream_cancel
    _stream_cancel = True

def is_stream_cancelled():
    global _stream_cancel
    return _stream_cancel

def get_engine_client():
    return OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=os.getenv("NVIDIA_API_KEY"))

def smart_processor(user_input):
    client = get_engine_client()
    
    system_prompt = """
    You are a Financial Intent Classifier.
    - If the user mentions a stock or crypto (e.g., Bitcoin, Reliance, Tesla), you MUST return ONLY the ticker in this format: TICKER: <symbol>
    - Rules for Tickers: 
        1. Bitcoin -> BTC-USD, Ethereum -> ETH-USD
        2. Indian Stocks -> Add .NS (e.g., RELIANCE.NS)
        3. US Stocks -> Just symbol (e.g., TSLA, AAPL)
    - If the user is just saying Hi/Hello or general talk, return: CHAT: <friendly response>
    
    Example: "Bitcoin dikha" -> TICKER: BTC-USD
    Example: "Reliance ka audit" -> TICKER: RELIANCE.NS
    """
    
    res = client.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    )
    
    return res.choices[0].message.content.strip()

def fetch_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        df = stock.history(period="1y") 
        if df.empty: raise ValueError("No data found")
        
        # Technical Calculations
        df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
        macd = MACD(close=df['Close'])
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['EMA_50'] = EMAIndicator(close=df['Close'], window=50).ema_indicator()
        df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()
        bb = BollingerBands(close=df['Close'])
        df['BB_Upper'] = bb.bollinger_hband()
        df['BB_Lower'] = bb.bollinger_lband()
        
        return df, df['Close'].iloc[-1]
    except Exception as e: raise ValueError(f"Ticker {symbol} issue: {e}")

def get_deep_analysis_stream(symbol, df, user_query):
    global _stream_cancel
    _stream_cancel = False
    client = get_engine_client()
    
    # Latest Values for AI
    latest = df.iloc[-1]
    indicators_data = f"""
    PRICE: {latest['Close']:.2f} | RSI: {latest['RSI']:.2f}
    MACD: {latest['MACD']:.4f} | SIGNAL: {latest['MACD_Signal']:.4f}
    EMA50: {latest['EMA_50']:.2f} | EMA200: {latest['EMA_200']:.2f}
    BB_UPPER: {latest['BB_Upper']:.2f} | BB_LOWER: {latest['BB_Lower']:.2f}
    """

    # 1. LOAD PROMPT FROM FILE
    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            base_instructions = f.read()
    except:
        base_instructions = "Analyze the stock data and provide a verdict."

    # 2. MERGE EVERYTHING
    final_prompt = f"""
    {base_instructions}

    --- REAL-TIME DATA ---
    SYMBOL: {symbol} | DATE: {today}
    {indicators_data}

    --- HISTORICAL DATA (5 DAYS) ---
    {df[['Close', 'Volume', 'RSI']].tail(5).to_string()}

    USER QUERY: {user_query}
    """
    
    return client.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=[{"role": "user", "content": final_prompt}],
        stream=True
    )