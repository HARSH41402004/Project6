# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils import (
    fetch_newsapi_articles,
    fetch_google_news_rss,
    dedupe_articles,
    detect_mutual_fund_mentions,
    normalize_article,
)
import os

st.set_page_config(page_title="F&O News & Mutual Fund Source Tracker", layout="wide")

st.title("F&O News & Mutual Fund Source Tracker")
st.markdown(
    """
Collects Futures & Options (F&O) news, aggregates from multiple sources (NewsAPI + Google News RSS),
and attempts to identify which Mutual Fund firm authored or is mentioned as the source of the update.
"""
)

# --- Sidebar: user inputs ---
st.sidebar.header("Search & Settings")

market = st.sidebar.selectbox("Market / Region (affects Google News query)", ["India (NSE)", "US (NYSE/NASDAQ)", "Global"])
default_query = {
    "India (NSE)": "NSE F&O OR futures options OR F&O stocks OR \"F&O\" OR \"futures & options\"",
    "US (NYSE/NASDAQ)": "options OR futures OR \"options market\" OR \"futures\"",
    "Global": "futures options OR derivatives OR options market",
}[market]

query = st.sidebar.text_input("Search query (Google News / NewsAPI)", value=default_query, help="Keywords used to query news. Tweak as needed.")
from_days = st.sidebar.number_input("Lookback (days)", min_value=1, max_value=30, value=7, step=1)
limit = st.sidebar.number_input("Max articles to fetch (per source)", min_value=10, max_value=500, value=150, step=10)

st.sidebar.markdown("### NewsAPI (optional)")
newsapi_key = st.sidebar.text_input("NewsAPI.org API key", value=os.getenv("NEWSAPI_KEY", ""), help="If you provide this, NewsAPI will be used (faster, richer). Get a key at https://newsapi.org")

st.sidebar.markdown("### Mutual Fund firms to detect")
mf_list_input = st.sidebar.text_area("Comma-separated list", value="SBI Mutual Fund,HDFC AMC,ICICI Prudential Mutual Fund,Axis Mutual Fund,Nippon India Mutual Fund,UTI Mutual Fund,Aditya Birla Sun Life Mutual Fund", height=120)
mf_list = [m.strip() for m in mf_list_input.split(",") if m.strip()]

if st.sidebar.button("Fetch latest F&O news now"):
    st.session_state.fetch = True

if "fetch" not in st.session_state:
    st.session_state.fetch = False

# Manual trigger
if st.session_state.fetch:
    with st.spinner("Fetching articles..."):
        from_date = (datetime.utcnow() - timedelta(days=int(from_days))).isoformat()
        all_articles = []

        # 1) NewsAPI (if key provided)
        if newsapi_key:
            try:
                n_articles = fetch_newsapi_articles(query=query, from_iso=from_date, api_key=newsapi_key, page_size=min(limit,100))
                for a in n_articles:
                    a_norm = normalize_article(a, source="NewsAPI")
                    a_norm["source_detected_mf"] = detect_mutual_fund_mentions(a_norm, mf_list)
                    all_articles.append(a_norm)
                st.success(f"Fetched {len(n_articles)} articles from NewsAPI.")
            except Exception as e:
                st.error(f"NewsAPI error: {e}")

        # 2) Google News RSS
        try:
            g_articles = fetch_google_news_rss(query=query, limit=limit)
            for a in g_articles:
                a_norm = normalize_article(a, source="GoogleNewsRSS")
                a_norm["source_detected_mf"] = detect_mutual_fund_mentions(a_norm, mf_list)
                all_articles.append(a_norm)
            st.success(f"Fetched {len(g_articles)} items from Google News RSS.")
        except Exception as e:
            st.error(f"Google News RSS error: {e}")

        # dedupe + sort
        combined = dedupe_articles(all_articles)
        df = pd.DataFrame(combined)
        if df.empty:
            st.warning("No articles found for that query/time window.")
        else:
            df["published"] = pd.to_datetime(df["published"], errors="coerce")
            df = df.sort_values("published", ascending=False)
            st.session_state.df = df
            st.success(f"Aggregated {len(df)} unique articles.")

# Display results if present
if "df" in st.session_state and not st.session_state.df.empty:
    df = st.session_state.df.copy()

    # Filters
    st.subheader("Results")
    cols = st.columns([3, 1, 1, 2, 1])
    with cols[0]:
        txt_filter = st.text_input("Filter by keyword (title/description/content)", value="")
    with cols[1]:
        mf_filter = st.selectbox("Filter by detected MF firm", options=["(any)"] + sorted(list({mf for mfs in df["source_detected_mf"].tolist() for mf in mfs if mfs})))
    with cols[2]:
        show_only_with_mf = st.checkbox("Show only items mentioning mutual fund firm", value=False)
    with cols[3]:
        max_rows = st.number_input("Show rows", value=50, min_value=5, max_value=1000, step=5)
    with cols[4]:
        download_btn = st.button("Download CSV")

    filtered = df
    if txt_filter:
        mask = filtered[["title", "description", "content"]].fillna("").apply(lambda col: col.str.contains(txt_filter, case=False, na=False))
        keep = mask.any(axis=1)
        filtered = filtered[keep]
    if mf_filter and mf_filter != "(any)":
        filtered = filtered[filtered["source_detected_mf"].apply(lambda arr: mf_filter in arr)]
    if show_only_with_mf:
        filtered = filtered[filtered["source_detected_mf"].apply(lambda arr: len(arr) > 0)]

    st.write(f"Showing {len(filtered)} articles (of {len(df)} total).")
    display_cols = ["published", "title", "source", "source_url", "source_detected_mf", "summary"]
    display_df = filtered[display_cols].head(int(max_rows)).copy()
    display_df = display_df.rename(columns={
        "published": "Published",
        "title": "Title",
        "source": "Source (site)",
        "source_url": "Link",
        "source_detected_mf": "Detected MF Firms (from text)",
        "summary": "Snippet"
    })
    st.dataframe(display_df, use_container_width=True)

    # Expand row view
    st.markdown("### Article details")
    for idx, row in filtered.head(int(max_rows)).iterrows():
        with st.expander(f"{row['published'].strftime('%Y-%m-%d %H:%M') if row['published'] is not pd.NaT else 'Unknown'} — {row['title']}"):
            st.write(f"**Source:** {row.get('source','')}")
            st.write(f"**URL:** {row.get('source_url','')}")
            st.write(f"**Detected MF firms:** {row.get('source_detected_mf', [])}")
            st.write(row.get("content") or row.get("description") or "")
            st.write("---")

    # Download CSV
    if download_btn:
        csv = filtered.to_csv(index=False)
        st.download_button("Download CSV", data=csv, file_name=f"fno_news_{datetime.utcnow().date()}.csv", mime="text/csv")

else:
    st.info("Click 'Fetch latest F&O news now' in the sidebar to collect articles.")

st.markdown("---")
st.markdown("**Notes:**\n- The app *attempts* to detect mutual fund firms by name inside articles. It doesn't guarantee the MF firm is the author — it could be mentioned inside the article. You can customize the MF firm list in the sidebar.\n- For production: add a NewsAPI key or other paid data sources for higher coverage and reliability.")
