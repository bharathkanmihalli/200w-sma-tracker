import streamlit as st
import yfinance as yf
import pandas as pd
from supabase import create_client
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
SUPABASE_URL = "https://bvlqbfdiqyptlhxiwksr.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2bHFiZmRpcXlwdGxoeGl3a3NyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIxNzI0MjgsImV4cCI6MjA4Nzc0ODQyOH0.R35Y7GtvqtarxqK9O-Um9c3z4_J6mu8sRR--5cdiJfo"
CACHE_HOURS = 1

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="200W SMA Tracker", page_icon="📈", layout="wide")

st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; margin-bottom: 0; }
    .subtitle { color: #888; margin-bottom: 1.5rem; font-size: 0.9rem; }
    .metric-above { color: #00c853; font-weight: 600; }
    .metric-below { color: #ff1744; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Database helpers ─────────────────────────────────────────────────────────
def get_watchlists():
    return supabase.table("watchlists").select("*").order("created_at").execute().data

def get_tickers(watchlist_id):
    rows = supabase.table("tickers").select("*").eq("watchlist_id", watchlist_id).order("symbol").execute().data
    return [r["symbol"] for r in rows]

def add_watchlist(name):
    supabase.table("watchlists").insert({"name": name}).execute()

def rename_watchlist(wid, name):
    supabase.table("watchlists").update({"name": name}).eq("id", wid).execute()

def delete_watchlist(wid):
    supabase.table("watchlists").delete().eq("id", wid).execute()

def add_ticker(watchlist_id, symbol):
    existing = supabase.table("tickers").select("id").eq("watchlist_id", watchlist_id).eq("symbol", symbol.upper()).execute()
    if not existing.data:
        supabase.table("tickers").insert({"watchlist_id": watchlist_id, "symbol": symbol.upper()}).execute()
        return True
    return False

def remove_ticker(watchlist_id, symbol):
    supabase.table("tickers").delete().eq("watchlist_id", watchlist_id).eq("symbol", symbol).execute()

# ── Cache helpers ─────────────────────────────────────────────────────────────
def get_cached(symbols):
    res = supabase.table("stock_cache").select("*").in_("symbol", symbols).execute()
    return {r["symbol"]: r for r in res.data}

def save_cache(rows):
    for row in rows:
        supabase.table("stock_cache").upsert(row).execute()

def is_fresh(cached_row):
    if not cached_row:
        return False
    updated = datetime.fromisoformat(cached_row["updated_at"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
    return age_hours < CACHE_HOURS

# ── Stock data ────────────────────────────────────────────────────────────────
def format_market_cap(val):
    if val is None:
        return "N/A"
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.2f}B"
    if val >= 1e6:
        return f"${val/1e6:.2f}M"
    return f"${val:,.0f}"

def fetch_and_cache(symbols):
    cache = get_cached(symbols)
    stale = [s for s in symbols if not is_fresh(cache.get(s))]
    
    if stale:
        progress = st.progress(0, text="Fetching fresh data from Yahoo Finance...")
        try:
            # Batch download all stale tickers in one request
            raw = yf.download(stale, period="5y", interval="1wk", progress=False, auto_adjust=True, group_by="ticker")
            
            new_rows = []
            for i, sym in enumerate(stale):
                progress.progress((i + 1) / len(stale), text=f"Processing {sym}...")
                try:
                    if len(stale) == 1:
                        data = raw
                    else:
                        data = raw[sym]
                    
                    if data.empty or len(data) < 10:
                        continue
                    
                    current_price = round(float(data["Close"].iloc[-1]), 2)
                    
                    if len(data) >= 200:
                        sma_200w = round(float(data["Close"].rolling(window=200).mean().iloc[-1]), 2)
                        distance = round(((current_price - sma_200w) / sma_200w) * 100, 2)
                    else:
                        sma_200w = None
                        distance = None
                    
                    # Get market cap
                    try:
                        info = yf.Ticker(sym).fast_info
                        market_cap = getattr(info, "market_cap", None)
                    except:
                        market_cap = None
                    
                    new_rows.append({
                        "symbol": sym,
                        "current_price": current_price,
                        "sma_200w": sma_200w,
                        "distance":
