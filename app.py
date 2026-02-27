import streamlit as st
import pandas as pd
from pandas_datareader import data as pdr
from supabase import create_client
from datetime import datetime, timezone
import datetime as dt

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
            end = dt.date.today()
start = end - dt.timedelta(weeks=260)
raw = {}
for sym in stale:
    try:
        df = pdr.DataReader(f"{sym}.US", "stooq", start, end)
        df = df.sort_index()
        df = df.resample("W").last()
        raw[sym] = df
    except:
        raw[sym] = pd.DataFrame()
            
            new_rows = []
            for i, sym in enumerate(stale):
                progress.progress((i + 1) / len(stale), text=f"Processing {sym}...")
                try:
                    data = raw.get(sym, pd.DataFrame())
                    
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
                    
                        market_cap = None
                    
                    new_rows.append({
                        "symbol": sym,
                        "current_price": current_price,
                        "sma_200w": sma_200w,
                        "distance": distance,
                        "market_cap": market_cap,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })
                except Exception:
                    continue
            
            if new_rows:
                save_cache(new_rows)
                for row in new_rows:
                    cache[row["symbol"]] = row
        
        except Exception as e:
            st.warning(f"Could not fetch fresh data: {e}. Showing cached data if available.")
        
        progress.empty()
    
    # Build final results from cache
    results = []
    for sym in symbols:
        c = cache.get(sym)
        if c:
            results.append({
                "symbol": sym,
                "current_price": c.get("current_price"),
                "sma_200w": c.get("sma_200w"),
                "distance": c.get("distance"),
                "market_cap": c.get("market_cap"),
            })
        else:
            results.append({"symbol": sym, "current_price": None, "sma_200w": None, "distance": None, "market_cap": None})
    
    return results

# ── Session state ─────────────────────────────────────────────────────────────
if "selected_watchlist_id" not in st.session_state:
    st.session_state.selected_watchlist_id = None
if "show_rename" not in st.session_state:
    st.session_state.show_rename = False
if "show_add_watchlist" not in st.session_state:
    st.session_state.show_add_watchlist = False

# ── Main UI ───────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">📈 200W SMA Tracker</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Track how far your stocks are from their 200-Week Simple Moving Average</div>', unsafe_allow_html=True)

watchlists = get_watchlists()
watchlist_names = [w["name"] for w in watchlists] if watchlists else []

col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

with col1:
    if watchlist_names:
        if st.session_state.selected_watchlist_id:
            ids = [w["id"] for w in watchlists]
            default_idx = ids.index(st.session_state.selected_watchlist_id) if st.session_state.selected_watchlist_id in ids else 0
        else:
            default_idx = 0
        selected_name = st.selectbox("Watchlist", watchlist_names, index=default_idx, label_visibility="collapsed")
        selected_wl = next(w for w in watchlists if w["name"] == selected_name)
        st.session_state.selected_watchlist_id = selected_wl["id"]
    else:
        selected_wl = None
        st.info("Create a watchlist to get started.")

with col2:
    if st.button("➕ New Watchlist", use_container_width=True):
        st.session_state.show_add_watchlist = not st.session_state.show_add_watchlist

with col3:
    if selected_wl and st.button("✏️ Rename", use_container_width=True):
        st.session_state.show_rename = not st.session_state.show_rename

with col4:
    if selected_wl and st.button("🗑️ Delete Watchlist", use_container_width=True):
        delete_watchlist(selected_wl["id"])
        st.session_state.selected_watchlist_id = None
        st.rerun()

if st.session_state.show_add_watchlist:
    with st.container(border=True):
        new_name = st.text_input("New watchlist name", placeholder="e.g. Nuclear Stocks")
        if st.button("Create", key="create_wl"):
            if new_name.strip():
                add_watchlist(new_name.strip())
                st.session_state.show_add_watchlist = False
                st.rerun()

if st.session_state.show_rename and selected_wl:
    with st.container(border=True):
        new_name = st.text_input("New name", value=selected_wl["name"])
        if st.button("Save name", key="save_rename"):
            if new_name.strip():
                rename_watchlist(selected_wl["id"], new_name.strip())
                st.session_state.show_rename = False
                st.rerun()

st.divider()

if selected_wl:
    symbols = get_tickers(selected_wl["id"])

    add_col, sort_col, refresh_col = st.columns([3, 2, 1])

    with add_col:
        new_ticker = st.text_input("Add ticker", placeholder="e.g. AAPL", label_visibility="collapsed")
        if st.button("Add Stock"):
            if new_ticker.strip():
                added = add_ticker(selected_wl["id"], new_ticker.strip().upper())
                if added:
                    st.rerun()
                else:
                    st.warning(f"{new_ticker.upper()} is already in this watchlist.")

    with sort_col:
        sort_by = st.selectbox("Sort by", ["Distance from 200W SMA", "Current Price", "Market Cap"], label_visibility="collapsed")

    with refresh_col:
        if st.button("🔄 Refresh", use_container_width=True):
            # Clear cache for this watchlist's symbols so fresh data is fetched
            for sym in symbols:
                supabase.table("stock_cache").delete().eq("symbol", sym).execute()
            st.rerun()

    if not symbols:
        st.info("No stocks in this watchlist yet. Add some tickers above!")
    else:
        rows = fetch_and_cache(symbols)
        df = pd.DataFrame(rows)

        sort_map = {"Distance from 200W SMA": "distance", "Current Price": "current_price", "Market Cap": "market_cap"}
        df = df.sort_values(by=sort_map[sort_by], ascending=True, na_position="last")

        st.markdown("### Holdings")
        header_cols = st.columns([1, 1.5, 1.5, 1.5, 1.5, 0.8])
        for col, label in zip(header_cols, ["Ticker", "Price", "200W SMA", "Distance", "Market Cap", "Remove"]):
            col.markdown(f"**{label}**")
        st.divider()

        for _, row in df.iterrows():
            r = st.columns([1, 1.5, 1.5, 1.5, 1.5, 0.8])
            r[0].markdown(f"**{row['symbol']}**")
            r[1].write(f"${row['current_price']:,.2f}" if row["current_price"] else "N/A")
            r[2].write(f"${row['sma_200w']:,.2f}" if row["sma_200w"] else "N/A")
            if row["distance"] is not None:
                color = "metric-above" if row["distance"] >= 0 else "metric-below"
                icon = "🟢" if row["distance"] >= 0 else "🔴"
                r[3].markdown(f'<span class="{color}">{icon} {row["distance"]:+.2f}%</span>', unsafe_allow_html=True)
            else:
                r[3].write("N/A")
            r[4].write(format_market_cap(row["market_cap"]))
            if r[5].button("✕", key=f"del_{row['symbol']}"):
                remove_ticker(selected_wl["id"], row["symbol"])
                st.rerun()

        st.divider()
        valid = df.dropna(subset=["distance"])
        if not valid.empty:
            s1, s2, s3 = st.columns(3)
            s1.metric("Stocks Above 200W SMA", f"{(valid['distance'] >= 0).sum()} / {len(valid)}")
            s2.metric("Most Stretched Above", f"{valid['distance'].max():+.1f}%", valid.loc[valid['distance'].idxmax(), 'symbol'])
            s3.metric("Best Value (Most Below)", f"{valid['distance'].min():+.1f}%", valid.loc[valid['distance'].idxmin(), 'symbol'])

st.markdown("---")
st.markdown('<div style="color:#555; font-size:0.8rem; text-align:center;">Data via Yahoo Finance · Cached hourly in Supabase · Built with Streamlit</div>', unsafe_allow_html=True)
