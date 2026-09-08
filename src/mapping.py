"""
mapping.py — turn the risk table into an interactive map you can send someone.

WHY AN INTERACTIVE MAP AND NOT A PNG
A static image is a picture of a conclusion. An interactive map lets the person you are
talking to find their own street, click it, and see the actual numbers behind the colour.
That is the difference between showing someone a result and letting them interrogate it —
and the second one is what earns trust from someone who knows the city better than you do.

Folium wraps Leaflet.js, the same mapping library behind a large share of the web maps
you have used. The output is a single self-contained HTML file: no server, no build step,
open it in any browser, email it to anyone.
"""

import branca.colormap as cm
import folium
import numpy as np

from . import config


# Colour scale: green (safe) through yellow and orange to dark red (worst).
# Chosen because it reads correctly for the most common forms of colour blindness in
# a way that a red/green-only scale does not — worth mentioning if anyone asks about
# accessibility, which is a question that separates careful work from careless work.
RISK_COLOURS = ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"]


def _risk_colour(value, colormap):
    """Colour for a risk value, with grey standing in for missing data."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "#cccccc"
    return colormap(value)


def build_risk_map(table, grid, drains=None, top_areas=None,
                   synthetic=False, validation=None, output_path=None):
    """
    Build the main interactive risk map.

    Parameters
    ----------
    synthetic : if True, stamps a prominent warning banner across the map. Never turn
                this off for demo data — a map that looks authoritative and is not is
                actively harmful, and someone will eventually screenshot it.
    """
    output_path = output_path or (config.OUTPUT_DIR / "jaipur_flood_risk_map.html")

    centre = [
        (grid["bounds"]["min_lat"] + grid["bounds"]["max_lat"]) / 2,
        (grid["bounds"]["min_lon"] + grid["bounds"]["max_lon"]) / 2,
    ]

    risk_map = folium.Map(
        location=centre,
        zoom_start=12,
        tiles="OpenStreetMap",   # free, no API key required
        control_scale=True,
    )

    colormap = cm.LinearColormap(
        colors=RISK_COLOURS, vmin=0, vmax=100,
        caption="Relative flood risk index (0 = lowest in Jaipur, 100 = highest)",
    )

    # --- the risk grid --------------------------------------------------------
    risk_layer = folium.FeatureGroup(name="Flood risk index", show=True)
    urban_cells = table[table["is_urban"] & table["risk_index"].notna()]

    half_lat = grid["cell_lat_degrees"] / 2
    half_lon = grid["cell_lon_degrees"] / 2

    for _, cell in urban_cells.iterrows():
        bounds = [
            [cell["lat"] - half_lat, cell["lon"] - half_lon],
            [cell["lat"] + half_lat, cell["lon"] + half_lon],
        ]

        stability = cell.get("rank_stability", None)
        stability_line = ""
        if stability is not None and not (isinstance(stability, float) and np.isnan(stability)):
            stability_line = (
                f"<tr><td>Robustness</td><td><b>{stability * 100:.0f}%</b> of weightings"
                f"</td></tr>"
            )

        popup_html = f"""
        <div style="font-family: system-ui, sans-serif; font-size: 13px; min-width: 240px">
          <div style="font-size:15px;font-weight:600;margin-bottom:6px">
            Risk index {cell['risk_index']:.0f}/100 &mdash; {cell['risk_band']}
          </div>
          <table style="border-collapse:collapse;width:100%">
            <tr><td>Hazard</td><td><b>{cell['hazard_score']:.2f}</b></td></tr>
            <tr><td>Exposure</td><td><b>{cell['exposure_score']:.2f}</b></td></tr>
            <tr><td>Sensitivity</td><td><b>{cell['sensitivity_score']:.2f}</b></td></tr>
            {stability_line}
            <tr><td colspan="2"><hr style="margin:4px 0"></td></tr>
            <tr><td>Elevation</td><td>{cell['elevation_m']:.0f} m</td></tr>
            <tr><td>Relative to area</td><td>{cell['relative_elevation_m']:+.1f} m</td></tr>
            <tr><td>Wetness index</td><td>{cell['twi']:.1f}</td></tr>
            <tr><td>Depression depth</td><td>{cell['depression_depth_m']:.2f} m</td></tr>
            <tr><td>Nearest drain</td><td>{cell['drain_distance_m']:.0f} m</td></tr>
            <tr><td>Buildings</td><td>{cell['building_count']:.0f}</td></tr>
          </table>
          <div style="margin-top:6px;color:#666;font-size:11px">
            {cell['lat']:.4f}, {cell['lon']:.4f}
          </div>
        </div>
        """

        folium.Rectangle(
            bounds=bounds,
            color=None,
            fill=True,
            fill_color=_risk_colour(cell["risk_index"], colormap),
            fill_opacity=0.55,
            weight=0,
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(risk_layer)

    risk_layer.add_to(risk_map)

    # --- drainage network -----------------------------------------------------
    if drains:
        drain_layer = folium.FeatureGroup(name="Mapped drainage (OpenStreetMap)", show=True)
        for drain in drains:
            if len(drain["points"]) < 2:
                continue
            is_major = drain["type"] in {"river", "canal"}
            folium.PolyLine(
                locations=drain["points"],
                color="#0570b0" if is_major else "#74a9cf",
                weight=3 if is_major else 1.5,
                opacity=0.85,
                tooltip=drain["name"] or drain["type"],
            ).add_to(drain_layer)
        drain_layer.add_to(risk_map)

    # --- priority sites -------------------------------------------------------
    if top_areas is not None and len(top_areas) > 0:
        priority_layer = folium.FeatureGroup(name="Top priority sites", show=True)
        for rank, (_, site) in enumerate(top_areas.iterrows(), start=1):
            folium.Marker(
                location=[site["lat"], site["lon"]],
                icon=folium.DivIcon(html=f"""
                    <div style="background:#7f0000;color:white;border-radius:50%;
                                width:24px;height:24px;line-height:24px;text-align:center;
                                font-weight:700;font-size:12px;
                                font-family:system-ui,sans-serif;
                                border:2px solid white;
                                box-shadow:0 1px 4px rgba(0,0,0,.4)">{rank}</div>
                """),
                tooltip=f"Priority {rank}: risk {site['risk_index']:.0f}/100",
            ).add_to(priority_layer)
        priority_layer.add_to(risk_map)

    # --- validation points ----------------------------------------------------
    if validation is not None and len(validation) > 0:
        validation_layer = folium.FeatureGroup(name="Ground-truth observations", show=False)
        for _, point in validation.iterrows():
            flooded = point["flooded"] == 1
            folium.CircleMarker(
                location=[point["lat"], point["lon"]],
                radius=5,
                color="#000000",
                weight=1,
                fill=True,
                fill_color="#08306b" if flooded else "#f7f7f7",
                fill_opacity=0.9,
                tooltip=(f"{point['name']}<br>"
                         f"{'Waterlogged' if flooded else 'Stayed dry'}<br>"
                         f"Model said: {point.get('risk_index', float('nan')):.0f}/100"),
            ).add_to(validation_layer)
        validation_layer.add_to(risk_map)

    colormap.add_to(risk_map)
    folium.LayerControl(collapsed=False).add_to(risk_map)

    # --- the synthetic-data warning ------------------------------------------
    if synthetic:
        warning = """
        <div style="position:fixed; top:10px; left:50%; transform:translateX(-50%);
                    z-index:9999; background:#b30000; color:white;
                    padding:10px 18px; border-radius:6px;
                    font-family:system-ui,sans-serif; font-size:13px; font-weight:600;
                    box-shadow:0 2px 10px rgba(0,0,0,.35); text-align:center;
                    max-width:90vw">
          SYNTHETIC TEST DATA &mdash; NOT REAL JAIPUR RESULTS<br>
          <span style="font-weight:400;font-size:12px">
            This map exists to demonstrate that the pipeline works. The terrain and
            infrastructure are computer-generated. Run the notebook with live data
            for real results.
          </span>
        </div>
        """
        risk_map.get_root().html.add_child(folium.Element(warning))

    risk_map.save(str(output_path))
    print(f"Map written to {output_path}")

    return risk_map


def build_diagnostic_maps(table, grid, output_dir=None):
    """
    Separate maps for each component, for debugging and for the write-up.

    WHY THIS IS WORTH DOING
    When the combined index says a place is high risk, you want to know WHY — was it
    the terrain, or just that a lot of buildings happen to be there? Looking at the
    layers separately is how you catch the case where one component is quietly driving
    everything and the others are along for the ride.
    """
    output_dir = output_dir or config.OUTPUT_DIR

    components = {
        "hazard_score": ("Hazard — where water collects", "hazard_map.html"),
        "exposure_score": ("Exposure — what is in the way", "exposure_map.html"),
        "sensitivity_score": ("Sensitivity — coping capacity proxy", "sensitivity_map.html"),
        "twi": ("Topographic Wetness Index", "twi_map.html"),
    }

    centre = [
        (grid["bounds"]["min_lat"] + grid["bounds"]["max_lat"]) / 2,
        (grid["bounds"]["min_lon"] + grid["bounds"]["max_lon"]) / 2,
    ]

    half_lat = grid["cell_lat_degrees"] / 2
    half_lon = grid["cell_lon_degrees"] / 2
    urban_cells = table[table["is_urban"]]

    for column, (title, filename) in components.items():
        if column not in table.columns:
            continue

        values = urban_cells[column].dropna()
        if len(values) == 0:
            continue

        component_map = folium.Map(location=centre, zoom_start=12, tiles="OpenStreetMap")
        colormap = cm.LinearColormap(
            colors=RISK_COLOURS, vmin=float(values.min()), vmax=float(values.max()),
            caption=title,
        )

        for _, cell in urban_cells.iterrows():
            value = cell[column]
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            folium.Rectangle(
                bounds=[[cell["lat"] - half_lat, cell["lon"] - half_lon],
                        [cell["lat"] + half_lat, cell["lon"] + half_lon]],
                fill=True, fill_color=colormap(value), fill_opacity=0.6, weight=0,
                tooltip=f"{title}: {value:.2f}",
            ).add_to(component_map)

        colormap.add_to(component_map)
        component_map.save(str(output_dir / filename))
        print(f"  wrote {filename}")
