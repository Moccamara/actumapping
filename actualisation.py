import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from folium.plugins import MeasureControl, Draw
import pandas as pd
import altair as alt
import matplotlib.pyplot as plt
from shapely.geometry import shape

# =========================================================
# APP CONFIG
# =========================================================
st.set_page_config(layout="wide", page_title="Geospatial Enterprise Solution")
st.title("🌍 Geospatial Enterprise Solution")

# =========================================================
# USERS AND ROLES
# =========================================================
USERS = {
    "admin": {"password": "admin2025", "role": "Admin"},
    "customer": {"password": "cust2025", "role": "Customer"},
}

# =========================================================
# SESSION STATE INIT
# =========================================================
if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False
    st.session_state.username = None
    st.session_state.user_role = None
    st.session_state.points_gdf = None

# =========================================================
# LOGOUT
# =========================================================
def logout():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# =========================================================
# LOGIN
# =========================================================
if not st.session_state.auth_ok:
    st.sidebar.header("🔐 Login")
    username = st.sidebar.selectbox("User", list(USERS.keys()))
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        if password == USERS[username]["password"]:
            st.session_state.auth_ok = True
            st.session_state.username = username
            st.session_state.user_role = USERS[username]["role"]
            st.rerun()
        else:
            st.sidebar.error("❌ Incorrect password")

    st.stop()

# =========================================================
# LOAD SE POLYGONS
# =========================================================
SE_URL = "https://raw.githubusercontent.com/Moccamara/web_mapping/master/data/SE.geojson"

@st.cache_data(show_spinner=False)
def load_se_data(url):
    gdf = gpd.read_file(url).to_crs(epsg=4326)
    gdf.columns = gdf.columns.str.lower().str.strip()

    gdf = gdf.rename(columns={
        "lregion": "region",
        "lcercle": "cercle",
        "lcommune": "commune"
    })

    for col in ["region", "cercle", "commune", "idse_new"]:
        if col not in gdf.columns:
            gdf[col] = ""

    for col in ["pop_se", "pop_se_ct"]:
        if col not in gdf.columns:
            gdf[col] = 0

    gdf = gdf[gdf.is_valid & ~gdf.is_empty]
    return gdf

gdf = load_se_data(SE_URL)

# =========================================================
# LOAD CONCESSION POINTS
# =========================================================
POINTS_URL = "https://raw.githubusercontent.com/Moccamara/web_mapping/master/data/concession.csv"

@st.cache_data(show_spinner=False)
def load_points(url):
    df = pd.read_csv(url)
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df.dropna(subset=["LAT", "LON"])

    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["LON"], df["LAT"]),
        crs="EPSG:4326"
    )

if st.session_state.points_gdf is None:
    st.session_state.points_gdf = load_points(POINTS_URL)

points_gdf = st.session_state.points_gdf

# =========================================================
# SAFE SPATIAL JOIN
# =========================================================
def safe_sjoin(points, polygons):
    polygons = polygons.copy()
    for col in polygons.columns:
        if col.startswith("index_"):
            polygons.drop(columns=[col], inplace=True)
    return gpd.sjoin(points, polygons, predicate="intersects", how="inner")

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown(f"**👤 User:** {st.session_state.username} ({st.session_state.user_role})")
    if st.button("Logout"):
        logout()

    st.markdown("### 🗂 Attribute Query")

    region = st.selectbox("Region", sorted(gdf["region"].unique()))
    gdf_r = gdf[gdf["region"] == region]

    cercle = st.selectbox("Cercle", sorted(gdf_r["cercle"].unique()))
    gdf_c = gdf_r[gdf_r["cercle"] == cercle]

    commune = st.selectbox("Commune", sorted(gdf_c["commune"].unique()))
    gdf_commune = gdf_c[gdf_c["commune"] == commune]

    idse_list = ["No filter"] + sorted(gdf_commune["idse_new"].unique())
    idse_selected = st.selectbox("SE", idse_list)

    gdf_idse = (
        gdf_commune if idse_selected == "No filter"
        else gdf_commune[gdf_commune["idse_new"] == idse_selected]
    )

# =========================================================
# MAP
# =========================================================
minx, miny, maxx, maxy = gdf_idse.total_bounds
m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=17)

folium.TileLayer("OpenStreetMap").add_to(m)
folium.GeoJson(
    gdf_idse,
    style_function=lambda x: {
        "color": "blue",
        "weight": 2,
        "fillOpacity": 0.15
    },
    tooltip=folium.GeoJsonTooltip(fields=["idse_new", "pop_se", "pop_se_ct"])
).add_to(m)

for _, r in points_gdf.iterrows():
    folium.CircleMarker(
        [r.geometry.y, r.geometry.x],
        radius=3,
        color="red",
        fill=True,
        fill_opacity=0.8
    ).add_to(m)

Draw(export=False).add_to(m)
MeasureControl().add_to(m)
folium.LayerControl().add_to(m)

# =========================================================
# LAYOUT
# =========================================================
col_map, col_chart = st.columns((3, 1), gap="small")

# ---------------- MAP + POLYGON QUERY -------------------
with col_map:
    map_data = st_folium(
        m,
        height=500,
        returned_objects=["all_drawings"],
        use_container_width=True
    )

    # 🔻 POLYGON-BASED STATISTICS (ONLY HERE)
    if map_data and map_data.get("all_drawings"):
        last_feature = map_data["all_drawings"][-1]

        if "geometry" in last_feature:
            poly = shape(last_feature["geometry"])

            pts_poly = points_gdf[points_gdf.geometry.within(poly)]

            st.subheader("🟢 Polygon-based statistics")

            if pts_poly.empty:
                st.info("No points inside drawn polygon.")
            else:
                m_poly = pd.to_numeric(
                    pts_poly.get("Masculin"), errors="coerce"
                ).fillna(0).sum()

                f_poly = pd.to_numeric(
                    pts_poly.get("Feminin"), errors="coerce"
                ).fillna(0).sum()

                st.markdown(
                    f"""
                    - 👨 **Masculin**: {int(m_poly)}
                    - 👩 **Feminin**: {int(f_poly)}
                    - 👥 **Total**: {int(m_poly + f_poly)}
                    """
                )

                fig, ax = plt.subplots(figsize=(3, 3))
                ax.pie(
                    [m_poly, f_poly],
                    labels=["Masculin", "Feminin"],
                    autopct="%1.1f%%",
                    startangle=90
                )
                ax.axis("equal")
                st.pyplot(fig)

# ---------------- RIGHT SE CHARTS (UNCHANGED) -------------------
with col_chart:
    if idse_selected == "No filter":
        st.info("Select SE.")
    else:
        st.subheader("📊 Population")

        df_long = gdf_idse[["idse_new", "pop_se", "pop_se_ct"]].melt(
            id_vars="idse_new",
            var_name="Type",
            value_name="Population"
        )

        chart = alt.Chart(df_long).mark_bar().encode(
            x="idse_new:N",
            y="Population:Q",
            color="Type:N"
        ).properties(height=180)

        st.altair_chart(chart, use_container_width=True)

        st.subheader("👥 Sex (SE)")

        pts_se = safe_sjoin(points_gdf, gdf_idse)

        m_total = pts_se.get("Masculin", pd.Series()).sum()
        f_total = pts_se.get("Feminin", pd.Series()).sum()

        st.markdown(
            f"""
            - 👨 **M**: {int(m_total)}
            - 👩 **F**: {int(f_total)}
            - 👥 **Total**: {int(m_total + f_total)}
            """
        )

        fig, ax = plt.subplots(figsize=(3, 3))
        ax.pie([m_total, f_total], labels=["M", "F"], autopct="%1.1f%%")
        ax.axis("equal")
        st.pyplot(fig)

# =========================================================
# FOOTER
# =========================================================
st.markdown("""
---
**Geospatial Enterprise Web Mapping**  
**Mahamadou CAMARA, PhD – Geomatics Engineering** © 2025
""")

