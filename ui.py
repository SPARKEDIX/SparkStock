import streamlit as st
import engine
import memory
import plotly.graph_objects as go
import uuid, os

def launch_ui():
    st.set_page_config(page_title="SparkStock AI Agent", layout="wide", page_icon="icon.jpg")

    # --- 1. CSS: Button Morphing & Sidebar ---
    # Jab AI generate karega, hum Send button ko Red Square (Stop) mein badal denge
    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
        * {{ font-family: 'Outfit', sans-serif; }}
        .stApp {{ background: #0B0E14; }}
        
        /* Sidebar Styling */
        [data-testid="stSidebar"] {{ background: #11141C !important; }}
        
        /* Chat Input Button Morphing Logic */
        { "button[data-testid='stChatInputSubmit'] svg { display: none !important; }" if st.session_state.get('is_generating') else "" }
        { "button[data-testid='stChatInputSubmit']::after { content: '■'; color: white; font-size: 18px; font-weight: bold; }" if st.session_state.get('is_generating') else "" }
        { "button[data-testid='stChatInputSubmit'] { background: #FF4B4B !important; border-radius: 50% !important; border: none !important; width: 32px !important; height: 32px !important; }" if st.session_state.get('is_generating') else "" }

        /* Bubbles */
        div[data-testid="stChatMessageUser"] {{ flex-direction: row-reverse !important; background: rgba(0, 242, 254, 0.1) !important; border-radius: 15px !important; }}
        div[data-testid="stChatMessageAssistant"] {{ background: rgba(255, 255, 255, 0.05) !important; border-radius: 15px !important; }}
        </style>
    """, unsafe_allow_html=True)

    # --- 2. SESSION INITIALIZATION ---
    if "current_session" not in st.session_state: st.session_state.current_session = str(uuid.uuid4())
    if "messages" not in st.session_state: st.session_state.messages = memory.get_chat_history(st.session_state.current_session)
    if "chat_title" not in st.session_state: st.session_state.chat_title = "New Investigation"
    if "is_generating" not in st.session_state: st.session_state.is_generating = False

    # --- 3. SIDEBAR (History Sabse Upar) ---
    with st.sidebar:
        st.markdown("<h1 style='color:#00F2FE; font-size: 2rem;'>⚡ SparkStock</h1>", unsafe_allow_html=True)
        
        if st.button("➕ Start New Chat", use_container_width=True):
            st.session_state.current_session = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.chat_title = "New Investigation"
            st.session_state.is_generating = False
            st.rerun()
        
        st.divider()
        st.caption("RECENT INVESTIGATIONS")
        
        sessions = memory.get_sessions_with_titles()
        # Sort history: Newest First
        sorted_sessions = sorted(sessions.items(), key=lambda x: x[0], reverse=True)
        
        for s_id, title in sorted_sessions:
            cols = st.columns([0.85, 0.15])
            with cols[0]:
                if st.button(f"📄 {title[:18]}", key=f"btn_{s_id}", use_container_width=True):
                    st.session_state.current_session = s_id
                    st.session_state.messages = memory.get_chat_history(s_id)
                    st.session_state.chat_title = title
                    st.rerun()
            with cols[1]:
                if st.button("🗑️", key=f"del_{s_id}"):
                    memory.delete_session(s_id)
                    if st.session_state.current_session == s_id:
                        st.session_state.current_session = str(uuid.uuid4())
                        st.session_state.messages = []
                    st.rerun()

    # --- 4. MAIN CHAT AREA ---
    st.markdown(f"## {st.session_state.chat_title}")
    
    # Display History
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("role") == "assistant" and msg.get("symbol"):
                try:
                    df, _ = engine.fetch_stock_data(msg["symbol"])
                    fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
                    fig.update_layout(template="plotly_dark", height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,b=0,t=0))
                    st.plotly_chart(fig, on_select="ignore")
                except: pass

    # --- 5. CHAT INPUT & STOP LOGIC ---
    # Trigger AI stop if user clicks the morphed button
    if st.session_state.is_generating:
        # Hidden transparent button exactly where the chat input button is
        # Jab button dabaoge, engine cancel hoga aur rerun hoga
        if st.button("STOP", key="stop_engine_btn", help="Cancel Analysis", use_container_width=False):
            engine.cancel_streaming()
            st.session_state.is_generating = False
            st.rerun()

    # Input Box (Normal mode)
    user_input = st.chat_input("Analyze any stock (e.g. BTC-USD, Reliance)...")

    if user_input:
        # Agar already AI chal raha hai aur user enter marta hai, toh ye Stop ki tarah act karega
        if st.session_state.is_generating:
            engine.cancel_streaming()
            st.session_state.is_generating = False
            st.rerun()
        else:
            # First query set title
            if not st.session_state.messages:
                st.session_state.chat_title = user_input[:25].upper()

            # Save and Display User Msg
            st.session_state.messages.append({"role": "user", "content": user_input})
            memory.save_chat_message(st.session_state.current_session, "user", user_input, st.session_state.chat_title)
            with st.chat_message("user"):
                st.markdown(user_input)

            # AI Execution
            with st.chat_message("assistant"):
                res_box = st.empty()
                st.session_state.is_generating = True
                
                # Intent analysis
                brain_res = engine.smart_processor(user_input)
                
                if "TICKER:" in brain_res:
                    symbol = brain_res.split("TICKER:")[1].split()[0].strip().upper() 
                    try:
                        df, price = engine.fetch_stock_data(symbol)
                        # Instant Chart
                        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
                        st.plotly_chart(fig.update_layout(template="plotly_dark", height=400))
                        
                        # Streaming Audit
                        full_res = ""
                        stream = engine.get_deep_analysis_stream(symbol, df, user_input)
                        for chunk in stream:
                            if engine.is_stream_cancelled(): break
                            if chunk.choices[0].delta.content:
                                full_res += chunk.choices[0].delta.content
                                res_box.markdown(full_res + "▌")
                        
                        res_box.markdown(full_res)
                        memory.save_chat_message(st.session_state.current_session, "assistant", full_res, st.session_state.chat_title, symbol)
                        st.session_state.messages.append({"role": "assistant", "content": full_res, "symbol": symbol})
                    except Exception as e:
                        st.error(f"Broker Issue: {e}")
                else:
                    # General Chat
                    chat_msg = brain_res.replace("CHAT:", "").strip()
                    res_box.markdown(chat_msg)
                    memory.save_chat_message(st.session_state.current_session, "assistant", chat_msg, st.session_state.chat_title)
                    st.session_state.messages.append({"role": "assistant", "content": chat_msg})
                
                # AI Done
                st.session_state.is_generating = False
                st.rerun()

