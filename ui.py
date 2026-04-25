import streamlit as st
import engine
import memory
import plotly.graph_objects as go
import uuid, os

def launch_ui():
    st.set_page_config(page_title="SparkStock AI Agent", layout="wide", page_icon="icon.jpg")

    # --- 1. INITIALIZE SESSION STATE (SABSE PEHLE YAHI HOGA) ---
    if "current_session" not in st.session_state: 
        st.session_state.current_session = str(uuid.uuid4())
    
    if "messages" not in st.session_state:
        st.session_state.messages = memory.get_chat_history(st.session_state.current_session)
        
    if "chat_title" not in st.session_state: 
        st.session_state.chat_title = "New Audit"
        
    if "is_generating" not in st.session_state: 
        st.session_state.is_generating = False

    # --- 2. CSS: PREMIUM DESIGN & BUTTON MORPHING ---
    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
        * {{ font-family: 'Outfit', sans-serif; }}
        .stApp {{ background: #0B0E14; }}
        [data-testid="stSidebar"] {{ background: #11141C !important; border-right: 1px solid rgba(255,255,255,0.05); }}
        .stChatInputContainer {{ background-color: #11141C !important; border-top: 1px solid rgba(255,255,255,0.1); }}

        div[data-testid="stChatMessageUser"] {{ flex-direction: row-reverse !important; background: rgba(0, 242, 254, 0.1) !important; border-radius: 18px !important; margin-bottom: 15px !important; }}
        div[data-testid="stChatMessageAssistant"] {{ background: rgba(255, 255, 255, 0.05) !important; border-radius: 18px !important; margin-bottom: 15px !important; }}

        /* BUTTON MORPHING */
        { "button[data-testid='stChatInputSubmit'] svg { display: none !important; }" if st.session_state.get('is_generating') else "" }
        { "button[data-testid='stChatInputSubmit']::after { content: '■'; color: white; font-size: 18px; font-weight: bold; }" if st.session_state.get('is_generating') else "" }
        { "button[data-testid='stChatInputSubmit'] { background: #FF4B4B !important; border-radius: 50% !important; border: none !important; }" if st.session_state.get('is_generating') else "" }
        </style>
    """, unsafe_allow_html=True)

    # --- 3. SIDEBAR (History) ---
    with st.sidebar:
        st.markdown("<h1 style='color:#00F2FE; font-size: 2rem;'>⚡ SparkStock</h1>", unsafe_allow_html=True)
        if st.button("➕ New Chat", use_container_width=True):
            st.session_state.current_session = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.chat_title = "New Audit"
            st.session_state.is_generating = False
            st.rerun()
        
        st.divider()
        st.caption("RECENT INVESTIGATIONS")
        
        sessions = memory.get_sessions_with_titles()
        sorted_sessions = sorted(sessions.items(), key=lambda x: x[0], reverse=True)
        
        for s_id, title in sorted_sessions:
            c1, c2 = st.columns([0.82, 0.18])
            with c1:
                if st.button(f"📄 {title[:16]}", key=f"btn_{s_id}", use_container_width=True):
                    st.session_state.current_session = s_id
                    st.session_state.messages = memory.get_chat_history(s_id)
                    st.session_state.chat_title = title
                    st.rerun()
            with c2:
                if st.button("🗑️", key=f"del_{s_id}"):
                    memory.delete_session(s_id)
                    if st.session_state.current_session == s_id:
                        st.session_state.current_session = str(uuid.uuid4())
                        st.session_state.messages = []
                    st.rerun()

    # --- 4. HEADER ---
    st.markdown(f"## {st.session_state.chat_title}")
    
    # --- 5. DISPLAY CHAT HISTORY ---
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
            current_symbol = msg.get("symbol")
            if msg.get("role") == "assistant" and current_symbol:
                try:
                    clean_sym = str(current_symbol).split()[0].strip().upper()
                    df, _ = engine.fetch_stock_data(clean_sym)
                    fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
                    fig.update_layout(template="plotly_dark", height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,b=0,t=0))
                    st.plotly_chart(fig, on_select="ignore")
                except: pass

    # --- 6. INPUT LOGIC & STOP ---
    if st.session_state.is_generating:
        if st.button("STOP", key="stop_engine_logic", help="Cancel Analysis"):
            engine.cancel_streaming()
            st.session_state.is_generating = False
            st.rerun()

    user_input = st.chat_input("Analyze any stock...", disabled=st.session_state.is_generating)

    if user_input:
        if st.session_state.is_generating:
            engine.cancel_streaming()
            st.session_state.is_generating = False
            st.rerun()
        else:
            if not st.session_state.messages:
                st.session_state.chat_title = user_input[:25].upper()

            st.session_state.messages.append({"role": "user", "content": user_input})
            memory.save_chat_message(st.session_state.current_session, "user", user_input, st.session_state.chat_title)
            st.session_state.is_generating = True
            st.rerun()

    # --- 7. AI EXECUTION ---
        # --- 7. AI EXECUTION (Triggers after rerun) ---
    if st.session_state.is_generating:
        # Get the last user query
        last_msg = st.session_state.messages[-1]["content"]
        
        with st.chat_message("assistant"):
            res_box = st.empty()
            # 1. Smart Intent Extraction (with Context)
            brain_res = engine.smart_processor(last_msg, st.session_state.current_session)
            
            if "TICKER:" in brain_res:
                # Robust extraction: 'TICKER: RELIANCE.NS' -> 'RELIANCE.NS'
                symbol = brain_res.split("TICKER:")[1].split()[0].strip().upper() 
                st.caption(f"🔍 Analyzing: **{symbol}**")
                
                try:
                    # 2. Fetch Market Data (Engine handles Cache & Fallback)
                    df, price = engine.fetch_stock_data(symbol)
                    
                    if df is not None:
                        # 3. Display Chart
                        fig = go.Figure(data=[go.Candlestick(
                            x=df.index, open=df['Open'], high=df['High'], 
                            low=df['Low'], close=df['Close']
                        )])
                        st.plotly_chart(fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0)))
                        
                        # 4. Deep Analysis Streaming
                        full_res = ""
                        stream = engine.get_deep_analysis_stream(symbol, df, last_msg)
                        for chunk in stream:
                            if engine.is_stream_cancelled(): 
                                full_res += "\n\n[🛑 Stopped by User]"
                                break
                            if chunk.choices[0].delta.content:
                                full_res += chunk.choices[0].delta.content
                                res_box.markdown(full_res + "▌")
                        
                        res_box.markdown(full_res)
                        
                        # 5. FINAL SAVE (Very Important)
                        memory.save_chat_message(st.session_state.current_session, "assistant", full_res, st.session_state.chat_title, symbol)
                        st.session_state.messages.append({"role": "assistant", "content": full_res, "symbol": symbol})
                    else:
                        st.error("Could not retrieve market data. Please check the symbol.")
                        st.session_state.messages.append({"role": "assistant", "content": "Sorry, I couldn't fetch the market data for this symbol."})

                except Exception as e:
                    st.error(f"Execution Error: {e}")
            
            else:
                # 6. Normal Chat Response (Streaming Effect)
                chat_msg = brain_res.replace("CHAT:", "").strip()
                displayed_msg = ""
                for char in chat_msg: # Fake stream for friendly chat
                    displayed_msg += char
                    res_box.markdown(displayed_msg + "▌")
                res_box.markdown(displayed_msg)
                
                # Save chat to memory
                memory.save_chat_message(st.session_state.current_session, "assistant", displayed_msg, st.session_state.chat_title)
                st.session_state.messages.append({"role": "assistant", "content": displayed_msg})

            # 7. LOCK RELEASE & FINAL REFRESH
            st.session_state.is_generating = False
            st.rerun()