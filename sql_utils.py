# Built-in libraries
import json
from datetime import datetime, timedelta
import sqlite3 as sql

# Third-party libraries -> requirements.txt
import airportsdata
import numpy as np



class SQLiteX33:
    """A streamlined SQLite Database Context Manager for easy SQL queries. Import as 'import sqlite_x33 as sql', then use sql.execute(db, query). /hodel33 & dyaland"""
    def __init__(self, db_file_path:str):
        self.db_file = db_file_path
        
    def __enter__(self):
        self.connection = sql.connect(self.db_file)
        self.connection.row_factory = sql.Row  # Enable dictionary-like row access, e.g. row['name']
        self.cursor = self.connection.cursor()
        self.cursor.execute("PRAGMA foreign_keys = True;") # Enable FOREIGN KEYS for SQLite 3
        return self
    
    def __exit__(self, exc_class, exc, traceback):
        try:
            self.connection.commit()
        except AttributeError: # isn't closable
            return True # exception handled successfully
        finally:
            self.cursor.close(); self.connection.close()
     
    def execute_query(self, query:str, params=()):
        if isinstance(params, list) and len(params) > 0 and isinstance(params[0], (list, tuple)): # Batch operation
            self.cursor.executemany(query, params)
            return self.cursor.rowcount # Return number of affected rows for batch INSERT/UPDATE/DELETE
        else: # Single operation
            self.cursor.execute(query, params)
            return self.cursor.fetchall() # Return result of a SELECT query; empty list [] for INSERT/UPDATE/DELETE

def execute(db_path:str, query:str, params=()):
    with SQLiteX33(db_path) as db:
        return db.execute_query(query, params)
    

class DatabaseUtils:
    """
    Utility class for database operations related to flight tracking.
    
    This class provides methods for saving, loading, and updating flight data, airport information, and airline details 
    in a SQLite database. It handles data enrichment, batch processing operations and manages the database schema.
    
    The database schema consists of three main tables:
    - flights: Stores flight tracking data including trail information
    - airport_data: Contains reference data for airports including coordinates
    - airline_data: Contains reference data for airline companies
    """
    
    # Initialize tables for the database
    db_tables = [
        """CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT UNIQUE,
            callsign TEXT,
            tail_no TEXT,
            flight_no TEXT,
            aircraft_icao TEXT,
            aircraft TEXT,
            airline_icao TEXT,
            airline TEXT,
            origin_airport_iata TEXT,
            origin_city TEXT,
            destination_airport_iata TEXT,
            destination_city TEXT,
            destination_airport_coords TEXT,
            trail_data TEXT,
            trail_data_details TEXT,
            last_fetch_timestamp DATETIME,
            last_fetch_timestamp_details DATETIME,
            anomalies_detected BOOLEAN DEFAULT FALSE,
            anomaly_types TEXT,
            anomaly_details TEXT,
            anomaly_timestamp DATETIME
        );""",

        """CREATE TABLE IF NOT EXISTS airport_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            icao TEXT UNIQUE,
            iata TEXT,
            name TEXT,
            lat REAL,
            lng REAL,
            city TEXT,
            country TEXT,
            last_fetch_timestamp DATETIME      
        );""",

        """CREATE TABLE IF NOT EXISTS airline_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            icao TEXT UNIQUE,
            name TEXT,
            last_fetch_timestamp DATETIME
        );""",

        """CREATE TABLE IF NOT EXISTS flight_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT,
            pattern_type TEXT,
            pattern_confidence REAL,
            behavioral_features TEXT,
            analysis_timestamp DATETIME,
            pattern_discovery_method TEXT,
            FOREIGN KEY (flight_id) REFERENCES flights(flight_id) ON DELETE CASCADE,
            UNIQUE(flight_id, pattern_discovery_method)
        );""",

        """CREATE INDEX IF NOT EXISTS idx_flight_patterns_flight_id ON flight_patterns(flight_id);""",
        """CREATE INDEX IF NOT EXISTS idx_flight_patterns_pattern_type ON flight_patterns(pattern_type);""",


    ]
   
    @staticmethod
    def initialize_database(db_path):
        """
        Initialize the database by creating all required tables and indexes.
        
        :param db_path: Path to the SQLite database file
        """
        try:
            for table_sql in DatabaseUtils.db_tables:
                execute(db_path, table_sql)
            
            # Migration: Add anomaly columns to existing flights table if they don't exist
            try:
                # Check if anomaly columns exist
                existing_columns = execute(db_path, "PRAGMA table_info(flights)")
                existing_column_names = [col[1] for col in existing_columns] if existing_columns else []
                
                # Add missing anomaly columns
                anomaly_columns = [
                    ("anomalies_detected", "BOOLEAN DEFAULT FALSE"),
                    ("anomaly_types", "TEXT"),
                    ("anomaly_details", "TEXT"),
                    ("anomaly_timestamp", "DATETIME")
                ]
                
                for column_name, column_definition in anomaly_columns:
                    if column_name not in existing_column_names:
                        execute(db_path, f"ALTER TABLE flights ADD COLUMN {column_name} {column_definition}")
                        print(f"Added missing column '{column_name}' to flights table")
                        
            except Exception as migration_error:
                print(f"Warning: Could not migrate anomaly columns: {migration_error}")
                
        except Exception as e:
            print(f"Error initializing database: {e}")
   
    @staticmethod
    def load_flights_from_db(db_path, flight_ids=None):
        """
        Get flights from the database, optionally filtered by flight IDs.
        
        :param db_path: Path to the SQLite database file
        :param flight_ids (optional): List of flight IDs to filter by. If None, returns all flights.
        :return: list: List of dictionaries, each representing a flight with its data
        """
        # JSON field parsing helper func
        def _parse_json_db_field(row, field_name, default=None):
            try:
                # Check if field exists in row before accessing it
                if field_name not in row or row[field_name] is None:
                    return default
                return json.loads(row[field_name]) if row[field_name] else default
            except (json.JSONDecodeError, KeyError):
                return default

        # Query flights from the database
        if flight_ids:
            placeholders = ', '.join(['?'] * len(flight_ids)) # Create placeholders for SQL query
            rows = execute(db_path, f"SELECT * FROM flights WHERE flight_id IN ({placeholders})", flight_ids) # Query specific flights from the db
        else:
            rows = execute(db_path, "SELECT * FROM flights") # Query all flights from the db

        flights = []

        for row in rows:
            # Create a dict with all flight data directly from row keys (excluding the 'id' column)
            try:
                row_dict = dict(row)
                existing_flight = {key: value for key, value in row_dict.items() if key != 'id'}
            except Exception:
                # Fallback: create dictionary manually from row if dict conversion fails
                existing_flight = {}
                if hasattr(row, 'keys'):
                    for key in row.keys():
                        if key != 'id':
                            existing_flight[key] = row[key]
            
            # Process JSON fields - only process fields that exist in the row
            json_fields = ["destination_airport_coords", "trail_data", "trail_data_details", "anomaly_types", "anomaly_details"]
            for field in json_fields:
                if field in row_dict:  # Only process field if it exists in the database row
                    existing_flight[field] = _parse_json_db_field(row, field)
                else:
                    # Set default values for missing fields
                    if field in ["anomaly_types", "anomaly_details"]:
                        existing_flight[field] = [] if field == "anomaly_types" else {}
                    else:
                        existing_flight[field] = None

            # Add the processed flight to the flights list
            flights.append(existing_flight)

        return flights    
    
    @staticmethod
    def update_anomaly_fields(db_path, flight_id, anomalies_detected, anomaly_types, anomaly_details, anomaly_timestamp):
        """
        Update only the anomaly fields for a specific flight in the database.
        
        :param db_path: Path to the SQLite database
        :param flight_id: Flight ID to update
        :param anomalies_detected: Boolean indicating if anomalies were detected
        :param anomaly_types: List of anomaly types
        :param anomaly_details: Dictionary with anomaly details
        :param anomaly_timestamp: Timestamp of anomaly detection
        :return: True if update was successful, False otherwise
        """
        if not flight_id:
            return False
            
        try:
            # Serialize JSON fields
            anomaly_types_json = json.dumps(anomaly_types) if isinstance(anomaly_types, list) else anomaly_types
            anomaly_details_json = json.dumps(anomaly_details) if isinstance(anomaly_details, dict) else anomaly_details
            
            # Format timestamp
            if anomaly_timestamp and hasattr(anomaly_timestamp, 'strftime'):
                anomaly_timestamp_str = anomaly_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                anomaly_timestamp_str = anomaly_timestamp
            
            # Update only anomaly fields
            execute(db_path, 
                """UPDATE flights SET 
                   anomalies_detected = ?, 
                   anomaly_types = ?, 
                   anomaly_details = ?, 
                   anomaly_timestamp = ?
                   WHERE flight_id = ?""",
                (anomalies_detected, anomaly_types_json, anomaly_details_json, anomaly_timestamp_str, flight_id)
            )
            return True
        except Exception as e:
            print(f"Error updating anomaly fields for flight {flight_id}: {e}")
            return False
    
    @staticmethod
    def get_flights_with_details_fetched(db_path, max_age_minutes=6):
        """
        Return a list of flight_id's for flights where last_fetch_timestamp_details is not empty
        and the timestamp is less than max_age_minutes old.
                
        :param db_path: Path to the SQLite database
        :param max_age_minutes: Maximum age in minutes for a fetch to be considered valid (default: 6)
        :return list: List of flight IDs with recent detailed API data
        """

        def is_recent_timestamp(current_time, timestamp_str, max_age_minutes):
            """Helper function to check if a timestamp is recent"""
            try:
                time_diff = current_time - datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                return time_diff.total_seconds() < max_age_minutes * 60
            except (ValueError, TypeError):
                return False
            
        flights = DatabaseUtils.load_flights_from_db(db_path)
        current_time = datetime.now()
        
        # Filter flights with recent timestamps
        flight_ids = [flight["flight_id"] for flight in flights if flight["last_fetch_timestamp_details"] and 
                    is_recent_timestamp(current_time, flight["last_fetch_timestamp_details"], max_age_minutes)]
        
        return flight_ids            
    
    @staticmethod
    def save_flights_to_db(db_path, flight_list):
        """
        Save flight data to database.
            
        :param db_path: Path to the SQLite database
        :param flight_list: List of flight dictionaries to save
        :return int: Number of flight records saved to database
        """

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        saved_count = 0
        
        for flight in flight_list:
            flight_id = flight.get('flight_id')
            is_detailed = flight.get('api_details_fetch', False) # Check if detailed fetch was performed for this flight
            
            # Retrieve existing trail data from database
            existing_data = execute(db_path, "SELECT trail_data FROM flights WHERE flight_id = ?", (flight_id,))
            
            # Prepare all trail data (both new + old) - Removing duplicates if present and sorting newest trail first
            updated_trail_points = [flight.get('trail_data')] # Add the new trail point
            if existing_data and existing_data[0][0]:
                try:
                    old_points = json.loads(existing_data[0][0]) # existing trail points
                    for point in (old_points if isinstance(old_points, list) else [old_points]):
                        if point['ts'] != flight['trail_data']['ts']: # Skip point if it has same timestamp as new point (skipping duplicates)
                            updated_trail_points.append(point)
                    updated_trail_points.sort(key=lambda x: x['ts'], reverse=True) # Sort by timestamp descending (newest first)
                # except: pass # Ignore invalid data
                except Exception as parse_error:
                    print(f"Error parsing existing trail data for flight {flight_id}: {parse_error}")
           
            # Set processed values
            flight['trail_data'] = json.dumps(updated_trail_points[:6])
            flight['last_fetch_timestamp'] = current_time
            
            if is_detailed:
                flight['last_fetch_timestamp_details'] = current_time
                if flight.get('trail_data_details'):
                    flight['trail_data_details'] = json.dumps(flight['trail_data_details'])
                if flight.get('destination_airport_coords'):
                    flight['destination_airport_coords'] = json.dumps(flight['destination_airport_coords'])
            
            # Handle anomaly field serialization
            if flight.get('anomaly_types') and isinstance(flight['anomaly_types'], list):
                flight['anomaly_types'] = json.dumps(flight['anomaly_types'])
            if flight.get('anomaly_details') and isinstance(flight['anomaly_details'], dict):
                flight['anomaly_details'] = json.dumps(flight['anomaly_details'])
                
            # Clean up (remove keys which don't correspond to columns in db)
            if 'api_details_fetch' in flight: 
                del flight['api_details_fetch']

            # Dynamically generate SQL from flight dict keys - works because dict keys match column names 
            try:
                if is_detailed or not existing_data: # Insert / Replace so it works for both use cases (Detailed fetch / General fetch)
                    execute(db_path, 
                        f"INSERT OR REPLACE INTO flights ({','.join(flight.keys())}) VALUES ({','.join(['?']*len(flight))})",
                        list(flight.values()))
                    
                else: # Update using COALESCE to only change fields that have values
                    updates = [f"{k}=COALESCE(?,{k})" for k in flight if k != 'flight_id']
                    params = [flight[k] for k in flight if k != 'flight_id'] + [flight_id]
                    
                    if updates:
                        execute(db_path, f"UPDATE flights SET {','.join(updates)} WHERE flight_id=?", params)
            
                saved_count += 1

            except Exception as error:
                print(f"Unexpected error processing flight: {error}")
                print(f"Problematic flight data: {flight}")
                return 0    
        
        return saved_count
       
    @staticmethod
    def save_airport_data_to_db(db_path, airport_data_list):
        """
        Save airport data to database using batch processing.
            
        :param db_path: Path to the SQLite database
        :param airport_data_list: List of airport data dictionaries to save
        :return int: Number of airport records saved to database
        """
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Add timestamp to all records
            airport_data_list = [{**airport, 'last_fetch_timestamp': current_time} for airport in airport_data_list]
            
            # Ensure we have airports to process
            if not airport_data_list:
                return 0
                
            # Get columns from the first airport (assuming all have same structure)
            columns = ','.join(airport_data_list[0].keys())
            placeholders = ','.join(['?'] * len(airport_data_list[0]))
            
            # Create SQL statement
            sql = f"INSERT OR REPLACE INTO airport_data ({columns}) VALUES ({placeholders})"
            
            # Prepare parameter lists for each airport
            param_sets = [list(airport.values()) for airport in airport_data_list]
            
            # Execute as a batch operation
            saved_count = execute(db_path, sql, param_sets)
            
            return saved_count
            
        except Exception as e:
            print(f"Error during batch airport save: {e}")
            return 0

    @staticmethod
    def save_airline_data_to_db(db_path, airline_data_list):
        """
        Save airline data to database using batch processing.
       
        :param db_path: Path to the SQLite database
        :param airline_data_list: List of airline data dictionaries to save
        :return int: Number of airline records saved to database
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            
            # Add timestamp to all records
            airline_data_list = [{**airline, 'last_fetch_timestamp': current_time} for airline in airline_data_list]
            
            # Ensure we have airlines to process
            if not airline_data_list:
                return 0
                
            # Get columns from the first airline (assuming all have same structure)
            columns = ','.join(airline_data_list[0].keys())
            placeholders = ','.join(['?'] * len(airline_data_list[0]))
            
            # Create SQL statement
            sql = f"INSERT OR REPLACE INTO airline_data ({columns}) VALUES ({placeholders})"
            
            # Prepare parameter lists for each airline
            param_sets = [list(airline.values()) for airline in airline_data_list]
            
            # Execute as a batch operation
            saved_count = execute(db_path, sql, param_sets)
            
            return saved_count
            
        except Exception as e:
            print(f"Error during batch airline save: {e}")
            return 0
        
    @staticmethod
    def fetch_airport_city_data(db_path):
        """
        Fetch city information for airports that need it.
        
        :param db_path: Path to the SQLite database
        :return list: List of dictionaries with airport ID and city information
        """        
        # Load airport data with both IATA and ICAO codes as keys
        iata_airports = airportsdata.load('IATA')
        icao_airports = airportsdata.load('ICAO')
        
        # Get all airports that need city information
        airports = execute(db_path, "SELECT id, icao, iata FROM airport_data WHERE city IS NULL")
        
        if not airports: # o airports found needing city data
            return []
        
        # Create result list
        airport_city_data = []
        
        # Process each airport
        for airport in airports:
            city = None
            
            # Try to get data using ICAO code first (more reliable)
            if airport['icao'] and airport['icao'] in icao_airports:
                city = icao_airports[airport['icao']]['city']
            
            # If no city found and IATA code exists, try this
            if not city and airport['iata'] and airport['iata'] in iata_airports:
                city = iata_airports[airport['iata']]['city']
            
            # If city found, add to results
            if city:
                airport_city_data.append({
                    'id': airport['id'],
                    'city': city
                })
        
        return airport_city_data

    @staticmethod
    def save_airport_city_data_to_db(db_path, airport_city_data):
        """
        Save airport city info to database using batch processing.
        
        :param db_path: Path to the SQLite database
        :param airport_city_data: List of dictionaries with airport ID and city
        :return int: Number of airports updated
        """        
        try:
            # Ensure we have data to process
            if not airport_city_data:
                return 0
                
            # Prepare update parameters [city, id]
            param_sets = [[airport['city'], airport['id']] for airport in airport_city_data]
            
            # Execute batch update
            updated_count = execute(db_path, "UPDATE airport_data SET city = ? WHERE id = ?", param_sets)
            
            return updated_count
            
        except Exception as e:
            print(f"Error during batch airport city update: {e}")
            return 0
        
    @staticmethod
    def enrich_missing_flight_data_from_db(db_path, flight_list):
        """
        Enrich flight data with information from airport and airline database tables
        
        :param db_path: Path to the SQLite database
        :param flight_list: List of flight dictionaries to enrich
        :return list: List of enriched flight dictionaries
        """       
        # If no flights, return empty list
        if not flight_list:
            return []
        
        # Get all airline data as a dictionary for quick lookup
        airlines = execute(db_path, "SELECT icao, name FROM airline_data")
        airline_dict = {airline['icao']: airline['name'] for airline in airlines if airline['icao']}
        
        # Get all airport data as a dictionary for quick lookup
        airports = execute(db_path, "SELECT icao, iata, city, lat, lng FROM airport_data")
        airport_dict_by_iata = {airport['iata']: airport for airport in airports if airport['iata']}
        
        enriched_flight_list = []

        # Enrich each flight
        for flight in flight_list:

            original_flight = flight.copy()

            # Add airline name if missing in the flight data and available in our airline_data table
            if not flight.get('airline') and flight.get('airline_icao') and flight['airline_icao'] in airline_dict:
                flight['airline'] = airline_dict[flight['airline_icao']]
            
            # Add origin city if missing in the flight data and available in our airport_data table
            if not flight.get('origin_city') and flight.get('origin_airport_iata') and flight['origin_airport_iata'] in airport_dict_by_iata:
                origin_airport = airport_dict_by_iata[flight['origin_airport_iata']]
                flight['origin_city'] = origin_airport['city']

            # Add destination city if missing in the flight data and available in our airport_data table
            if not flight.get('destination_city') and flight.get('destination_airport_iata') and flight['destination_airport_iata'] in airport_dict_by_iata:
                dest_airport = airport_dict_by_iata[flight['destination_airport_iata']]
                flight['destination_city'] = dest_airport['city']
                
                # Add destination airport coordinates if missing in the flight data and available in our airport_data table
                if not flight.get('destination_airport_coords') and dest_airport['lat'] and dest_airport['lng']:
                    flight['destination_airport_coords'] = {"lat": dest_airport['lat'], "lng": dest_airport['lng']}

            # Only append if the flight was modified (enriched)
            if flight != original_flight:
                enriched_flight_list.append(flight)
        
        return enriched_flight_list

    @staticmethod
    def save_enriched_flights_to_db(db_path, flight_list):
        """
        Save enriched flight data to database, focusing on fields that come from enrichment.
        
        :param db_path: Path to the SQLite database
        :param flight_list: List of enriched flight dictionaries
        :return int: Number of flights updated with enrichment data
        """     
        try:
            # Ensure we have data to process
            if not flight_list:
                return 0
                
            # Prepare update parameters for each flight
            updates = []

            for flight in flight_list:

                # Only include flights that have at least one enriched field
                if any(field in flight for field in ['airline', 'origin_city', 'destination_city', 'destination_airport_coords']):
                    
                    # Prepare update parameters
                    params = []
                    
                    # Add parameters in the same order as the SQL query
                    params.append(flight.get('airline') or None)
                    params.append(flight.get('origin_city') or None)
                    params.append(flight.get('destination_city') or None)

                    # Convert destination_airport_coords to JSON string if needed
                    dest_coords = flight.get('destination_airport_coords')
                    if dest_coords is not None:
                        params.append(json.dumps(dest_coords) if isinstance(dest_coords, dict) else dest_coords)
                    else:
                        params.append(None)

                    params.append(flight.get('flight_id'))
                    
                    updates.append(params)
            
            # Execute batch update
            if updates:
                updated_count = execute(db_path, """
                    UPDATE flights SET 
                        airline = COALESCE(?, airline),
                        origin_city = COALESCE(?, origin_city),
                        destination_city = COALESCE(?, destination_city),
                        destination_airport_coords = COALESCE(?, destination_airport_coords)
                    WHERE flight_id = ?
                """, updates)
                
                return updated_count
                
            return 0
            
        except Exception as e:
            print(f"Error during flight enrichment update: {e}")
            return 0
        
    @staticmethod
    def is_reference_data_refresh_needed(db_path):
        """
        Check if airport and airline reference data needs to be refreshed.
        
        :param db_path: Path to the SQLite database
        :return bool: True if no data exists or if the most recent fetch is older than time passed threshold
        """
        # Check latest fetch timestamp from both airport and airline tables
        latest_fetch_result = execute(db_path, """
            SELECT MAX(last_fetch_timestamp) AS latest_timestamp
            FROM (
                SELECT last_fetch_timestamp FROM airport_data
                UNION ALL
                SELECT last_fetch_timestamp FROM airline_data
            )
        """)
        latest_timestamp = latest_fetch_result[0][0] if latest_fetch_result and latest_fetch_result[0][0] else None
        
        # If no data exists in either table, we need to refresh
        if not latest_timestamp:
            return True

        try:
            latest_fetch_date = datetime.strptime(latest_timestamp, "%Y-%m-%d %H:%M:%S")
            time_passed_refresh_threshold = datetime.now() - timedelta(days=30) # Check if the most recent fetch is older than the time threshold

            return latest_fetch_date < time_passed_refresh_threshold
            
        except (ValueError, TypeError):
            # If there's any issue parsing the date, refresh to be safe
            return True

    @staticmethod
    def save_flight_patterns_to_db(db_path, pattern_data_list):
        """
        Save flight pattern analysis results to database using batch processing.
        
        :param db_path: Path to the SQLite database
        :param pattern_data_list: List of pattern data dictionaries to save
        :return int: Number of pattern records saved to database
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            if not pattern_data_list:
                return 0
            
            # Add timestamp and method to all records
            processed_patterns = []
            for pattern in pattern_data_list:
                processed_pattern = {
                    'flight_id': pattern.get('flight_id'),
                    'pattern_type': pattern.get('pattern_type'),
                    'pattern_confidence': pattern.get('pattern_confidence'),
                    'behavioral_features': json.dumps(pattern.get('behavioral_features', {})),
                    'analysis_timestamp': current_time,
                    'pattern_discovery_method': pattern.get('pattern_discovery_method', 'basic_classification')
                }
                processed_patterns.append(processed_pattern)
            
            # Prepare SQL for batch upsert (update on conflict)
            columns = ','.join(processed_patterns[0].keys())
            placeholders = ','.join(['?'] * len(processed_patterns[0]))
            update_columns = ', '.join([f"{col} = excluded.{col}" for col in processed_patterns[0].keys() if col not in ['id', 'flight_id', 'pattern_discovery_method']])
            sql_query = f"""INSERT INTO flight_patterns ({columns}) VALUES ({placeholders})
                           ON CONFLICT(flight_id, pattern_discovery_method) DO UPDATE SET
                           {update_columns}"""
            
            # Prepare parameter sets
            param_sets = [list(pattern.values()) for pattern in processed_patterns]
            
            # Execute batch operation with fallback for older SQLite versions
            try:
                saved_count = execute(db_path, sql_query, param_sets)
            except Exception as e:
                # Fallback to INSERT OR REPLACE for older SQLite versions
                fallback_sql = f"INSERT OR REPLACE INTO flight_patterns ({columns}) VALUES ({placeholders})"
                saved_count = execute(db_path, fallback_sql, param_sets)
            
            return saved_count
            
        except Exception as e:
            print(f"Error during batch pattern save: {e}")
            return 0
    
    @staticmethod
    def load_flight_patterns_from_db(db_path, flight_ids=None):
        """
        Retrieve pattern data from database with optional filtering by flight IDs.
        
        :param db_path: Path to the SQLite database
        :param flight_ids: Optional list of flight IDs to filter by
        :return: List of pattern data dictionaries
        """
        try:
            if flight_ids:
                placeholders = ', '.join(['?'] * len(flight_ids))
                rows = execute(db_path, f"SELECT * FROM flight_patterns WHERE flight_id IN ({placeholders})", flight_ids)
            else:
                rows = execute(db_path, "SELECT * FROM flight_patterns")
            
            patterns = []
            for row in rows:
                pattern_data = dict(row)
                # Parse JSON behavioral features
                try:
                    pattern_data['behavioral_features'] = json.loads(pattern_data['behavioral_features']) if pattern_data['behavioral_features'] else {}
                except json.JSONDecodeError:
                    pattern_data['behavioral_features'] = {}
                
                patterns.append(pattern_data)
            
            return patterns
            
        except Exception as e:
            print(f"Error loading flight patterns: {e}")
            return []
    
    @staticmethod
    def get_pattern_statistics(db_path):
        """
        Return pattern distribution statistics for analytics and UI display.
        
        :param db_path: Path to the SQLite database
        :return: Dictionary with pattern statistics
        """
        try:
            # Get pattern type distribution
            pattern_counts = execute(db_path, """
                SELECT pattern_type, COUNT(*) as count, AVG(pattern_confidence) as avg_confidence
                FROM flight_patterns 
                WHERE analysis_timestamp >= datetime('now', '-1 day')
                GROUP BY pattern_type
                ORDER BY count DESC
            """)
            
            # Get total patterns count
            total_result = execute(db_path, """
                SELECT COUNT(*) as total
                FROM flight_patterns 
                WHERE analysis_timestamp >= datetime('now', '-1 day')
            """)
            
            total_patterns = total_result[0]['total'] if total_result else 0
            
            # Format results
            statistics = {
                'total_patterns': total_patterns,
                'pattern_distribution': {row['pattern_type']: {
                    'count': row['count'],
                    'avg_confidence': round(row['avg_confidence'], 2) if row['avg_confidence'] else 0
                } for row in pattern_counts}
            }
            
            return statistics
            
        except Exception as e:
            print(f"Error getting pattern statistics: {e}")
            return {'total_patterns': 0, 'pattern_distribution': {}}
    
    @staticmethod
    def cleanup_old_patterns(db_path, days_threshold=7):
        """
        Remove pattern data for old flights, maintaining consistency with flight data cleanup.
        
        :param db_path: Path to the SQLite database
        :param days_threshold: Number of days to keep pattern data (default: 7)
        :return: Number of pattern records deleted
        """
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime("%Y-%m-%d %H:%M:%S")
            
            # Delete old pattern records
            deleted_count = execute(db_path, "DELETE FROM flight_patterns WHERE analysis_timestamp < ?", (cutoff_date,))
            
            return deleted_count
            
        except Exception as e:
            print(f"Error during cleanup of old patterns: {e}")
            return 0
    

    
    @staticmethod
    def enrich_flights_with_patterns(db_path, flight_list):
        """
        Merge pattern information with flight data during loading.
        
        :param db_path: Path to the SQLite database
        :param flight_list: List of flight dictionaries to enrich with pattern data
        :return: List of flight dictionaries with pattern information added
        """
        try:
            if not flight_list:
                return []
            
            # Get flight IDs for pattern lookup
            flight_ids = [flight.get('flight_id') for flight in flight_list if flight.get('flight_id')]
            
            if not flight_ids:
                return flight_list
            
            # Load patterns for these flights
            patterns = DatabaseUtils.load_flight_patterns_from_db(db_path, flight_ids)
            
            # Create pattern lookup dictionary
            pattern_dict = {pattern['flight_id']: pattern for pattern in patterns}
            
            # Enrich flights with pattern data
            enriched_flights = []
            for flight in flight_list:
                flight_copy = flight.copy()
                flight_id = flight.get('flight_id')
                
                if flight_id in pattern_dict:
                    pattern_data = pattern_dict[flight_id]
                    flight_copy.update({
                        'pattern_type': pattern_data.get('pattern_type'),
                        'pattern_confidence': pattern_data.get('pattern_confidence'),
                        'behavioral_features': pattern_data.get('behavioral_features', {}),
                        'pattern_analysis_timestamp': pattern_data.get('analysis_timestamp')
                    })
                else:
                    # Add default pattern data if no pattern analysis exists
                    flight_copy.update({
                        'pattern_type': None,
                        'pattern_confidence': None,
                        'behavioral_features': {},
                        'pattern_analysis_timestamp': None
                    })
                
                enriched_flights.append(flight_copy)
            
            return enriched_flights
            
        except Exception as e:
            print(f"Error enriching flights with patterns: {e}")
            return flight_list
    
    @staticmethod
    def cleanup_old_flights(db_path, days_threshold=7):
        """
        Delete flights older than specified days threshold and reset table indexing.
        Also cleans up associated pattern data.
        
        :param db_path: Path to SQLite database
        :param days_threshold: Number of days to keep data (default: 7)
        :return: int: Number of deleted flights
        """
        try:
            # Calculate the cutoff date (current time - days_threshold)
            cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime("%Y-%m-%d %H:%M:%S")
            
            # Clean up old patterns first
            DatabaseUtils.cleanup_old_patterns(db_path, days_threshold)
            

            
            # Delete old flights
            deleted_count = execute(db_path, "DELETE FROM flights WHERE last_fetch_timestamp < ?", (cutoff_date,))
            
            # Reset the indexing/AUTOINCR sequence for the flights table
            execute(db_path, "DELETE FROM sqlite_sequence WHERE name = 'flights'")
            
            return deleted_count
            
        except Exception as e:
            print(f"Error during cleanup of old flights: {e}")
            return 0

    @staticmethod
    def get_recent_anomalies(db_path, hours_threshold=24):
        """
        Query flights with anomalies detected within specified time window.
        
        :param db_path: Path to the SQLite database
        :param hours_threshold: Maximum age in hours for anomalies to be considered recent
        :return list: List of flight dictionaries with recent anomalies
        """
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours_threshold)
            cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")
            
            rows = execute(db_path, 
                "SELECT * FROM flights WHERE anomalies_detected = 1 AND anomaly_timestamp >= ?", 
                (cutoff_str,))
            
            flights_with_anomalies = []
            for row in rows:
                flight_dict = {key: value for key, value in dict(row).items() if key != 'id'}
                
                # Parse JSON fields
                json_fields = ["destination_airport_coords", "trail_data", "trail_data_details", "anomaly_types", "anomaly_details"]
                for field in json_fields:
                    try:
                        flight_dict[field] = json.loads(row[field]) if row[field] else None
                    except (json.JSONDecodeError, TypeError):
                        flight_dict[field] = None
                
                flights_with_anomalies.append(flight_dict)
                
            return flights_with_anomalies
            
        except Exception as e:
            print(f"Error retrieving recent anomalies: {e}")
            return []

    @staticmethod
    def get_anomaly_statistics(db_path, hours_threshold=24):
        """
        Return counts and distribution of anomaly types for dashboard display.
        
        :param db_path: Path to the SQLite database
        :param hours_threshold: Maximum age in hours for anomalies to include in statistics
        :return dict: Dictionary with anomaly statistics
        """
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours_threshold)
            cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Get all flights with anomalies
            rows = execute(db_path, 
                "SELECT anomaly_types FROM flights WHERE anomalies_detected = 1 AND anomaly_timestamp >= ?", 
                (cutoff_str,))
            
            if not rows:
                return {
                    'total_anomalies': 0,
                    'bearing_anomalies': 0,
                    'altitude_anomalies': 0,
                    'timing_anomalies': 0,
                    'multiple_anomalies': 0
                }
            
            # Count anomaly types
            bearing_count = altitude_count = timing_count = multiple_count = 0
            total_flights_with_anomalies = len(rows)
            
            for row in rows:
                try:
                    anomaly_types = json.loads(row[0]) if row[0] else []
                    if isinstance(anomaly_types, list):
                        if len(anomaly_types) > 1:
                            multiple_count += 1
                        if 'bearing_anomaly' in anomaly_types:
                            bearing_count += 1
                        if 'altitude_anomaly' in anomaly_types:
                            altitude_count += 1
                        if 'timing_anomaly' in anomaly_types:
                            timing_count += 1
                except (json.JSONDecodeError, TypeError):
                    continue
            
            return {
                'total_anomalies': total_flights_with_anomalies,
                'bearing_anomalies': bearing_count,
                'altitude_anomalies': altitude_count,
                'timing_anomalies': timing_count,
                'multiple_anomalies': multiple_count
            }
            
        except Exception as e:
            print(f"Error retrieving anomaly statistics: {e}")
            return {
                'total_anomalies': 0,
                'bearing_anomalies': 0,
                'altitude_anomalies': 0,
                'timing_anomalies': 0,
                'multiple_anomalies': 0
            }


