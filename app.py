"""ExoRadar — NurExone Exosome Market & GTM Intelligence Dashboard."""
from __future__ import annotations

import io
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from data.pricing_tiers import get_pricing_basis
from utils.db import get_conn, init_db, log_change
from utils.scoring import (
    _READINESS_SCORE,
    _legislation_score,
    _scale_score,
    calculate_gtm_score,
    calculate_score,
)

st.set_page_config(
    page_title="ExoRadar — Exosome Market & GTM Intelligence",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# Auto-seed states: INSERT OR REPLACE so CSV edits propagate on every deploy
from pipeline.seed_states import seed_states
seed_states()

# Auto-seed entities: INSERT OR IGNORE — adds new entries, never overwrites existing/manual edits
from pipeline.seed_entities import seed_entities
seed_entities()

# ── helpers ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_states() -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM state_registry ORDER BY state_name", conn)


@st.cache_data(ttl=60)
def load_entities() -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM entity_registry ORDER BY priority_score DESC NULLS LAST", conn)


@st.cache_data(ttl=60)
def load_update_log() -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(
            """
            SELECT ul.id, ul.log_date,
                   COALESCE(ul.entity_name, er.name, '—') AS entity_name,
                   ul.change_type, ul.description, ul.source_url, ul.logged_by
            FROM update_log ul
            LEFT JOIN entity_registry er ON ul.entity_id = er.id
            ORDER BY ul.log_date DESC
            LIMIT 50
            """,
            conn,
        )


def invalidate_cache():
    load_states.clear()
    load_entities.clear()
    load_update_log.clear()


_RISK_COLORS = {"low": "#2ecc71", "medium": "#f39c12", "high": "#e74c3c", "unknown": "#95a5a6", "unclear": "#95a5a6"}
_RISK_LABELS = {"low": "Low — Permissive", "medium": "Medium — Ambiguous", "high": "High — Restrictive", "unknown": "Unknown"}

# ── SECTION A — Legislation map ───────────────────────────────────────────────

def _entity_hover_str(state_code: str, state_entities: dict) -> str:
    """Return an HTML snippet listing entities for a given state code."""
    ents = state_entities.get(state_code, [])
    if not ents:
        return "None tracked"
    shown = ents[:7]
    extra = len(ents) - 7
    lines = "<br>".join(
        f"&nbsp;• {name} <span style='color:#aaa'>({etype})</span>"
        for name, etype in shown
    )
    if extra > 0:
        lines += f"<br>&nbsp;&nbsp;<i>+{extra} more</i>"
    return f"<b>{len(ents)} tracked</b><br>{lines}"


def render_map(states_df: pd.DataFrame, entities_df: pd.DataFrame):
    st.subheader("Section A — US State Legislation Map")

    if states_df.empty:
        st.info("No state data loaded yet. Run `pipeline/seed_states.py` first.")
        return

    # Build state_code → [(name, entity_type)] sorted by score desc
    state_entities: dict[str, list] = {}
    for _, row in entities_df[entities_df["active"] == 1].iterrows():
        for sc in (row["states"] or "").split(","):
            sc = sc.strip()
            if sc and sc != "INTL":
                state_entities.setdefault(sc, []).append((row["name"], row["entity_type"]))

    df = states_df.copy()
    df["risk_display"] = df["risk_level"].fillna("unknown").str.lower()
    df["color_order"] = df["risk_display"].map({"low": 0, "medium": 1, "high": 2, "unknown": 3, "unclear": 3}).fillna(3)
    df["provisions_short"] = df["key_provisions"].fillna("").str[:140]
    df["entities_str"] = df["state_code"].apply(lambda sc: _entity_hover_str(sc, state_entities))

    color_discrete_map = {
        "low": _RISK_COLORS["low"],
        "medium": _RISK_COLORS["medium"],
        "high": _RISK_COLORS["high"],
        "unknown": _RISK_COLORS["unknown"],
        "unclear": _RISK_COLORS["unclear"],
    }

    fig = px.choropleth(
        df,
        locations="state_code",
        locationmode="USA-states",
        color="risk_display",
        color_discrete_map=color_discrete_map,
        scope="usa",
        hover_name="state_name",
        hover_data={"state_code": False, "risk_display": False, "legislation_type": False,
                    "provisions_short": False, "entities_str": False},
        category_orders={"risk_display": ["low", "medium", "high", "unknown", "unclear"]},
    )

    # px.choropleth with discrete colors creates one trace per risk category, not one per
    # state — so update_traces() with a flat array misaligns customdata. Instead, rebuild
    # customdata in trace.locations order for each trace individually.
    df_idx = df.set_index("state_code")

    def _cd(loc: str) -> list:
        if loc in df_idx.index:
            r = df_idx.loc[loc]
            return [r["risk_display"], r["legislation_type"], r["provisions_short"], r["entities_str"]]
        return ["unknown", "unknown", "", "None tracked"]

    _tmpl = (
        "<b>%{hovertext}</b><br>"
        "Risk: <b>%{customdata[0]}</b>&nbsp;&nbsp;|&nbsp;&nbsp;Type: %{customdata[1]}<br>"
        "%{customdata[2]}<br>"
        "<br>"
        "%{customdata[3]}"
        "<extra></extra>"
    )
    for trace in fig.data:
        trace.customdata = [_cd(loc) for loc in trace.locations]
        trace.hovertemplate = _tmpl

    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        legend_title_text="Risk Level",
        height=420,
        dragmode=False,
        geo=dict(bgcolor="rgba(0,0,0,0)"),
        paper_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False, "displayModeBar": False})

    counts = df["risk_display"].value_counts()
    cols = st.columns(5)
    for i, (level, label) in enumerate(_RISK_LABELS.items()):
        cols[i].metric(label, counts.get(level, 0))

    with st.expander("State legislation detail table"):
        display_cols = ["state_code", "state_name", "legislation_type", "risk_level",
                        "physician_admin_allowed", "wellness_allowed", "aesthetics_allowed",
                        "key_provisions", "effective_date", "last_updated"]
        st.dataframe(
            df[display_cols].rename(columns={
                "state_code": "Code", "state_name": "State",
                "legislation_type": "Type", "risk_level": "Risk",
                "physician_admin_allowed": "Physician OK",
                "wellness_allowed": "Wellness OK",
                "aesthetics_allowed": "Aesthetics OK",
                "key_provisions": "Key Provisions",
                "effective_date": "Effective",
                "last_updated": "Updated",
            }),
            use_container_width=True,
            hide_index=True,
        )


# ── SECTION B — Entity table ──────────────────────────────────────────────────

def render_entities(entities_df: pd.DataFrame):
    st.subheader("Section B — Entity Registry")

    if entities_df.empty:
        st.info("No entities loaded yet. Run `pipeline/seed_entities.py` first.")
        return

    # Sidebar filters
    with st.sidebar:
        st.header("Filters")

        all_types = sorted(entities_df["entity_type"].dropna().unique().tolist())
        sel_types = st.multiselect("Entity Type", all_types, default=all_types)

        all_states_raw = set()
        for s in entities_df["states"].dropna():
            for code in s.split(","):
                all_states_raw.add(code.strip())
        all_states = sorted(all_states_raw)
        sel_states = st.multiselect("State (any)", all_states)

        all_specs = sorted(entities_df["specialty"].dropna().unique().tolist())
        sel_specs = st.multiselect("Specialty", all_specs, default=all_specs)

        min_score = st.slider("Min Priority Score", 1.0, 10.0, 1.0, 0.5)
        min_gtm = st.slider("Min GTM Score", 0.0, 10.0, 0.0, 0.5)

        engagement_opts = ["active", "interested", "adjacent", "unknown"]
        sel_engagement = st.multiselect("Exosome Engagement", engagement_opts, default=engagement_opts)

        pricing_opts = sorted(entities_df["pricing_tier"].dropna().unique().tolist())
        sel_pricing = st.multiselect("Pricing Tier", pricing_opts, default=pricing_opts)

        openness_opts = sorted(entities_df["supplier_openness"].dropna().unique().tolist())
        sel_openness = st.multiselect("Supplier Openness", openness_opts, default=openness_opts)

        show_archived = st.toggle("Show Archived", value=False)

    df = entities_df.copy()
    if not show_archived:
        df = df[df["active"] == 1]

    if sel_types:
        df = df[df["entity_type"].isin(sel_types)]
    if sel_states:
        df = df[df["states"].apply(
            lambda s: any(code.strip() in sel_states for code in (s or "").split(","))
        )]
    if sel_specs:
        df = df[df["specialty"].isin(sel_specs)]
    df = df[df["priority_score"].fillna(0) >= min_score]
    df = df[df["gtm_score"].fillna(0) >= min_gtm]
    if sel_engagement:
        df = df[df["current_exosome_use"].isin(sel_engagement)]
    if sel_pricing:
        df = df[df["pricing_tier"].isin(sel_pricing)]
    if sel_openness:
        df = df[df["supplier_openness"].isin(sel_openness)]

    st.caption(f"Showing {len(df)} entities (of {len(entities_df)} total)")

    display_cols = ["id", "name", "entity_type", "states", "specialty", "products",
                    "current_exosome_use", "priority_score", "gtm_score", "pricing_tier",
                    "supplier_openness", "recent_deal", "website", "last_updated"]
    rename_map = {
        "id": "ID", "name": "Name", "entity_type": "Type", "states": "States",
        "specialty": "Specialty", "products": "Products",
        "current_exosome_use": "Engagement",
        "priority_score": "Score", "gtm_score": "GTM Score",
        "pricing_tier": "Pricing Tier", "supplier_openness": "Supplier Openness",
        "recent_deal": "Recent Deal",
        "website": "Website", "last_updated": "Updated",
    }
    show_df = df[display_cols].rename(columns=rename_map).reset_index(drop=True)

    # Add deal indicator column
    show_df.insert(1, "🔥", show_df["Recent Deal"].apply(lambda x: "🔥" if x else ""))

    def _highlight_deals(row):
        color = "background-color: #fff8e1; font-weight: 500;" if row.get("Recent Deal") else ""
        return [color] * len(row)

    styled = show_df.style.apply(_highlight_deals, axis=1)

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Website": st.column_config.LinkColumn("Website"),
            "Score": st.column_config.NumberColumn("Score", format="%.1f"),
            "GTM Score": st.column_config.NumberColumn("GTM Score", format="%.1f"),
            "🔥": st.column_config.TextColumn("🔥", width="small"),
            "Products": st.column_config.TextColumn("Products", width="medium"),
            "Recent Deal": st.column_config.TextColumn("Recent Deal", width="medium"),
        },
    )

    # Click-to-expand entity profile
    st.markdown("#### Entity Detail View")
    if len(df) > 0:
        if "entity_detail_open" not in st.session_state:
            st.session_state["entity_detail_open"] = False
        if "entity_detail_name" not in st.session_state:
            st.session_state["entity_detail_name"] = "—"

        sel_name = st.selectbox(
            "Select entity to view",
            ["—"] + df["name"].tolist(),
            index=(["—"] + df["name"].tolist()).index(st.session_state["entity_detail_name"])
                  if st.session_state["entity_detail_name"] in df["name"].tolist() else 0,
            key="entity_detail_select",
        )
        if sel_name != st.session_state["entity_detail_name"]:
            st.session_state["entity_detail_name"] = sel_name
            st.session_state["entity_detail_open"] = sel_name != "—"
            st.rerun()

        if st.session_state["entity_detail_open"] and sel_name != "—":
            row = df[df["name"] == sel_name].iloc[0]
            if row.get("recent_deal"):
                st.success(f"🔥 **Recent Deal:** {row['recent_deal']}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Name:** {row['name']}")
                st.markdown(f"**Type:** {row['entity_type']}")
                st.markdown(f"**States:** {row['states']}")
                st.markdown(f"**Specialty:** {row.get('specialty', '—')}")
                st.markdown(f"**Engagement:** {row.get('current_exosome_use', '—')}")
                st.markdown(f"**Priority Score:** {row.get('priority_score', '—')}")
                st.markdown(f"**GTM Score:** {row.get('gtm_score', '—')}")
                st.markdown(f"**Pricing Tier:** {row.get('pricing_tier', '—')}")
                st.markdown(f"**Supplier Openness:** {row.get('supplier_openness', '—')}")
                if row.get("manual_override_score"):
                    st.markdown(f"**Manual Override Score:** {row['manual_override_score']}")
            with c2:
                _web = row.get('website', '')
                st.markdown(f"**Website:** [{_web}]({_web})" if _web else "**Website:** —")
                st.markdown(f"**Contact:** {row.get('contact_info', '—')}")
                _li = row.get('linkedin_url', '')
                st.markdown(f"**LinkedIn:** [{_li}]({_li})" if _li else "**LinkedIn:** —")
                st.markdown(f"**Source:** {row.get('source', '—')}")
                st.markdown(f"**Active:** {'Yes' if row.get('active') else 'No (archived)'}")
                st.markdown(f"**IND Seeking:** {'Yes — EXCLUDED' if row.get('ind_seeking') else 'No'}")
            st.markdown(f"**Products:** {row.get('products', '—')}")
            st.markdown(f"**Notes:** {row.get('notes', '—')}")
            if st.button("✕ Close detail"):
                st.session_state["entity_detail_open"] = False
                st.session_state["entity_detail_name"] = "—"
                st.rerun()

    # Export
    buf = io.BytesIO()
    df[display_cols].rename(columns=rename_map).to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    st.sidebar.download_button(
        "Export Filtered Table (Excel)",
        data=buf,
        file_name=f"exo_market_entities_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── SECTION B2 — GTM priority bubble chart ────────────────────────────────────

def render_gtm_bubble_chart(entities_df: pd.DataFrame):
    st.subheader("Section B2 — Go-to-Market Priority Map")
    st.caption(
        "Bubble size = estimated reach/scale (clinic count or footprint). "
        "Color = entity type. ⭐ = confirmed recent deal (acquisition/partnership since 2024)."
    )

    with st.expander("How is GTM Score calculated?"):
        st.markdown(
            "GTM Score (0-10) weights five factors:\n\n"
            "| Factor | Weight | Scoring |\n"
            "|---|---|---|\n"
            "| Pricing Tier | 30% | premium=10, mid-market=6, mass=3, unknown=2 |\n"
            "| Exosome Readiness | 25% | active=10, interested=5, adjacent=3, unknown=1 |\n"
            "| Operation Scale | 15% | derived from estimated clinic count / footprint |\n"
            "| Legislation Favorability | 15% | low risk=10, medium=6, high=3, unknown=2 |\n"
            "| Priority Score | 15% | existing 1-10 legislation/reach/engagement/contact score |\n\n"
            "**Pricing Tier carries the heaviest weight**: entities pricing their products/services "
            "more aggressively run on better margins and tend to be more open to adopting new/improved "
            "products — making them better first-wave GTM targets. Tiers are assigned per segment "
            "(distributor B2B vial pricing, MSO/KOL patient-facing session pricing, CME course pricing) "
            "so comparisons stay apples-to-apples — see the **Pricing Basis** column in the ranked table below."
        )

    df = entities_df[entities_df["active"] == 1].copy()
    if df.empty:
        st.info("No active entities to plot.")
        return

    bubble_types = sorted(df["entity_type"].dropna().unique().tolist())
    sel_bubble_types = st.multiselect(
        "Filter by Entity Type", bubble_types, default=bubble_types, key="gtm_bubble_type_filter"
    )
    if sel_bubble_types:
        df = df[df["entity_type"].isin(sel_bubble_types)]
    if df.empty:
        st.info("No entities match the selected type filter.")
        return

    with get_conn() as conn:
        df["readiness"] = df["current_exosome_use"].apply(
            lambda v: _READINESS_SCORE.get((v or "unknown").lower(), 1.0)
        )
        df["legislation"] = df["states"].apply(lambda s: _legislation_score(s, conn))
        df["scale"] = df.apply(
            lambda r: _scale_score(r["notes"], r["products"], r["states"]), axis=1
        )

    df["has_deal"] = df["recent_deal"].fillna("") != ""
    df["marker_symbol"] = df["has_deal"].map({True: "star", False: "circle"})

    # Spread entities sharing the same readiness/legislation score out into a
    # sunflower pattern around that point, so dense clusters fan out instead
    # of stacking on top of each other.
    def _spread_offsets(n: int, max_radius: float = 1.6) -> list[tuple[float, float]]:
        if n <= 1:
            return [(0.0, 0.0)]
        golden_angle = math.pi * (3 - math.sqrt(5))
        return [
            (
                max_radius * math.sqrt((i + 0.5) / n) * math.cos(i * golden_angle),
                max_radius * math.sqrt((i + 0.5) / n) * math.sin(i * golden_angle),
            )
            for i in range(n)
        ]

    df["x_jitter"] = df["legislation"].astype(float)
    df["y_jitter"] = df["readiness"].astype(float)
    for (leg, read), group in df.groupby(["legislation", "readiness"]):
        offsets = _spread_offsets(len(group))
        for (idx, _), (dx, dy) in zip(group.iterrows(), offsets):
            df.loc[idx, "x_jitter"] = leg + dx
            df.loc[idx, "y_jitter"] = read + dy

    fig = px.scatter(
        df,
        x="x_jitter",
        y="y_jitter",
        size="scale",
        color="entity_type",
        symbol="marker_symbol",
        symbol_map={"star": "star", "circle": "circle"},
        hover_name="name",
        custom_data=["states", "gtm_score", "recent_deal", "current_exosome_use"],
        size_max=26,
        opacity=0.75,
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "States: %{customdata[0]}<br>"
            "Engagement: %{customdata[3]}<br>"
            "GTM Score: %{customdata[1]}<br>"
            "Recent Deal: %{customdata[2]}"
            "<extra></extra>"
        )
    )
    fig.update_layout(
        height=650,
        xaxis_title="Legislation Favorability →",
        yaxis_title="Exosome Readiness →",
        xaxis=dict(range=[-0.5, 12.5], showgrid=True),
        yaxis=dict(range=[-2, 12.5], showgrid=True),
        legend_title_text="Entity Type",
        title={
            "text": "<b>GTM Priority Map — Exosome Market Entities</b>",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 20, "color": "#1f77b4"},
        },
        margin={"t": 60},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Best first-wave targets sit in the **top-right** (high readiness, favorable legislation) "
        "with large bubbles (strong reach/scale)."
    )

    st.markdown("##### Ranked Targets")
    st.caption("Click any column header to sort.")
    df["pricing_basis"] = df.apply(
        lambda r: get_pricing_basis(r["entity_type"], r["pricing_tier"], r["name"]), axis=1
    )
    ranked_cols = ["name", "entity_type", "states", "gtm_score", "pricing_tier",
                   "pricing_basis", "readiness", "legislation", "scale", "recent_deal"]
    ranked = (
        df[ranked_cols]
        .rename(columns={
            "name": "Name", "entity_type": "Type", "states": "States",
            "gtm_score": "GTM Score", "pricing_tier": "Pricing Tier",
            "pricing_basis": "Pricing Basis", "readiness": "Readiness",
            "legislation": "Legislation", "scale": "Operation Scale", "recent_deal": "Recent Deal",
        })
        .sort_values("GTM Score", ascending=False)
        .reset_index(drop=True)
    )
    st.dataframe(
        ranked,
        use_container_width=True,
        hide_index=True,
        column_config={
            "GTM Score": st.column_config.NumberColumn("GTM Score", format="%.1f"),
            "Readiness": st.column_config.NumberColumn("Readiness", format="%.1f"),
            "Legislation": st.column_config.NumberColumn("Legislation", format="%.1f"),
            "Operation Scale": st.column_config.NumberColumn("Operation Scale", format="%.1f"),
            "Pricing Basis": st.column_config.TextColumn("Pricing Basis", width="large"),
        },
    )


# ── SECTION C — Update log ────────────────────────────────────────────────────

def render_update_log(log_df: pd.DataFrame):
    with st.expander("Section C — Update Log (last 30 entries)", expanded=False):
        if log_df.empty:
            st.info("No log entries yet.")
            return
        st.dataframe(
            log_df.rename(columns={
                "log_date": "Date", "entity_name": "Entity", "change_type": "Change",
                "description": "Description", "source_url": "Source URL", "logged_by": "Logged By",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={"Source URL": st.column_config.LinkColumn("Source URL")},
        )


# ── SECTION D — Sidebar controls ─────────────────────────────────────────────

def render_sidebar_controls(entities_df: pd.DataFrame):
    with st.sidebar:
        st.divider()
        st.header("Add Entity")

        with st.form("add_entity_form", clear_on_submit=True):
            name = st.text_input("Name *")
            entity_type = st.selectbox("Type *", ["distributor", "CME", "KOL", "MSO"])
            states = st.text_input("States (comma-separated, e.g. FL,TX or INTL)")
            country = st.text_input("Country", "US")
            us_reach = st.checkbox("US Reach", value=True)
            specialty = st.text_input("Specialty")
            engagement = st.selectbox("Exosome Engagement", ["unknown", "active", "interested", "adjacent"])
            ind_seeking = st.checkbox("IND Seeking (EXCLUDES from dashboard)", value=False)
            website = st.text_input("Website")
            contact_info = st.text_input("Contact Info")
            linkedin_url = st.text_input("LinkedIn URL")
            products = st.text_input("Products (comma-separated key products/brands)")
            recent_deal = st.text_input("Recent Deal (acquisition, partnership, or supply deal since 2024)")
            pricing_tier = st.selectbox("Pricing Tier", ["unknown", "mass", "mid-market", "premium"])
            supplier_openness = st.selectbox(
                "Supplier Openness",
                ["unknown", "multi-vendor (open)", "limited (selective)", "exclusive (single-source)"],
            )
            notes = st.text_area("Notes")
            source = st.text_input("Source / How Discovered")
            submitted = st.form_submit_button("Add Entity")

        if submitted:
            if not name:
                st.sidebar.error("Name is required.")
            else:
                with get_conn() as conn:
                    score = calculate_score(states, engagement, website, contact_info, int(ind_seeking), conn)
                    gtm_score = calculate_gtm_score(
                        states, engagement, notes, products, score, int(ind_seeking), conn,
                        pricing_tier,
                    )
                    conn.execute(
                        """INSERT INTO entity_registry
                           (name, entity_type, states, country, us_reach, specialty,
                            current_exosome_use, ind_seeking, website, contact_info,
                            linkedin_url, priority_score, products, recent_deal,
                            notes, source, last_updated, active, gtm_score,
                            pricing_tier, supplier_openness)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (name, entity_type, states, country, int(us_reach), specialty,
                         engagement, int(ind_seeking), website, contact_info, linkedin_url,
                         score, products, recent_deal,
                         notes, source, datetime.now(timezone.utc).isoformat(),
                         0 if ind_seeking else 1, gtm_score,
                         pricing_tier, supplier_openness),
                    )
                    log_change(conn, name, "new", f"Added via dashboard form | type={entity_type} | score={score}", "user")
                invalidate_cache()
                st.sidebar.success(f"Added {name} (score: {score})")
                st.rerun()

        st.divider()
        st.header("Pipeline")
        if st.button("Run Refresh Pipeline"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "pipeline" / "refresh.py")],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                st.sidebar.success("Refresh complete.")
            else:
                st.sidebar.error(f"Refresh failed: {result.stderr[:200]}")
            invalidate_cache()

        st.divider()
        st.header("Dashboard Stats")
        with get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entity_registry WHERE active=1").fetchone()[0]
            excluded = conn.execute("SELECT COUNT(*) FROM entity_registry WHERE ind_seeking=1").fetchone()[0]
            by_type = conn.execute(
                "SELECT entity_type, COUNT(*) as n FROM entity_registry WHERE active=1 GROUP BY entity_type"
            ).fetchall()
            last_log = conn.execute("SELECT MAX(log_date) FROM update_log").fetchone()[0]

        st.metric("Active Entities", total)
        st.metric("Excluded (IND Seeking)", excluded)
        for row in by_type:
            st.write(f"- **{row['entity_type']}**: {row['n']}")
        st.caption(f"Last update: {last_log or 'never'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def render_instructions():
    with st.expander("📖 How to use this dashboard — click to collapse", expanded=True):
        st.markdown("""
**Purpose**
This dashboard maps the commercial (non-IND) US exosome market for NurExone — tracking
state legislation risk, potential distribution and partnership entities, and deal activity.

---

**Section A — US State Legislation Map**
Choropleth of all 50 states colour-coded by regulatory risk for non-IND exosome/cell therapy:
- 🟢 **Low** — physician exemption active (FL, UT, NH); priority states for entry
- 🟡 **Medium** — Right-to-Try or advancing legislation; secondary targets
- 🔴 **High** — No exemption or active FDA-aligned enforcement; avoid initial entry
- ⚫ **Unknown** — Insufficient data

Hover over a state for key provisions. Expand the detail table for full legislation data.

---

**Section B — Entity Registry**
Filterable table of commercial partners across four categories:
| Type | Who they are |
|---|---|
| **Distributor** | B2B suppliers, GPOs, and logistics handlers for biologics |
| **CME** | Physician education providers — key recruitment channel for product adoption |
| **KOL** | Key Opinion Leaders who influence clinical adoption through speaking and case studies |
| **MSO** | Management Service Organizations and clinic networks — gate-keepers for standardised procurement |

**Priority Score (1–10)** is auto-calculated from: legislation risk (35%) · geographic reach (25%) ·
exosome engagement (25%) · contact completeness (15%).

**GTM Score (0–10)** ranks entities for first-wave marketing outreach: exosome readiness (35%) ·
reach/scale — clinic count or footprint, estimated from notes (25%) · legislation favorability (20%) ·
Priority Score (20%). Click the column header to sort.

**Pricing Tier** and **Supplier Openness** are manually-curated fields (default `unknown` until researched):
- *Pricing Tier* — `mass`, `mid-market`, or `premium`, based on the entity's typical client base/positioning.
- *Supplier Openness* — `multi-vendor (open)` (carries multiple brands, easy to add a new line),
  `limited (selective)`, or `exclusive (single-source)` (locked to one supplier/parent company).

**🔥 Recent Deal** marks entities with a confirmed acquisition, partnership, or distribution deal in the past 2 years.
These are the highest-priority outreach targets — they are actively expanding and looking for vendors.

Use the **sidebar filters** to narrow by Type, State, Specialty, Score, GTM Score, Engagement,
Pricing Tier, and Supplier Openness.
Click **Export Filtered Table (Excel)** in the sidebar to download your selection.

---

**Section B2 — Go-to-Market Priority Map**
Bubble chart plotting active entities by **Exosome Readiness** (y-axis) vs **Legislation Favorability** (x-axis).
Bubble size reflects estimated reach/scale (clinic count or multi-state footprint), and color marks entity type.
Entities marked with a ⭐ have a confirmed recent deal. The **top-right, largest bubbles** are the best
first-wave marketing targets.

---

**Adding a New Entity**
Use the **Add Entity** form in the sidebar:
1. **Name** and **Type** are required.
2. **States** — enter comma-separated 2-letter codes (e.g. `FL,TX`) or `INTL` for international.
3. **Exosome Engagement** — set honestly:
   - *active* = currently buying/using exosome products
   - *interested* = expressed intent or adjacent positioning
   - *adjacent* = in the regenerative space but no confirmed exosome activity
   - *unknown* = unverified
4. Tick **IND Seeking** if the entity has active ClinicalTrials.gov registrations — this sets their score to 0 and hides them from the active registry (commercial pathway only).
5. The **Priority Score** is calculated automatically on save.
6. All additions are logged to the **Update Log** (Section C) for audit purposes.
""")


def main():
    st.title("🎯 ExoRadar — US Exosome Market & GTM Intelligence")
    st.caption("Commercial (non-IND) pathway only. All entities reflect physician-administered or wellness/aesthetics use.")

    render_instructions()

    states_df = load_states()
    entities_df = load_entities()
    log_df = load_update_log()

    render_sidebar_controls(entities_df)
    render_map(states_df, entities_df)
    st.divider()
    render_entities(entities_df)
    st.divider()
    render_gtm_bubble_chart(entities_df)
    st.divider()
    render_update_log(log_df)


if __name__ == "__main__":
    main()
