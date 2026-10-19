# FlyApp

FlyApp is a Streamlit dashboard for tracking aircraft near a configured location. It retrieves live flight data, calculates distance and flyby information, detects flight patterns and trajectory anomalies, stores results in SQLite, and displays the results on an interactive map and in tables.

## Features

- Live aircraft tracking through FlightRadar24 API data
- Configurable monitoring coordinates and radius
- Interactive Folium flight map
- Flight list and flyby schedule views
- Distance, heading, bearing, speed, and flyby ETA calculations
- Basic flight pattern detection:
  - Circular
  - Linear
  - Erratic
  - Normal
- Optional advanced pattern clustering with scikit-learn
- Trajectory anomaly detection for:
  - Bearing deviations
  - Altitude deviations
  - Timing deviations
- Local SQLite storage for flights, trails, airports, airlines, patterns, and anomalies
- Automatic dashboard refresh

## Project structure

| File | Purpose |
| --- | --- |
| `streamlit_app.py` | Streamlit dashboard and user interface |
| `main.py` | Flight calculations, processing, map helpers, pattern detection, and anomaly detection |
| `sql_utils.py` | SQLite database initialization and data-access utilities |
| `config.ini` | Tracking location, radius, refresh, and analysis settings |
| `requirements.txt` | Python dependencies |
| `sql_database.db` | Local runtime database; generated or updated by the application |
| `run_streamlit.bat` | Windows launcher |
| `run_streamlit.command` | macOS/Linux launcher |
| `.streamlit/config.toml` | Streamlit theme settings |

## Requirements

- Python 3.14 or a compatible Python version
- Internet access for live flight data
- A FlightRadar24 API connection supported by `FlightRadarAPI`

## Installation

Open PowerShell in the project folder:

```powershell
cd "C:\Users\shiro\Downloads\flightappshiro\flightapp"
python -m pip install -r requirements.txt
```

For a clean local environment, use a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Running the application

Start the application with:

```powershell
python -m streamlit run streamlit_app.py
```

Then open:

<http://127.0.0.1:8501>

On Windows, you can also double-click `run_streamlit.bat`.

Stop the application with `Ctrl+C` in the terminal.

## Configuration

Edit `config.ini` before starting the application:

```ini
[Settings]
location_coords = 40.7127, -74.0059
location_radius = 100
auto_refresh_interval = 30
ignore_airport_proximity = False
debug_mode = False
```

Settings:

- `location_coords`: latitude and longitude to monitor
- `location_radius`: monitoring radius in kilometers; supported values are 50, 100, 150, and 200
- `auto_refresh_interval`: refresh interval in seconds; supported values are 0, 15, 30, and 60
- `ignore_airport_proximity`: whether to calculate flyby information for aircraft likely approaching nearby airports
- `debug_mode`: enables additional diagnostic logging

## Understanding the Schedule page

The Schedule page is a predicted nearby flyby list, not an official airport timetable. It only displays flights for which FlyApp can calculate a valid flyby ETA. Flights without enough trail, speed, heading, or flyby information are excluded from that view.

## Database

FlyApp uses SQLite and does not require a separate database server. The database contains:

- Current and historical flight information
- Aircraft trails
- Airport and airline reference data
- Detected flight patterns
- Trajectory anomaly results

The database is intentionally excluded from new Git commits by `.gitignore` because it contains runtime-generated data. A local database file may still be present in an existing working copy.

## Notes

- Live results depend on the availability and response of the FlightRadar24 service.
- The application filters out ground vehicles, aircraft below the minimum speed, and aircraft outside the configured circular radius.
- `pyarrow==23.0.1` is pinned in `requirements.txt` for Windows compatibility with the tested Python 3.14 environment.
- Do not commit API credentials, local secrets, or generated runtime files.

## License

No license has been specified for this project yet. Add a license file before distributing the project publicly.
