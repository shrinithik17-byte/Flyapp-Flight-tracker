# Built-in libraries
import os
import time
import math
from math import exp
import json
import pandas as pd
from pathlib import Path
import configparser
from datetime import datetime, timedelta, timezone
import asyncio
import sqlite3
import logging

# Third-party libraries -> requirements.txt
from FlightRadarAPI import FlightRadar24API
import reverse_geocode
from haversine import haversine, Unit
from geopy.distance import geodesic
from geopy import Point
import folium
from folium.plugins import MarkerCluster
from tqdm import tqdm
from unidecode import unidecode
import numpy as np
try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    KMeans = None
    StandardScaler = None

# Custom made libraries
import sql_utils as sql



class Utils:

    # Expose sklearn availability flag as class attribute
    SKLEARN_AVAILABLE = SKLEARN_AVAILABLE
    
    LOG_TS = None
    LOG_RAW = None

    @staticmethod 
    def setup_logging(log_filename, level=logging.DEBUG):
        """
        Configure application logging with timestamp and raw logging capabilities.
        
        :param log_filename: Path to the log file
        :param level: Logging level (default: logging.DEBUG)
        :return: None, but sets Utils.LOG_TS and Utils.LOG_RAW class attributes
        """
        # Clear any existing handlers
        logging.getLogger().handlers = []
        
        # Create a file handler with UTF-8 encoding
        handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Configure the root logger
        logger = logging.getLogger()
        logger.setLevel(level)
        logger.addHandler(handler)
        
        # Function to log with timestamp format
        def log_with_timestamp(message):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"{timestamp} - {message}")
        
        # Function to log raw message
        def log_raw(message):
            logger.debug(message)

        # Store these functions as class attributes
        Utils.LOG_TS = log_with_timestamp
        Utils.LOG_RAW = log_raw

    @staticmethod 
    def print_main_header():
        """Display styled ASCII art header in the terminal."""

        clear_terminal = "cls" if os.name == "nt" else "clear" # "nt" (windows), "posix" (linux/mac)
        os.system(clear_terminal)

        # Explicitly move cursor to top-left corner
        print("\033[H\033[J", end="")

        print("\033[38;5;133m") # Setting a new color for the header

        ascii_header = f'''
░█▀▀░█░░░█░█░█▀▄░█░█░▀▀█░▀▀█
░█▀▀░█░░░░█░░█▀▄░░█░░░▀▄░░▀▄
░▀░░░▀▀▀░░▀░░▀▀░░░▀░░▀▀░░▀▀░
© 2025 Hodel33'''
        
        ascii_header = ascii_header.strip()
        print(ascii_header)
        
        print(f"\033[0;0m") # resets the color back to default

    @staticmethod
    def get_custom_colors():
        """Return dictionary of custom color theme values used throughout the application."""
        return {
            "plane_color": "#C9EEFF", # Light blue
            "plane_color_low_alt": "#6AA0C0", # Medium-dark blue
            "map_feat_color": "#2a729f",
            "popup_bg_color": "#142c3bE6", # hex color code + ~90% transparency
            "orange_color": "#F39C12"
        }

    @staticmethod    
    def get_css_custom_map(map_feat_color, popup_bg_color, orange_color):
        """Returns the custom CSS string used for Folium customization"""
        return f"""
        <style>

        .leaflet-control-attribution {{
            background-color: #1a1a1a !important;
            color: #535353 !important;
            border-radius: 3px !important;                       /* Rounded corners */
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5) !important;
        }}

        .leaflet-control-attribution a {{
            color: {map_feat_color} !important;
            text-decoration: none;
        }}

        /* Override the default Leaflet popup content wrapper */
        .leaflet-popup-content-wrapper {{
            background-color: {popup_bg_color} !important; /* Dark slate background with high opacity */
            color: #ECF0F1 !important;                            /* Light gray font color for readability */
            border-radius: 7px !important;                       /* Rounded corners */
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5) !important; 
        }}

        /* Override the default Leaflet popup tip */
        .leaflet-popup-tip {{
            background-color: {popup_bg_color} !important; /* Match the popup background */
        }}

        /* Style specific elements within the popup */
        .custom-popup-content b {{
            color: {orange_color}; /* Specific color for bold labels */
        }}
        
        .custom-popup-content {{
            padding: 10px;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 14px;
        }}

        /* Style the popup close "×" button */
        .leaflet-popup-close-button {{
            color: #FFF !important;
            transform: translate(-3px, 3px); 
        }}    

        </style>
        """

    @staticmethod
    def load_and_validate_config(config_file="config.ini"):
        """Load and validate application configuration from a config file."""
        config = configparser.ConfigParser()

        # Check if the config file exists
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file {config_file} not found")

        config.read(config_file)

        # Load values as strings
        origin_location_coords = config.get('Settings', 'location_coords') # Coordinates for the location
        origin_radius_km = config.get('Settings', 'location_radius') # Radius of the area to track flights, in km
        auto_refresh_interval = config.get('Settings', 'auto_refresh_interval', fallback='0') # Auto refresh interval in seconds

        # Check Origin location_coords
        try:
            latitude, longitude = map(float, origin_location_coords.split(','))
            origin_location_coords = (latitude, longitude)  # Convert to tuple of floats
        except ValueError:
            raise ValueError("Invalid origin location coordinates in config (must be in the format 'latitude, longitude')")

        # Check and Save location_radius - only allow 50, 100, 150, or 200
        try:
            origin_radius_km = int(origin_radius_km)
            if origin_radius_km not in [50, 100, 150, 200]:
                raise ValueError
            origin_radius_m = origin_radius_km * 1000 # Convert to meters
        except ValueError:
            raise ValueError("Invalid location radius in config (must be 50, 100, 150, or 200)")
        
        # Check and Save auto_refresh_interval - only allow 0, 15, 30, or 60
        try:
            auto_refresh_interval = int(auto_refresh_interval)
            if auto_refresh_interval not in [0, 15, 30, 60]:
                raise ValueError
        except ValueError:
            raise ValueError("Invalid auto refresh interval in config (must be 0, 15, 30, or 60)")

        # Load ignore_airport_proximity
        ignore_airport_proximity = config.getboolean('Settings', 'ignore_airport_proximity', fallback=False)  # Default to False if not present

        # Load debug_mode
        debug_mode = config.getboolean('Settings', 'debug_mode', fallback=False)  # Default to False if not present

        # Load anomaly detection settings
        bearing_threshold = config.getfloat('AnomalyDetection', 'bearing_threshold', fallback=30.0)
        altitude_threshold = config.getfloat('AnomalyDetection', 'altitude_threshold', fallback=1000.0)
        timing_threshold = config.getfloat('AnomalyDetection', 'timing_threshold', fallback=3.0)
        auto_detection_enabled = config.getboolean('AnomalyDetection', 'auto_detection_enabled', fallback=True)
        detection_mode = config.get('AnomalyDetection', 'detection_mode', fallback='auto')

        # Validate anomaly detection thresholds
        if not (10 <= bearing_threshold <= 90):
            bearing_threshold = 30.0
        if not (500 <= altitude_threshold <= 3000):
            altitude_threshold = 1000.0
        if not (1 <= timing_threshold <= 10):
            timing_threshold = 3.0
        if detection_mode not in ['auto', 'manual']:
            detection_mode = 'auto'

        anomaly_config = {
            'bearing_threshold': bearing_threshold,
            'altitude_threshold': altitude_threshold,
            'timing_threshold': timing_threshold,
            'auto_detection_enabled': auto_detection_enabled,
            'detection_mode': detection_mode
        }

        return origin_location_coords, origin_radius_m, auto_refresh_interval, ignore_airport_proximity, debug_mode, anomaly_config
    
    @staticmethod
    def get_nested(data, path, default=None):
        """Safely access nested dictionary values using dot notation path."""
        keys = path.split('.')
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key, default)
                if data is None or data == '':
                    return default
            else:
                return default
        return data

    @staticmethod
    def knots_to_kmph(knots):
        """Convert knots to km/h, rounded to nearest integer."""
        return round(knots * 1.852)

    @staticmethod
    def feet_to_meters(feet):
        """Convert feet to meters, rounded to nearest integer."""
        return round(feet * 0.3048)

    @staticmethod
    def calculate_distance(coord1, coord2):
        """Calculate distance between two coordinates using the Haversine formula.
        
        :param coord1: First coordinate tuple (latitude, longitude)
        :param coord2: Second coordinate tuple (latitude, longitude)
        :return: Distance in kilometers, rounded to nearest integer
        """
        distance = haversine(coord1, coord2, unit=Unit.KILOMETERS)
        return round(distance)
    
    @staticmethod
    def calculate_bearing(pointA, pointB):
        """
        Calculates the bearing from pointA to pointB.

        :param pointA: Tuple of (latitude, longitude) for the starting point.
        :param pointB: Tuple of (latitude, longitude) for the destination point.
        :return: Bearing in degrees from pointA to pointB.
        """
        lat1 = math.radians(pointA[0])
        lat2 = math.radians(pointB[0])
        diffLong = math.radians(pointB[1] - pointA[1])

        x = math.sin(diffLong) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
                * math.cos(lat2) * math.cos(diffLong))

        initial_bearing = math.atan2(x, y)
        initial_bearing = math.degrees(initial_bearing)
        compass_bearing = (initial_bearing + 360) % 360

        return compass_bearing

    @staticmethod
    def calculate_destination(point, bearing, distance_km):
        """
        Calculates the destination point given start point, bearing, and distance.

        :param point: Tuple of (latitude, longitude) for the starting point.
        :param bearing: Bearing in degrees.
        :param distance_km: Distance in kilometers.
        :return: Tuple of (latitude, longitude) for the destination point.
        """
        destination = geodesic(kilometers=distance_km).destination(Point(point[0], point[1]), bearing)
        return (destination.latitude, destination.longitude)
    
    @staticmethod
    def is_plane_heading_towards_origin(plane_loc, heading, origin_loc, max_bearing_diff=90):
        """
        Determines if the plane is heading towards the origin within a specified bearing difference.

        :param plane_loc: Tuple of (latitude, longitude) for the plane's current location.
        :param heading: The plane's current heading in degrees.
        :param origin: Tuple of (latitude, longitude) for the origin location.
        :param max_bearing_diff: Maximum allowed difference in degrees between the plane's heading and the bearing to the origin.
        :return: Boolean indicating if the plane is heading towards the origin.
        """
        bearing_to_origin = Utils.calculate_bearing(plane_loc, origin_loc)
        bearing_difference = abs(bearing_to_origin - heading)
        bearing_difference = min(bearing_difference, 360 - bearing_difference)  # Normalize to [0, 180]

        return bearing_difference <= max_bearing_diff

    @staticmethod
    def will_plane_pass_within_radius(plane_loc, heading, origin_loc, radius_km=10):
        """
        Determines if the plane's path will pass within a specified radius of the origin.

        :param plane_loc: Tuple of (latitude, longitude) for the plane's current location.
        :param heading: The plane's current heading in degrees.
        :param origin: Tuple of (latitude, longitude) for the origin location.
        :param radius_km: The radius in kilometers within which the plane should pass.
        :return: Boolean indicating if the plane's path will pass within the radius of the origin.
        """
        # Earth's radius in kilometers
        R = 6371.0

        # Calculate angular distance between plane and origin
        delta13 = geodesic(plane_loc, origin_loc).kilometers / R

        # Convert bearings to radians
        theta13 = math.radians(Utils.calculate_bearing(plane_loc, origin_loc))
        theta12 = math.radians(heading)

        # Calculate cross-track distance
        delta_theta = theta13 - theta12
        delta_xt = math.asin(math.sin(delta13) * math.sin(delta_theta))
        cross_track_distance = abs(delta_xt * R)

        return cross_track_distance <= radius_km

    @staticmethod
    def get_flyby_info(plane_loc, heading, origin_loc):
        """
        Calculates the flyby distance and direction.

        :param plane_loc: Tuple of (latitude, longitude) for the plane's current location.
        :param heading: The plane's current heading in degrees.
        :param origin_loc: Tuple of (latitude, longitude) for the origin location.
        :return: A string in the format "X km - Y° DIR".
        """
        # Earth's radius in kilometers
        R = 6371.0

        # Calculate distance between plane and origin using Haversine formula
        d13 = Utils.calculate_distance(plane_loc, origin_loc)  # in km

        if d13 == 0:
            # Plane is at the origin
            return "0 km N/A°"

        # Calculate bearing from plane to origin
        bearing_to_origin = Utils.calculate_bearing(plane_loc, origin_loc)  # in degrees
        theta13 = math.radians(bearing_to_origin)  # Convert to radians

        # Convert heading to radians
        theta12 = math.radians(heading)

        # Angular distance
        delta13 = d13 / R  # in radians

        # Cross-track distance calculation
        cross_track_angle = math.sin(delta13) * math.sin(theta13 - theta12)
        # Clamp the value to [-1, 1] to avoid math domain errors
        cross_track_angle = max(-1.0, min(1.0, cross_track_angle))
        d_xt = math.asin(cross_track_angle) * R
        # Preserve the sign to determine side
        # Positive d_xt: origin is to the left of the path
        # Negative d_xt: origin is to the right of the path

        # Along-track distance calculation
        cos_delta_at = math.cos(delta13) / math.cos(cross_track_angle)
        # Clamp the value to [-1, 1] to avoid math domain errors
        cos_delta_at = max(-1.0, min(1.0, cos_delta_at))
        delta_at = math.acos(cos_delta_at)
        d_at = delta_at * R  # in km

        # Calculate flyby point by moving d_at km along heading from plane_loc
        try:
            destination = geodesic(kilometers=d_at).destination(Point(plane_loc[0], plane_loc[1]), heading)
            flyby_point = (destination.latitude, destination.longitude)
        except Exception as e:
            return f"{round(abs(d_xt))} km N/A°"

        # Calculate bearing from origin to flyby point
        bearing_origin_to_flyby = Utils.calculate_bearing(origin_loc, flyby_point)
        compass_dir = Utils.bearing_to_compass(bearing_origin_to_flyby)

        # Round distance and bearing for readability
        d_xt = round(abs(d_xt))
        bearing_origin_to_flyby = int(bearing_origin_to_flyby)

        # Format the flyby info string
        flyby_info = f"{d_xt} km {compass_dir} ({bearing_origin_to_flyby}°)"

        return flyby_info

    @staticmethod
    def bearing_to_compass(bearing):
        """
        Converts a bearing in degrees to a 2-character compass direction.

        :param bearing: Bearing in degrees.
        :return: Compass direction as a string (e.g., 'N', 'NE', 'E', etc.).
        """
        dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        ix = int((bearing + 22.5) / 45) % 8
        return dirs[ix]

    @staticmethod
    def truncate_string(string, max_length=20):
        """Shorten string to specified maximum length, appending '..' if truncated."""
        if pd.isnull(string):
            return string
        if len(string) > max_length:
            return string[:max_length - 1] + '..'
        else:
            return string

    @staticmethod
    def calculate_straight_heading_chance(trails, max_average_change=20):
        """
        Calculates the percentage chance that the aircraft is maintaining a straight heading
        using a weighted average where recent changes have more weight.
        
        :param trails: List of trail elements.
        :param max_average_change: Maximum average heading change (in degrees) for which the aircraft 
        is considered to be possibly maintaining a straight heading (0 probability at or beyond this value).
        :return: Percentage chance of straight heading (0 to 1).
        """
        changes = []
        weights_exp = [] # Exponential weights
        total_trails = len(trails)
        
        for i in range(len(trails) - 1):
            hd1 = trails[i].get('hd')
            hd2 = trails[i + 1].get('hd')
            if hd1 is not None and hd2 is not None:
                diff = abs(hd1 - hd2)
                diff = min(diff, 360 - diff) # Handle compass wrap-around (e.g. a turn from 358° to 2° is a 4° change, not 356°)
                changes.append(diff)
                
                # Add Exponential Weighting - Assign exponentially higher weight to more recent changes
                weights_exp_base = 1
                weights_exp.append(exp(weights_exp_base * (total_trails - i))) 
        
        if not changes:
            return 0 # Not enough data to determine
           
        # Calculate Exponential Weighted Average
        weighted_sum_exp = sum(change * weight for change, weight in zip(changes, weights_exp))
        total_weight_exp = sum(weights_exp)
        weighted_avg_change_exp = weighted_sum_exp / total_weight_exp if total_weight_exp != 0 else 0
            
        # Calculate Exponential Weighted Percentage Chance
        straight_heading_chance = max(0, min(1, 1 - (weighted_avg_change_exp / max_average_change)))
        
        return straight_heading_chance
            

    @staticmethod
    def calculate_flyby_chance(trails, distance_to_origin, origin_radius_km, flyby_radius_km, speed_kmh, max_average_change=10):
        """
        Calculates the flyby chance based on proximity, heading stability, and speed.

        :param trails: List of trail elements.
        :param distance_to_origin: Distance from the plane to the origin location in km.
        :param flyby_radius_km: Radius defining the immediate flyby area around the origin in km (e.g. 10 km).
        :param origin_radius_km: Radius of the monitored region from the origin location in km (e.g. 200 km).
        :param speed_kmh: The speed of the aircraft in km/h.
        :param max_average_change: The average heading change (in degrees) for which the aircraft is considered to be 
        possibly maintaining a straight heading (0% chance at or beyond this value).
        :return: Tuple of (flyby_chance, flyby_chance_debug) where flyby_chance is a probability between 0 and 1, 
        and flyby_chance_debug is a formatted string with percentage and contributing factors.
        """

        if distance_to_origin <= flyby_radius_km:
            # Plane is within the flyby radius, flyby chance is 1 (100%)
            flyby_chance = 1
            proximity_factor = "-"
            straight_heading_chance = "-"
            speed_factor = "-"

        else:
            # Proximity decreases from 1 to 0 as distance increases from flyby_radius to origin_radius
            proximity_factor = 1 - ((distance_to_origin - flyby_radius_km) / (origin_radius_km - flyby_radius_km))
            proximity_factor = max(0.1, min(1, proximity_factor))  # Ensure proximity is between 0.1 and 1

            default_min_heading_chance = 0.3 # Default minimum value for straight heading chance (uncertain / highly variable headings data)

            # Calculate the straight heading chance (default to 0.3 if not enough trail points for calculation)
            if trails and len(trails) > 1:
                straight_heading_chance = Utils.calculate_straight_heading_chance(trails, max_average_change)
            else:
                straight_heading_chance = default_min_heading_chance # Default to 0.3 when insufficient trail points exist
            
            # Ensure the calculated heading chance stays between our minimum threshold (0.3) and 1
            # Apply minimum threshold of 0.3 to ensure even variable headings have some contribution
            straight_heading_chance = max(default_min_heading_chance, min(1, straight_heading_chance))

            # Normalize the speed
            min_speed = 200  # km/h
            max_speed = 700  # km/h
            speed_factor = (speed_kmh - min_speed) / (max_speed - min_speed)
            speed_factor = max(0.1, min(1, speed_factor))

            # Combine proximity, heading and speed with specified weights
            proximity_weight = 0.6
            heading_weight = 0.25
            speed_weight = 0.15

            flyby_chance = (
                (proximity_factor * proximity_weight) +
                (straight_heading_chance * heading_weight) +
                (speed_factor * speed_weight)
            )

            # Ensure the result is between 0 and 1
            flyby_chance = max(0, min(1, flyby_chance))

            proximity_factor = f"{proximity_factor:.1f}"
            straight_heading_chance = f"{straight_heading_chance:.1f}"
            speed_factor = f"{speed_factor:.1f}"

        flyby_chance_perc_for_info = int(round(flyby_chance * 100))
        flyby_chance_debug = f"{flyby_chance_perc_for_info} % (P{proximity_factor} H{straight_heading_chance} S{speed_factor})"

        return flyby_chance, flyby_chance_debug

    @staticmethod
    def extract_behavior_features(trail_data):
        """
        Extract behavioral metrics from flight trail data.
        
        :param trail_data: List of trail dictionaries with position/heading/speed data
        :return: Dictionary of behavioral features
        """
        if not trail_data or len(trail_data) < 2:
            return {
                'turn_frequency': 0,
                'altitude_variance': 0,
                'speed_consistency': 0,
                'path_circularity': 0,
                'climb_descent_ratio': 0,
                'heading_stability': 0
            }
        
        # Calculate turn frequency
        heading_changes = []
        altitude_changes = []
        speed_changes = []
        
        altitude_deltas = []  # Signed deltas for climb/descent calculation
        
        for i in range(len(trail_data) - 1):
            curr = trail_data[i]
            next_point = trail_data[i + 1]
            
            # Heading changes
            if curr.get('hd') is not None and next_point.get('hd') is not None:
                hd_diff = abs(curr['hd'] - next_point['hd'])
                hd_diff = min(hd_diff, 360 - hd_diff)  # Handle wraparound
                heading_changes.append(hd_diff)
            
            # Altitude changes (signed delta: newer - older)
            if curr.get('alt') is not None and next_point.get('alt') is not None:
                altitude_delta = next_point['alt'] - curr['alt']
                altitude_deltas.append(altitude_delta)
                altitude_changes.append(abs(altitude_delta))
            
            # Speed changes
            if curr.get('spd') is not None and next_point.get('spd') is not None:
                speed_changes.append(abs(curr['spd'] - next_point['spd']))
        
        # Calculate features
        turn_frequency = np.mean(heading_changes) if heading_changes else 0
        altitude_variance = np.var([p.get('alt', 0) for p in trail_data if p.get('alt') is not None])
        speed_consistency = 1 / (1 + np.std(speed_changes)) if speed_changes else 0
        
        # Path circularity (simplified - checks if start and end are close)
        path_circularity = 0
        if len(trail_data) >= 3:
            start_point = trail_data[-1]  # Oldest
            end_point = trail_data[0]     # Newest
            if (start_point.get('lat') and start_point.get('lng') and 
                end_point.get('lat') and end_point.get('lng')):
                distance = Utils.calculate_distance(
                    (start_point['lat'], start_point['lng']),
                    (end_point['lat'], end_point['lng'])
                )
                path_circularity = 1 / (1 + distance) if distance > 0 else 1
        
        # Climb/descent ratio
        climb_descent_ratio = 0
        if altitude_deltas:
            climbs = sum(1 for delta in altitude_deltas if delta > 100)  # >100ft climbs
            descents = sum(1 for delta in altitude_deltas if delta < -100)  # >100ft descents
            total_changes = climbs + descents
            climb_descent_ratio = abs(climbs - descents) / total_changes if total_changes > 0 else 0
        
        # Heading stability
        heading_stability = 1 / (1 + turn_frequency) if turn_frequency > 0 else 1
        
        return {
            'turn_frequency': turn_frequency,
            'altitude_variance': altitude_variance,
            'speed_consistency': speed_consistency,
            'path_circularity': path_circularity,
            'climb_descent_ratio': climb_descent_ratio,
            'heading_stability': heading_stability
        }
    
    @staticmethod
    def detect_circular_pattern(trail_data):
        """
        Detect circular flight patterns.
        
        :param trail_data: List of trail dictionaries
        :return: Tuple of (is_circular, confidence)
        """
        if not trail_data or len(trail_data) < 4:
            return False, 0.0
        
        features = Utils.extract_behavior_features(trail_data)
        
        # Circular patterns have high path circularity and consistent turns
        circularity_score = features['path_circularity']
        turn_consistency = 1 / (1 + abs(features['turn_frequency'] - 15))  # Ideal ~15° turns
        
        # Check for consistent heading changes (indicating turns)
        heading_changes = []
        for i in range(len(trail_data) - 1):
            curr = trail_data[i]
            next_point = trail_data[i + 1]
            if curr.get('hd') is not None and next_point.get('hd') is not None:
                hd_diff = curr['hd'] - next_point['hd']
                # Normalize to [-180, 180]
                if hd_diff > 180:
                    hd_diff -= 360
                elif hd_diff < -180:
                    hd_diff += 360
                heading_changes.append(hd_diff)
        
        # Check for consistent turn direction
        direction_consistency = 0
        if heading_changes:
            positive_changes = sum(1 for hc in heading_changes if hc > 5)
            negative_changes = sum(1 for hc in heading_changes if hc < -5)
            total_significant = positive_changes + negative_changes
            if total_significant > 0:
                direction_consistency = max(positive_changes, negative_changes) / total_significant
        
        confidence = (circularity_score * 0.4 + turn_consistency * 0.3 + direction_consistency * 0.3)
        is_circular = confidence > 0.6
        
        return is_circular, confidence
    
    @staticmethod
    def detect_linear_pattern(trail_data):
        """
        Detect linear/direct flight patterns.
        
        :param trail_data: List of trail dictionaries
        :return: Tuple of (is_linear, confidence)
        """
        if not trail_data or len(trail_data) < 3:
            return False, 0.0
        
        features = Utils.extract_behavior_features(trail_data)
        
        # Linear patterns have high heading stability and low turn frequency
        heading_stability = features['heading_stability']
        low_turn_score = 1 / (1 + features['turn_frequency'] / 5)  # Penalize high turn frequency
        
        # Check path straightness
        path_straightness = 0
        if len(trail_data) >= 3:
            start_point = trail_data[-1]  # Oldest
            end_point = trail_data[0]     # Newest
            
            if (start_point.get('lat') and start_point.get('lng') and 
                end_point.get('lat') and end_point.get('lng')):
                # Calculate direct distance vs path distance
                direct_distance = Utils.calculate_distance(
                    (start_point['lat'], start_point['lng']),
                    (end_point['lat'], end_point['lng'])
                )
                
                # Calculate path distance (sum of segments)
                path_distance = 0
                for i in range(len(trail_data) - 1):
                    curr = trail_data[i]
                    next_point = trail_data[i + 1]
                    if (curr.get('lat') and curr.get('lng') and 
                        next_point.get('lat') and next_point.get('lng')):
                        segment_dist = Utils.calculate_distance(
                            (curr['lat'], curr['lng']),
                            (next_point['lat'], next_point['lng'])
                        )
                        path_distance += segment_dist
                
                if path_distance > 0:
                    path_straightness = direct_distance / path_distance
        
        confidence = (heading_stability * 0.4 + low_turn_score * 0.3 + path_straightness * 0.3)
        is_linear = confidence > 0.7
        
        return is_linear, confidence
    
    @staticmethod
    def detect_erratic_pattern(trail_data):
        """
        Detect erratic/irregular flight patterns.
        
        :param trail_data: List of trail dictionaries
        :return: Tuple of (is_erratic, confidence)
        """
        if not trail_data or len(trail_data) < 3:
            return False, 0.0
        
        features = Utils.extract_behavior_features(trail_data)
        
        # Erratic patterns have high variance in multiple metrics
        high_turn_score = min(1.0, features['turn_frequency'] / 20)  # Normalize to [0,1]
        high_altitude_variance = min(1.0, features['altitude_variance'] / 10000)  # Normalize
        low_speed_consistency = 1 - features['speed_consistency']
        low_heading_stability = 1 - features['heading_stability']
        
        confidence = (high_turn_score * 0.3 + high_altitude_variance * 0.2 + 
                     low_speed_consistency * 0.25 + low_heading_stability * 0.25)
        is_erratic = confidence > 0.6
        
        return is_erratic, confidence
    
    @staticmethod
    def classify_basic_pattern(trail_data):
        """
        Classify flight pattern using basic detection methods.
        
        :param trail_data: List of trail dictionaries
        :return: Tuple of (pattern_type, confidence)
        """
        if not trail_data or len(trail_data) < 2:
            return "insufficient_data", 0.0
        
        # Run all pattern detectors
        is_circular, circular_conf = Utils.detect_circular_pattern(trail_data)
        is_linear, linear_conf = Utils.detect_linear_pattern(trail_data)
        is_erratic, erratic_conf = Utils.detect_erratic_pattern(trail_data)
        
        # Determine the strongest pattern
        patterns = [
            ("circular", circular_conf if is_circular else 0),
            ("linear", linear_conf if is_linear else 0),
            ("erratic", erratic_conf if is_erratic else 0)
        ]
        
        # Sort by confidence
        patterns.sort(key=lambda x: x[1], reverse=True)
        best_pattern, best_confidence = patterns[0]
        
        # If no pattern has sufficient confidence, classify as "normal"
        if best_confidence < 0.5:
            return "normal", 0.5
        
        return best_pattern, best_confidence
    
    @staticmethod
    def extract_advanced_features(trail_data):
        """
        Extract sophisticated behavioral features for advanced analysis.
        
        :param trail_data: List of trail dictionaries
        :return: Dictionary of advanced features
        """
        basic_features = Utils.extract_behavior_features(trail_data)
        
        if not trail_data or len(trail_data) < 3:
            return {**basic_features, 'micro_corrections': 0, 'altitude_precision': 0, 
                   'speed_control': 0, 'temporal_consistency': 0}
        
        # Micro-corrections frequency (small heading adjustments)
        micro_corrections = 0
        for i in range(len(trail_data) - 1):
            curr = trail_data[i]
            next_point = trail_data[i + 1]
            if curr.get('hd') is not None and next_point.get('hd') is not None:
                hd_diff = abs(curr['hd'] - next_point['hd'])
                hd_diff = min(hd_diff, 360 - hd_diff)
                if 1 <= hd_diff <= 5:  # Small corrections
                    micro_corrections += 1
        
        # Altitude management precision
        altitude_changes = []
        for i in range(len(trail_data) - 1):
            curr = trail_data[i]
            next_point = trail_data[i + 1]
            if curr.get('alt') is not None and next_point.get('alt') is not None:
                altitude_changes.append(abs(curr['alt'] - next_point['alt']))
        
        altitude_precision = 1 / (1 + np.std(altitude_changes)) if altitude_changes else 0
        
        # Speed control consistency
        speed_values = [p.get('spd', 0) for p in trail_data if p.get('spd') is not None]
        speed_control = 1 / (1 + np.std(speed_values)) if len(speed_values) > 1 else 0
        
        # Temporal consistency (regular time intervals)
        time_intervals = []
        for i in range(len(trail_data) - 1):
            curr = trail_data[i]
            next_point = trail_data[i + 1]
            if curr.get('ts') is not None and next_point.get('ts') is not None:
                time_intervals.append(abs(curr['ts'] - next_point['ts']))
        
        temporal_consistency = 1 / (1 + np.std(time_intervals)) if len(time_intervals) > 1 else 0
        
        return {
            **basic_features,
            'micro_corrections': micro_corrections,
            'altitude_precision': altitude_precision,
            'speed_control': speed_control,
            'temporal_consistency': temporal_consistency
        }
    
    @staticmethod
    def cluster_flight_behaviors(flight_features_list, n_clusters=5):
        """
        Use K-means clustering to discover flight behavior patterns.
        
        :param flight_features_list: List of feature dictionaries from flights
        :param n_clusters: Number of clusters to create
        :return: Dictionary with cluster results
        """
        if not SKLEARN_AVAILABLE:
            return None
            
        if len(flight_features_list) < n_clusters:
            return None
        
        # Convert feature dictionaries to numpy array
        feature_names = ['turn_frequency', 'altitude_variance', 'speed_consistency', 
                        'path_circularity', 'heading_stability', 'micro_corrections',
                        'altitude_precision', 'speed_control', 'temporal_consistency']
        
        feature_matrix = np.array([
            [features.get(name, 0) for name in feature_names]
            for features in flight_features_list
        ])
        
        # Standardize features
        scaler = StandardScaler()
        feature_matrix_scaled = scaler.fit_transform(feature_matrix)
        
        # Perform K-means clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(feature_matrix_scaled)
        
        return {
            'labels': cluster_labels,
            'centers': kmeans.cluster_centers_,
            'feature_names': feature_names,
            'scaler': scaler
        }
    
    @staticmethod
    def name_discovered_patterns(cluster_results, flight_data_list):
        """
        Assign meaningful names to discovered clusters.
        
        :param cluster_results: Results from cluster_flight_behaviors
        :param flight_data_list: List of flight data corresponding to features
        :return: Dictionary mapping cluster IDs to pattern names
        """
        if not cluster_results:
            return {}
        
        cluster_names = {}
        n_clusters = len(cluster_results['centers'])
        
        for cluster_id in range(n_clusters):
            # Get flights in this cluster
            cluster_flights = [i for i, label in enumerate(cluster_results['labels']) if label == cluster_id]
            
            if not cluster_flights:
                cluster_names[cluster_id] = f"cluster_{cluster_id}"
                continue
            
            # Analyze cluster characteristics
            center = cluster_results['centers'][cluster_id]
            feature_names = cluster_results['feature_names']
            
            # Map back to original scale for interpretation
            center_original = cluster_results['scaler'].inverse_transform([center])[0]
            feature_values = dict(zip(feature_names, center_original))
            
            # Determine pattern name based on dominant characteristics
            if feature_values['path_circularity'] > 0.6:
                cluster_names[cluster_id] = "circular_pattern"
            elif feature_values['heading_stability'] > 0.8 and feature_values['turn_frequency'] < 5:
                cluster_names[cluster_id] = "direct_cruise"
            elif feature_values['turn_frequency'] > 15:
                cluster_names[cluster_id] = "maneuvering"
            elif feature_values['altitude_variance'] > 5000:
                cluster_names[cluster_id] = "climbing_descending"
            elif feature_values['micro_corrections'] > 3:
                cluster_names[cluster_id] = "precision_flight"
            else:
                cluster_names[cluster_id] = f"pattern_{cluster_id + 1}"
        
        return cluster_names
    
    @staticmethod
    def calculate_pattern_confidence(pattern_features, historical_patterns=None):
        """
        Calculate confidence score for pattern classification.
        
        :param pattern_features: Dictionary of extracted features
        :param historical_patterns: Optional historical pattern data for comparison
        :return: Confidence score between 0 and 1
        """
        # Base confidence on feature consistency and strength
        feature_strengths = [
            min(1.0, pattern_features.get('heading_stability', 0)),
            min(1.0, pattern_features.get('speed_consistency', 0)),
            min(1.0, pattern_features.get('altitude_precision', 0)),
            min(1.0, pattern_features.get('temporal_consistency', 0))
        ]
        
        base_confidence = np.mean(feature_strengths)
        
        # Adjust based on data completeness
        data_completeness = sum(1 for v in pattern_features.values() if v > 0) / len(pattern_features)
        
        final_confidence = base_confidence * data_completeness
        return min(1.0, max(0.0, final_confidence))

    @staticmethod
    def compute_straight_line_baseline(plane_loc, heading, speed_kmh, destination_loc=None, current_altitude=None):
        """
        Calculate expected trajectory baseline using straight-line projection.
        
        :param plane_loc: Current aircraft position (lat, lng)
        :param heading: Current aircraft heading in degrees
        :param speed_kmh: Current aircraft speed in km/h
        :param destination_loc: Optional destination coordinates for ETA calculation
        :param current_altitude: Current altitude in feet (for baseline reference)
        :return: Dictionary with baseline predictions
        """
        if not plane_loc or heading is None or speed_kmh is None:
            return None
        
        try:
            # Calculate expected bearing and distance to destination if provided
            if destination_loc:
                expected_bearing = Utils.calculate_bearing(plane_loc, destination_loc)
                distance_to_dest = Utils.calculate_distance(plane_loc, destination_loc)
                expected_eta_hours = distance_to_dest / speed_kmh if speed_kmh > 0 else None
            else:
                expected_bearing = heading
                distance_to_dest = None
                expected_eta_hours = None
            
            return {
                'expected_bearing': expected_bearing,
                'current_heading': heading,
                'expected_altitude_trend': 0,  # Assume level flight for straight-line
                'baseline_altitude': current_altitude,  # Store current altitude as baseline
                'expected_eta_hours': expected_eta_hours,
                'distance_to_destination': distance_to_dest,
                'baseline_type': 'straight_line'
            }
        except Exception:
            return None

    @staticmethod
    def compute_historical_trajectory_baseline(trail_data):
        """
        Analyze trail data to compute trajectory baseline using recent flight patterns.
        
        :param trail_data: List of recent trajectory points
        :return: Dictionary with historical baseline predictions
        """
        if not trail_data or len(trail_data) < 2:  # Reduced minimum requirement
            return None
        
        try:
            # Sort by timestamp (most recent first)
            sorted_trails = sorted(trail_data, key=lambda x: x.get('ts', 0), reverse=True)
            
            # Filter out stale trail data (older than 10 minutes)
            import time
            current_time = time.time()
            max_age_seconds = 10 * 60  # 10 minutes
            fresh_trails = [point for point in sorted_trails if point.get('ts', 0) > (current_time - max_age_seconds)]
            
            if len(fresh_trails) < 2:
                return None  # Not enough fresh trail data
            
            # Use fresh trails for all calculations
            # Calculate average heading trend
            headings = [point.get('hd') for point in fresh_trails if point.get('hd') is not None]
            if len(headings) >= 2:
                heading_trend = np.mean(headings[:3])  # Use 3 most recent points
            else:
                heading_trend = headings[0] if headings else None
            
            # Calculate altitude trend and baseline altitude from trail data
            altitudes = [point.get('alt') for point in fresh_trails if point.get('alt') is not None]
            altitude_trend = 0
            baseline_altitude_feet = None
            
            if len(altitudes) >= 1:
                # Convert altitudes to feet (trail data might be in meters)
                altitudes_feet = [alt * 3.28084 if alt is not None else None for alt in altitudes]
                altitudes_feet = [alt for alt in altitudes_feet if alt is not None]
                
                if len(altitudes_feet) >= 1:
                    # Use most recent altitude as independent baseline
                    baseline_altitude_feet = altitudes_feet[0]  # First element is most recent
                    
                if len(altitudes_feet) >= 2:
                    # Calculate altitude trend in feet per minute
                    alt_changes = [altitudes_feet[i] - altitudes_feet[i+1] for i in range(len(altitudes_feet)-1)]
                    altitude_trend = np.mean(alt_changes) if alt_changes else 0
            
            # Calculate speed trend
            speeds = [point.get('spd') for point in fresh_trails if point.get('spd') is not None]
            speed_trend = np.mean(speeds) if speeds else None
            
            return {
                'historical_heading': heading_trend,
                'altitude_trend': altitude_trend,
                'baseline_altitude_feet': baseline_altitude_feet,  # Independent baseline in feet
                'speed_trend': speed_trend,
                'data_points': len(fresh_trails),  # Count of fresh trail points
                'baseline_type': 'historical'
            }
        except Exception:
            return None

    @staticmethod
    def compute_blended_baseline(straight_line_baseline, historical_baseline, weight_historical=0.7):
        """
        Combine straight-line and historical baselines with weighted averaging.
        
        :param straight_line_baseline: Straight-line projection baseline
        :param historical_baseline: Historical pattern baseline
        :param weight_historical: Weight for historical data (0-1)
        :return: Blended baseline prediction
        """
        if not straight_line_baseline or not historical_baseline:
            return straight_line_baseline or historical_baseline
        
        try:
            weight_straight = 1.0 - weight_historical
            
            # Blend heading predictions
            expected_bearing = None
            if (straight_line_baseline.get('expected_bearing') is not None and 
                historical_baseline.get('historical_heading') is not None):
                expected_bearing = (
                    weight_straight * straight_line_baseline['expected_bearing'] +
                    weight_historical * historical_baseline['historical_heading']
                )
            
            # Blend altitude trends
            altitude_trend = (
                weight_straight * straight_line_baseline.get('expected_altitude_trend', 0) +
                weight_historical * historical_baseline.get('altitude_trend', 0)
            )
            
            # Calculate predicted altitude from independent historical baseline
            predicted_altitude = None
            if historical_baseline and historical_baseline.get('baseline_altitude_feet') is not None:
                # Use independent baseline altitude from trail data (already in feet)
                baseline_altitude_feet = historical_baseline['baseline_altitude_feet']
                if altitude_trend is not None:
                    # Project altitude forward by 1 minute using blended trend (feet per minute)
                    predicted_altitude = baseline_altitude_feet + (altitude_trend * 1.0)  # 1 minute projection
                else:
                    # If no trend available, use baseline altitude directly
                    predicted_altitude = baseline_altitude_feet
            
            return {
                'blended_bearing': expected_bearing,
                'blended_altitude_trend': altitude_trend,
                'predicted_altitude': predicted_altitude,
                'expected_eta_hours': straight_line_baseline.get('expected_eta_hours'),
                'confidence': min(1.0, historical_baseline.get('data_points', 1) / 5.0),
                'baseline_type': 'blended'
            }
        except Exception:
            return straight_line_baseline

    @staticmethod
    def detect_bearing_anomaly(current_heading, baseline_bearing, threshold_degrees):
        """
        Detect bearing anomalies by comparing actual vs predicted heading.
        
        :param current_heading: Current aircraft heading in degrees
        :param baseline_bearing: Expected bearing from baseline calculation
        :param threshold_degrees: Maximum allowed deviation in degrees
        :return: Dictionary with anomaly detection results
        """
        if current_heading is None or baseline_bearing is None:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_degrees}
        
        try:
            # Calculate angular difference (shortest path)
            deviation = abs(((current_heading - baseline_bearing + 180) % 360) - 180)
            anomaly_detected = deviation > threshold_degrees
            
            return {
                'anomaly_detected': anomaly_detected,
                'deviation': deviation,
                'threshold': threshold_degrees,
                'current_heading': current_heading,
                'expected_bearing': baseline_bearing,
                'severity': 'high' if deviation > threshold_degrees * 1.5 else 'medium' if anomaly_detected else 'low'
            }
        except Exception:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_degrees}

    @staticmethod
    def detect_altitude_anomaly(current_altitude, predicted_altitude, threshold_feet):
        """
        Detect altitude anomalies by comparing actual vs predicted altitude from independent historical baselines.
        
        :param current_altitude: Current aircraft altitude (will be converted to feet)
        :param predicted_altitude: Predicted altitude from independent historical baseline (in feet)
        :param threshold_feet: Maximum allowed altitude deviation in feet
        :return: Dictionary with anomaly detection results
        """
        if current_altitude is None or predicted_altitude is None:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_feet}
        
        try:
            # Convert current altitude to feet for consistent comparison
            if isinstance(current_altitude, str):
                current_altitude_raw = float(current_altitude.replace(',', ''))
            else:
                current_altitude_raw = float(current_altitude)
            
            # Assume current altitude might be in meters, convert to feet for consistency
            # FlightRadar24 API typically provides altitude in feet, but ensure consistency
            current_altitude_feet = current_altitude_raw  # Assuming it's already in feet from API
            
            predicted_altitude_feet = float(predicted_altitude)
            
            # Calculate actual deviation between current and independent predicted altitude
            deviation = abs(current_altitude_feet - predicted_altitude_feet)
            anomaly_detected = deviation > threshold_feet
            
            return {
                'anomaly_detected': anomaly_detected,
                'deviation': deviation,
                'threshold': threshold_feet,
                'current_altitude_feet': current_altitude_feet,
                'predicted_altitude_feet': predicted_altitude_feet,
                'severity': 'high' if deviation > threshold_feet * 1.5 else 'medium' if anomaly_detected else 'low'
            }
        except Exception:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_feet}

    @staticmethod
    def detect_timing_anomaly(actual_eta, baseline_eta, threshold_minutes):
        """
        Detect timing anomalies by comparing actual vs predicted ETA.
        
        :param actual_eta: Actual ETA datetime object
        :param baseline_eta: Expected ETA from baseline calculation
        :param threshold_minutes: Maximum allowed timing deviation in minutes
        :return: Dictionary with anomaly detection results
        """
        if not actual_eta or not baseline_eta:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_minutes}
        
        try:
            # Calculate time difference in minutes
            if isinstance(actual_eta, datetime) and isinstance(baseline_eta, datetime):
                time_diff = abs((actual_eta - baseline_eta).total_seconds() / 60)
            else:
                # Handle cases where ETA might be in different formats
                return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_minutes}
            
            anomaly_detected = time_diff > threshold_minutes
            
            return {
                'anomaly_detected': anomaly_detected,
                'deviation': time_diff,
                'threshold': threshold_minutes,
                'actual_eta': actual_eta,
                'expected_eta': baseline_eta,
                'severity': 'high' if time_diff > threshold_minutes * 1.5 else 'medium' if anomaly_detected else 'low'
            }
        except Exception:
            return {'anomaly_detected': False, 'deviation': None, 'threshold': threshold_minutes}

    @staticmethod
    def detect_trajectory_anomalies(flight_data, anomaly_config, origin_location_coords=None):
        """
        Main method to orchestrate all anomaly detection checks.
        
        :param flight_data: Dictionary containing flight information
        :param anomaly_config: Configuration dictionary with thresholds
        :param origin_location_coords: Origin location for destination-based calculations
        :return: Dictionary with comprehensive anomaly detection results
        """
        if not anomaly_config.get('auto_detection_enabled', True):
            return {
                'anomalies_detected': False,
                'anomaly_types': [],
                'anomaly_details': {},
                'anomaly_timestamp': datetime.now()
            }
        
        try:
            # Extract flight parameters
            plane_loc = flight_data.get('location_coords')
            heading = flight_data.get('heading')
            altitude = flight_data.get('altitude')
            speed = flight_data.get('speed')
            trail_data = flight_data.get('latest_trail_data', [])
            eta = flight_data.get('flyby_eta')
            
            # Compute baselines
            straight_baseline = Utils.compute_straight_line_baseline(
                plane_loc, heading, speed, origin_location_coords, altitude
            )
            historical_baseline = Utils.compute_historical_trajectory_baseline(trail_data)
            blended_baseline = Utils.compute_blended_baseline(straight_baseline, historical_baseline)
            
            anomaly_results = {
                'anomalies_detected': False,
                'anomaly_types': [],
                'anomaly_details': {},
                'anomaly_timestamp': datetime.now(),
                'baseline_used': blended_baseline.get('baseline_type', 'none') if blended_baseline else 'none'
            }
            
            # Detect bearing anomalies
            if blended_baseline and blended_baseline.get('blended_bearing'):
                bearing_result = Utils.detect_bearing_anomaly(
                    heading, 
                    blended_baseline['blended_bearing'],
                    anomaly_config.get('bearing_threshold', 30)
                )
                if bearing_result['anomaly_detected']:
                    anomaly_results['anomaly_types'].append('bearing_anomaly')
                    anomaly_results['anomaly_details']['bearing'] = bearing_result
                    anomaly_results['anomalies_detected'] = True
            
            # Detect altitude anomalies using independent baseline from historical trail data
            if blended_baseline and altitude and blended_baseline.get('predicted_altitude') is not None:
                # altitude is current flight altitude (assumed to be in feet from FlightRadar24 API)
                # predicted_altitude is from independent historical baseline (already in feet)
                altitude_result = Utils.detect_altitude_anomaly(
                    altitude,
                    blended_baseline.get('predicted_altitude'),
                    anomaly_config.get('altitude_threshold', 1000)  # threshold in feet
                )
                if altitude_result['anomaly_detected']:
                    anomaly_results['anomaly_types'].append('altitude_anomaly')
                    anomaly_results['anomaly_details']['altitude'] = altitude_result
                    anomaly_results['anomalies_detected'] = True
            
            # Detect timing anomalies (simplified - would need more sophisticated ETA tracking)
            if eta and isinstance(eta, datetime) and blended_baseline:
                # Create a baseline ETA for comparison (simplified)
                baseline_eta_hours = blended_baseline.get('expected_eta_hours')
                if baseline_eta_hours:
                    baseline_eta = datetime.now() + timedelta(hours=baseline_eta_hours)
                    timing_result = Utils.detect_timing_anomaly(
                        eta, baseline_eta, anomaly_config.get('timing_threshold', 3)  # Threshold in minutes
                    )
                    if timing_result['anomaly_detected']:
                        anomaly_results['anomaly_types'].append('timing_anomaly')
                        anomaly_results['anomaly_details']['timing'] = timing_result
                        anomaly_results['anomalies_detected'] = True
            
            return anomaly_results
            
        except Exception as e:
            return {
                'anomalies_detected': False,
                'anomaly_types': [],
                'anomaly_details': {'error': str(e)},
                'anomaly_timestamp': datetime.now()
            }

    @staticmethod
    def _process_flyby_data(flight_data, origin_location_coords, origin_radius_km, flyby_radius_km, ignore_airport_proximity=False, DEBUG_MODE=False):
        """
        Process flight data to determine flyby chance, flyby info and flyby ETA.

        :param flight_data: Dictionary containing flight information.
        :param origin_location_coords: Coordinates of the origin location.
        :param origin_radius_km: Radius of the origin area in kilometers.
        :param flyby_radius_km: Radius for flyby detection in kilometers.
        :param ignore_airport_proximity: When True, calculates flyby info even if plane is closer to airport than origin.
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: Tuple containing (flyby_info, flyby_chance, flyby_chance_debug, flyby_eta_datetime, is_closer_to_airport_than_origin, is_heading, will_pass).
        """
        flyby_info = "-"
        flyby_chance = "-"
        flyby_chance_debug = "-"
        flyby_eta_datetime = "-"
        is_closer_to_airport_than_origin = False
        is_heading = False
        will_pass = False

        callsign = flight_data.get('callsign')
        origin_loc = origin_location_coords
        plane_loc = flight_data.get('location_coords')
        plane_heading = flight_data.get('heading')
        plane_speed_kmph = flight_data.get('speed')
        distance_km = flight_data.get('distance_from_origin', '-')
        timestamp = flight_data.get('timestamp')

        if plane_loc != None and plane_heading != None:
            try:
                plane_loc = (float(plane_loc[0]), float(plane_loc[1]))
                plane_heading = float(plane_heading)
                
                # Determine if the plane is heading towards the origin and will pass within the flyby radius
                is_heading = Utils.is_plane_heading_towards_origin(plane_loc, plane_heading, origin_loc, max_bearing_diff=90)
                will_pass = Utils.will_plane_pass_within_radius(plane_loc, plane_heading, origin_loc, radius_km=flyby_radius_km)

                # Check if the plane is closer to its destination airport than origin, indicating it will land there without passing our origin location
                if is_heading and will_pass:

                    destination_airport_coords = flight_data.get('destination_airport_coords')
                    plane_distance_to_origin = float(distance_km)

                    if destination_airport_coords and destination_airport_coords != None:

                        try:
                            destination_airport_loc = (float(destination_airport_coords['lat']), float(destination_airport_coords['lng']))                           
                            plane_distance_to_dest_airport = Utils.calculate_distance(plane_loc, destination_airport_loc)                            
                            is_closer_to_airport_than_origin = plane_distance_to_dest_airport < plane_distance_to_origin

                        except Exception as e:
                            is_closer_to_airport_than_origin = False

                    # Calculate flyby details if plane isn't heading to land at its airport first OR if airport proximity check is disabled
                    if not is_closer_to_airport_than_origin or ignore_airport_proximity:
                      
                        relevant_trails = flight_data.get('latest_trail_data') or []

                        # Calculate Flyby Chance
                        flyby_chance, flyby_chance_debug = Utils.calculate_flyby_chance(relevant_trails, plane_distance_to_origin, origin_radius_km, 
                                                                                        flyby_radius_km, plane_speed_kmph, max_average_change=10)
                                              
                        if DEBUG_MODE:

                            Utils.LOG_RAW(f"\n{'-' * 60}") # Log Divider
                            Utils.LOG_TS(f"Callsign: {callsign} - Flyby Chance: {flyby_chance_debug}")
                            trail_count = len(relevant_trails)

                            if len(relevant_trails) > 1: # Compute timestamp & heading differences
                                Utils.LOG_RAW(f"\n// Timestamp Diff and Heading - {trail_count} trails")

                                for i in range(trail_count - 1):
                                    hd_current = relevant_trails[i].get('hd')
                                    hd_next = relevant_trails[i + 1].get('hd')
                                    ts_current = relevant_trails[i].get('ts')
                                    ts_next = relevant_trails[i + 1].get('ts')
                                    
                                    if ts_current and ts_next: # Only calculate if both timestamps exist
                                        time_diff = ts_current - ts_next
                                        heading_diff = ((hd_next - hd_current + 180) % 360) - 180 # Shortest angle between headings
                                        delta_prefix = "+" if heading_diff > 0 else "" # Add plus sign for positive changes
                                        Utils.LOG_RAW(f"Trail {i+1}->{i+2}: [{time_diff}s] {hd_current}° -> {hd_next}° ({delta_prefix}{heading_diff}°)")
                                    else:
                                        Utils.LOG_RAW(f"Trail {i+1}->{i+2}: Data unavailable")
                            else:
                                Utils.LOG_RAW("Not enough trail data")

                        # Calculate Flyby Info - Distance and directional information relative to origin
                        flyby_info = Utils.get_flyby_info(plane_loc, plane_heading, origin_loc)

                        # Calculate ETA (Estimated Time of Arrival) to the origin
                        if plane_speed_kmph != None and distance_km != None and float(plane_speed_kmph) > 0 and isinstance(timestamp, datetime):
                            flyby_eta_datetime = timestamp + timedelta(hours=float(distance_km) / float(plane_speed_kmph))
                            flyby_eta_datetime = flyby_eta_datetime.replace(tzinfo=None, microsecond=0)

            except Exception as e:
                print(f"Callsign {callsign}: {e}")
                flyby_info = "-"
                flyby_chance = "-"
                flyby_chance_debug = "-"
                flyby_eta_datetime = "-"
                
        return flyby_info, flyby_chance, flyby_chance_debug, flyby_eta_datetime, is_closer_to_airport_than_origin, is_heading, will_pass
    
    @staticmethod
    async def fetch_api_flights(flights_with_details, origin_location_coords, origin_radius_m, 
                             max_concurrent_requests=10, run_detailed_api=False, fr_api=None, DEBUG_MODE=False):
        """
        Asynchronously fetch and process flight data from the FlightRadar24 API.

        :param flights_with_details: List of flight IDs that already have recent detailed API data fetched.
        :param origin_location_coords: Tuple of (latitude, longitude) for the origin location.
        :param origin_radius_m: Radius around the origin location in meters.
        :param max_concurrent_requests: Maximum number of concurrent API requests.
        :param run_detailed_api: If True, fetch detailed flight information, otherwise skip detailed API calls.
        :param fr_api: FlightRadar24API object instance. If None, a new instance will be created.
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: List of processed flight data dictionaries.
        """
        origin_radius_km = origin_radius_m / 1000

        # Use provided API object or create a new one if None
        if fr_api is None:
            fr_api = FlightRadar24API()

        bounds = fr_api.get_bounds_by_point(origin_location_coords[0], origin_location_coords[1], origin_radius_m)
        flights_api_fetch = Utils._fetch_flights_with_retry(fr_api, bounds)

        # Filter out flights with aircraft_code = 'GRND' (ground vehicles)
        flights = [flight for flight in flights_api_fetch if flight.aircraft_code != 'GRND']

        # Filter flights that are airborne (above 0 altitude)
        flights = [flight for flight in flights if flight.altitude > 0]

        # Filter out flights with low speed (less than 20 km/h)
        min_speed = 20
        flights = [flight for flight in flights if Utils.knots_to_kmph(flight.ground_speed) >= min_speed]

        # Filter flights within the radius (the api "get_bounds_by_point" retrieves flights within a square area and not a circle)
        flights = [flight for flight in flights if Utils.calculate_distance(origin_location_coords,(flight.latitude, flight.longitude)) <= origin_radius_km]

        total_flights = len(flights)
        print(f"\n// Fetching data for aircraft in range: {total_flights}\n")
        
        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(max_concurrent_requests)
        
        # Create and gather tasks
        tasks = []
        for i, flight in enumerate(flights, 1):
            task = asyncio.create_task(Utils._process_flight(flight, flights_with_details, fr_api, i, total_flights, semaphore, run_detailed_api, DEBUG_MODE))
            tasks.append(task)
        
        custom_bar = "{desc:<30}    [{bar:30}] {percentage:3.0f}%  "

        with tqdm(total=len(tasks), desc='Processing Aircraft', bar_format=custom_bar, ascii=" =", leave=False) as pbar:
            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                pbar.update(1)
                yield result

    @staticmethod
    async def _process_flight(flight, flights_with_details, fr_api, i, total_flights, semaphore, run_detailed_api, DEBUG_MODE):
        """
        Process a single flight asynchronously to extract and enhance flight data.
        
        :param flight: Flight object from the FlightRadar24 API.
        :param flights_with_details: List of flight IDs that already have recent detailed API data fetched.
        :param fr_api: FlightRadar24API instance.
        :param i: Current flight index for progress tracking.
        :param total_flights: Total number of flights being processed.
        :param semaphore: Asyncio semaphore to limit concurrent API requests.
        :param run_detailed_api: If True, fetch detailed flight information, otherwise skip detailed API calls.
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: Tuple containing (processed flight data dictionary, current index, total flights count).
        """
        
        altitude = flight.altitude # api altitude = feet above sea level
        speed = flight.ground_speed # api ground_speed = knots (nautical miles per hour)
        timestamp = flight.time # UNIX timestamp
        trail_data = {'lat': flight.latitude, 'lng': flight.longitude, 'alt': altitude, 'spd': speed, 'ts': timestamp, 'hd': flight.heading}
        
        # Save flight data from the regular API fetch
        flight_data = {
            'flight_id': flight.id,
            'callsign': flight.callsign or None,
            'tail_no': flight.registration or None,
            'flight_no': flight.number or None,
            'aircraft_icao': flight.aircraft_code or None,
            'airline_icao': flight.airline_icao or None,
            'origin_airport_iata': flight.origin_airport_iata or None,
            'destination_airport_iata': flight.destination_airport_iata or None,
            'trail_data': trail_data,
            'api_details_fetch': False
        }

        flight_details = None # Initialize

        # Fetch flight details with retry logic and semaphore to limit concurrent connections
        # Only fetch if flight doesn't have recent detailed data (less than 6 minutes old)
        if run_detailed_api and flight.id not in flights_with_details:
            async with semaphore:
                flight_details = await Utils._fetch_flight_details(flight, fr_api, DEBUG_MODE=DEBUG_MODE)

        if flight_details:

            # Extract and update flight_data with detailed info
            callsign = Utils.get_nested(flight_details, 'identification.callsign')
            tail_no = Utils.get_nested(flight_details, 'aircraft.registration')
            flight_no = Utils.get_nested(flight_details, 'identification.number.default')

            aircraft_icao = Utils.get_nested(flight_details, 'aircraft.model.code')    
            aircraft = Utils.get_nested(flight_details, 'aircraft.model.text')
            airline_icao = Utils.get_nested(flight_details, 'airline.code.icao')
            # Retrieve 'airline.short' and fallback to 'airline.name' if necessary
            airline = Utils.get_nested(flight_details, 'airline.short') or Utils.get_nested(flight_details, 'airline.name')

            origin_airport_iata = Utils.get_nested(flight_details, 'airport.origin.code.iata')
            origin_city = Utils.get_nested(flight_details, 'airport.origin.position.region.city')

            destination_airport_iata = Utils.get_nested(flight_details, 'airport.destination.code.iata')
            destination_city = Utils.get_nested(flight_details, 'airport.destination.position.region.city')
        
            destination_airport_position_lat = Utils.get_nested(flight_details, 'airport.destination.position.latitude')
            destination_airport_position_long = Utils.get_nested(flight_details, 'airport.destination.position.longitude')

            # Check if the position coords are present for the destination airport location
            if destination_airport_position_lat == None:
                destination_airport_coords = None
            else:
                destination_airport_coords = {'lat': destination_airport_position_lat, 'lng': destination_airport_position_long}

            trail_list = flight_details.get('trail', [])

            # Extract the first (most recent) 6 trails, if available. If list is empty, set to None
            trail_data_details = trail_list[:6] if trail_list else None 

            # Save flight data from the detailed API fetch
            flight_data_detailed = {
                'callsign': callsign,
                'tail_no': tail_no,
                'flight_no': flight_no,
                'aircraft_icao': aircraft_icao,
                'aircraft': aircraft,
                'airline_icao': airline_icao,
                'airline': airline,
                'origin_airport_iata': origin_airport_iata,
                'origin_city': origin_city,
                'destination_airport_iata': destination_airport_iata,
                'destination_city': destination_city,
                'destination_airport_coords': destination_airport_coords,
                'trail_data_details': trail_data_details,
            }

            # Update flight_data with values from flight_data_detailed only where flight_data has None
            flight_data.update({k: v for k, v in flight_data_detailed.items() if k not in flight_data or flight_data[k] is None})
            flight_data['api_details_fetch'] = True
        
        if DEBUG_MODE:
            Utils.LOG_RAW(f"\n{'-' * 60}") # Log Divider
            Utils.LOG_TS(f"Callsign: {flight_data.get('callsign')} - API Data:")
            Utils.LOG_RAW(json.dumps(flight_data, indent=2, default=str))

        return flight_data, i, total_flights

    @staticmethod
    async def _fetch_flight_details(flight, fr_api, max_retries=5, DEBUG_MODE=False):
        """
        Asynchronously fetch flight details with retry logic.
        
        :param flight: Flight object
        :param fr_api: FlightRadar24API instance
        :param max_retries: Maximum number of retry attempts
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: Flight details or None if fetching fails
        """
        for attempt in range(1, max_retries + 1):
            try:
                loop = asyncio.get_event_loop()
                flight_details = await loop.run_in_executor(None, fr_api.get_flight_details, flight)
                return flight_details  # Success
            except Exception as e:
                if attempt == max_retries:
                    # Error code 402 "Payment Required" occurs occasionally
                    Utils.LOG_TS(f"Flight details fetch failed for flight ID {flight.id}. Error: {e}") if DEBUG_MODE else None
                    return None  # Failed after all retries
                else:
                    wait_time = 2 ** (attempt - 1)  # Exponential backoff
                    await asyncio.sleep(wait_time)

    @staticmethod
    def _fetch_flights_with_retry(fr_api, bounds, max_retries=3, DEBUG_MODE=False):
        """
        Fetch flights within bounds with retry logic.
        
        :param fr_api: FlightRadar24API instance
        :param bounds: Boundary coordinates for the flight search
        :param max_retries: Maximum number of retry attempts
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: Flights data or None if fetching fails
        """
        for attempt in range(1, max_retries + 1):
            try:
                flights = fr_api.get_flights(bounds=bounds)
                return flights  # Success
            except Exception as e:
                if attempt == max_retries:
                    Utils.LOG_TS(f"Flights fetch failed for bounds {bounds}. Error: {e}") if DEBUG_MODE else None
                    return None  # Failed after all retries
                else:
                    wait_time = 2 ** (attempt - 1)  # Exponential backoff
                    time.sleep(wait_time)

    @staticmethod
    def generate_folium_map(flight_list, origin_location_coords, origin_radius_m, flyby_radius_m, ignore_airport_proximity=False, view_center=None, view_zoom=6):
        """
        Generate a Folium Map object visualizing flight data.

        :param flight_list: List of flight data dictionaries.
        :param origin_location_coords: Tuple of (latitude, longitude) for the origin location.
        :param origin_radius_m: Radius around the origin location in meters.
        :param flyby_radius_m: Flyby radius in meters.
        :param ignore_airport_proximity: When True, calculates flyby info even if plane is closer to airport than origin.
        :param view_center: List containing [latitude, longitude] for the map center.
        :param view_zoom: Integer representing the zoom level of the map.        
        :return: A Folium Map object representing the generated map.        
        """

        # Import the color theme
        custom_colors = Utils.get_custom_colors()
        plane_color = custom_colors["plane_color"]
        plane_color_low_alt = custom_colors["plane_color_low_alt"]
        map_feat_color = custom_colors["map_feat_color"]
        popup_bg_color = custom_colors["popup_bg_color"]
        orange_color = custom_colors["orange_color"]
        symbol_right_arrow = "➔"
        
        # Pattern-based color mapping
        pattern_colors = {
            'circular': '#FF6B6B',      # Red for circular patterns
            'linear': '#4ECDC4',        # Teal for linear patterns  
            'erratic': '#FFE66D',       # Yellow for erratic patterns
            'normal': '#A8E6CF',        # Light green for normal patterns
            'direct_cruise': '#87CEEB', # Sky blue for direct cruise
            'maneuvering': '#DDA0DD',   # Plum for maneuvering
            'climbing_descending': '#F0E68C', # Khaki for altitude changes
            'precision_flight': '#98FB98',     # Pale green for precision flight
            'unknown': '#D3D3D3',       # Light gray for unknown
            'insufficient_data': '#808080' # Gray for insufficient data
        }
        
        def get_pattern_color(pattern_type):
            """Get color for pattern type, fallback to default plane color."""
            return pattern_colors.get(pattern_type, plane_color)
        
        def get_trail_style(pattern_type):
            """Get trail styling based on pattern type."""
            trail_styles = {
                'linear': {'dash_array': None, 'weight': 3},  # Solid line
                'circular': {'dash_array': '4,6', 'weight': 2},  # Dotted
                'erratic': {'dash_array': '10,6', 'weight': 2},  # Dashed
                'normal': {'dash_array': None, 'weight': 2},  # Solid, thin
                'maneuvering': {'dash_array': '8,4', 'weight': 2},  # Long dash
            }
            return trail_styles.get(pattern_type, {'dash_array': None, 'weight': 2})

        # Define the distance to extend beyond the origin in kilometers for the bearing line
        extension_distance_km = 30  

        # Use origin_location_coords as default center if center is not provided
        if view_center is None:
            view_center = origin_location_coords

        # Initialize the Folium map centered at the specified location
        plane_map = folium.Map(
            location=view_center,
            zoom_start=view_zoom,
            tiles='OpenStreetMap'
        )

        # Add a circle to represent the tracking radius
        folium.Circle(
            location=origin_location_coords,
            radius=origin_radius_m,  # Radius in meters
            color=map_feat_color,
            fill=True,
            fill_opacity=0.07
        ).add_to(plane_map)

        # Add a circle to represent the flight audible/visible radius
        folium.Circle(
            location=origin_location_coords,
            radius=flyby_radius_m,  # Radius in meters
            color=orange_color,
            fill=True,
            fill_opacity=0.07
        ).add_to(plane_map)

        # Add a tiny dot at the center to represent the origin location
        folium.CircleMarker(
            location=origin_location_coords,
            radius=3,  # Radius in pixels
            color=orange_color,
            fill=True,
            fill_opacity=1, 
            popup=f"""
                <style>
                /* Override the default Leaflet popup content wrapper */
                .leaflet-popup-content-wrapper {{
                    background-color: {popup_bg_color} !important; /* Dark slate background with high opacity */
                    color: #ECF0F1 !important;                            /* Light gray font color for readability */
                    border-radius: 7px !important;                       /* Rounded corners */
                    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5) !important;
                }}

                /* Override the default Leaflet popup tip */
                .leaflet-popup-tip {{
                    background-color: {popup_bg_color} !important;
                }}

                /* Style specific elements within the popup */
                .custom-popup-content b {{
                    color: {orange_color}; /* Specific color for bold labels */
                }}
                
                .custom-popup-content {{
                    padding: 10px;
                    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                    font-size: 14px;
                }}

                /* Style the popup close "×" button */
                .leaflet-popup-close-button {{
                    color: #FFF !important;
                    transform: translate(-3px, 3px); 
                }} 
                </style>

                <div class="custom-popup-content">
                <b>Origin:</b> {origin_location_coords[0]}, {origin_location_coords[1]}
                </div>
                """
        ).add_to(plane_map)

        # Initialize MarkerCluster for better performance with lots of markers
        marker_cluster = MarkerCluster(maxClusterRadius=50).add_to(plane_map)

        # Function to create a rotated icon with labels using DivIcon
        def create_rotated_icon(angle, labels=None, altitude=None, pattern_color=None, has_anomaly=False):
            """
            Creates a rotated DivIcon with optional labels and altitude-based color.

            :param angle: Rotation angle in degrees.
            :param labels: Dictionary containing label texts.
            :param altitude: Altitude in meters for color selection.
            :param pattern_color: Color based on flight pattern type.
            :param has_anomaly: Boolean indicating if flight has anomalies.
            :return: folium.DivIcon object.
            """
            # Define low altitude threshold
            low_alt_threshold = 3000  # meters - Visually observable and audible from ground
            # Above low_alt_threshold: Limited visibility and audibility from ground
            
            # Set color based on altitude or pattern
            if pattern_color is not None:
                # Use pattern-based color, but still consider altitude for low altitude flights
                if altitude is not None:
                    try:
                        alt_value = float(altitude)
                        if alt_value <= low_alt_threshold:
                            plane_alt_color = plane_color_low_alt  # Override for low altitude
                        else:
                            plane_alt_color = pattern_color
                    except (ValueError, TypeError):
                        plane_alt_color = pattern_color
                else:
                    plane_alt_color = pattern_color
            elif altitude is not None:
                try:
                    alt_value = float(altitude)
                    if alt_value <= low_alt_threshold:
                        plane_alt_color  = plane_color_low_alt  # Lower altitude
                    else:
                        plane_alt_color  = plane_color  # Higher altitude
                except (ValueError, TypeError):
                    plane_alt_color  = plane_color  # Default to high altitude color
            else:
                plane_alt_color  = plane_color  # Default color

            # Create a plane icon SVG with the appropriate color
            plane_icon_svg = f"""
            <?xml version="1.0" encoding="utf-8"?>
            <svg width="32px" height="32px" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
                <title>aircraft</title>
                <path d="M15.521 3.91c0.828 0 1.5 0.672 1.5 1.5v7.75l10 6.25v2.688l-10-3.375v5.25l2.039 2.029-0.001 2.084l-3.538-1.176-3.487 1.18 0.015-2.189 1.91-1.865 0.017-5.312-9.997 3.436 0.021-2.75 10.007-6.313 0.016-7.688c-0.002-0.827 0.67-1.499 1.498-1.499z" fill="{plane_alt_color }"/>
            </svg>
            """

            label_html = ""
            if labels:
                # Construct label HTML
                label_html = f"""
                <div style="margin-left: 5px; font-size: 11px; color: white; white-space: nowrap;">
                    <div>{labels.get('callsign', '-')}</div>
                    <div>{labels.get('origin', '-')} {symbol_right_arrow} {labels.get('destination', '-')}</div>
                </div>
                """

            # Add anomaly indicator styling
            anomaly_style = ""
            if has_anomaly:
                anomaly_style = "border: 3px solid #FF0000; border-radius: 50%; background-color: rgba(255, 0, 0, 0.1); box-shadow: 0 0 10px rgba(255, 0, 0, 0.5);"

            # Rotate the SVG icon only, keep labels upright
            html = f"""
            <div style="display: flex; align-items: center;">
                <div style="transform: rotate({angle}deg); padding: 2px; {anomaly_style}">
                    {plane_icon_svg}
                </div>
                {label_html}
            </div>
            """
            
            # Add icon_size and icon_anchor to center the icon
            return folium.DivIcon(html=html, icon_size=(32, 32), icon_anchor=(16, 16))
        
        url_flightradar_flight_no_base =  "https://www.flightradar24.com/data/flights/"
        url_flightradar_reg_no_base =  "https://www.flightradar24.com/data/aircraft/"
        url_skybrary_aircraft_icao_base = "https://skybrary.aero/aircraft/"

        # Iterate through each flight and add a marker with labels
        for flight in flight_list:

            # Skip flights with invalid coordinates/heading
            try:
                # Check if Location Coords exists and is not None
                location_coords = flight.get('Location Coords')
                if not location_coords or len(location_coords) < 2:
                    continue  # Skip flights with missing or incomplete coordinates
                
                plane_loc = (float(location_coords[0]), float(location_coords[1]))
                plane_heading = float(flight['Heading (°)'])
            except (ValueError, TypeError, KeyError, IndexError):
                continue # Skipping flight due to invalid coordinates/heading

            # ================== ADDING THE TRAIL LINE WITH GRADIENT OPACITY ==================

            # Plot the trail line with gradient opacity and pattern-based styling
            relevant_trails = flight.get('latest_trail_data', [])
            pattern_type = flight.get('Pattern') or flight.get('pattern_type', 'normal')
            trail_color = get_pattern_color(pattern_type)
            trail_style = get_trail_style(pattern_type)
            
            if len(relevant_trails) > 1:
                # Extract positions from index 1 onward
                positions = [
                    (trail['lat'], trail['lng'])
                    for trail in relevant_trails
                    if 'lat' in trail and 'lng' in trail
                ]
                if positions:
                    num_segments = len(positions) - 1
                    opacity_trail_recent = 0.4  # Opacity for the most recent trail (less transparent)
                    opacity_trail_oldest = 0.1  # Opacity for the oldest trail (more transparent)
                    for i in range(num_segments):
                        start = positions[i]
                        end = positions[i + 1]
                        # Calculate opacity
                        opacity_trail = opacity_trail_oldest + (opacity_trail_recent - opacity_trail_oldest) * (num_segments - i) / num_segments
                        # Draw segment with pattern-based styling
                        polyline_kwargs = {
                            'locations': [start, end],
                            'color': trail_color,
                            'weight': trail_style['weight'],
                            'opacity': opacity_trail,
                        }
                        if trail_style['dash_array']:
                            polyline_kwargs['dash_array'] = trail_style['dash_array']
                        
                        folium.PolyLine(**polyline_kwargs).add_to(plane_map)

            # ================== END OF TRAIL LINE ==================

            # ================== ADDING THE BEARING LINE ==================

            plane_distance_to_origin = float(flight['Distance (km)'])  # Get the distance from the plane to the origin

            # Retrieve saved data from flight_data
            is_heading = flight.get('is_heading_towards_origin', False)
            will_pass = flight.get('will_pass_within_radius', False)
            is_closer_to_airport_than_origin = flight.get('is_closer_to_airport_than_origin', False)
            flyby_eta_datetime = flight.get('ETA', '-')
            eta_time = flyby_eta_datetime.time() if isinstance(flyby_eta_datetime, datetime) else '-'
            flyby_info = flight.get('Flyby Info', '-')
            flyby_chance = flight.get('Flyby Chance', '-')

            # Check if the plane is heading towards the origin and will pass within the Origin Radius (10 km)
            if is_heading and will_pass:

                if is_closer_to_airport_than_origin and not ignore_airport_proximity:
                    pass  # Skip drawing - plane will land before reaching origin and airport proximity check is active
                else:
                    # Calculate the extended point along the plane's exact heading
                    total_distance = plane_distance_to_origin + extension_distance_km
                    extended_point = Utils.calculate_destination(plane_loc, plane_heading, total_distance)

                    # Opacity Bearing Line
                    opacity_bear_high = 0.6    # High Flyby Chance
                    opacity_bear_medium = 0.4  # Medium Flyby Chance
                    opacity_bear_low = 0.2     # Low Flyby Chance                  

                    # Set bearing line opacity based on flyby_chance
                    try:
                        flyby_chance_val = float(flyby_chance)
                    except (ValueError, TypeError):
                        flyby_chance_val = 0.4  # Default opacity
                        
                    # Map flyby_probability to opacity_bearing based on defined ranges
                    if flyby_chance_val >= 0.8:
                        opacity_bearing = opacity_bear_high
                    elif flyby_chance_val >= 0.6:
                        opacity_bearing = opacity_bear_medium
                    else:
                        opacity_bearing = opacity_bear_low
                    
                    # Add the Bearing Line (a dotted PolyLine) representing the plane's path along its heading
                    folium.PolyLine(
                        locations=[plane_loc, (extended_point[0], extended_point[1])],
                        color=orange_color,
                        weight=3,
                        opacity=opacity_bearing,
                        dash_array='10,10'
                    ).add_to(plane_map)

            # ================== END OF BEARING LINE ==================

            # Format Flyby Chance as %
            flyby_chance = f"{int(round(flyby_chance * 100))} %" if flyby_chance != "-" else flyby_chance
      
            # Format Flight No as a clickable link to Flightradar
            flight_no_display = (
                f"{flight['Flight No']} <a href='{url_flightradar_flight_no_base}{flight['Flight No']}' target='_blank' style='text-decoration: none;'>🔗</a>"
                if flight['Flight No'] != "-" else "-"
                )
            
            # Format Tail No as a clickable link to Flightradar
            tail_no_display = (
                f"{flight['Tail No']} <a href='{url_flightradar_reg_no_base}{flight['Tail No']}' target='_blank' style='text-decoration: none;'>🔗</a>"
                if flight['Tail No'] != "-" else "-"
                )
            
            # Format Aircraft ICAO Code as a clickable link to Flightradar
            aircraft_code_display = (
                f"{flight['Aircraft Code']} <a href='{url_skybrary_aircraft_icao_base}{flight['Aircraft Code']}' target='_blank' style='text-decoration: none;'>🔗</a>"
                if flight['Aircraft Code'] != "-" else "-"
                )
            
            # Fetch the plane's altitude
            plane_alt = flight['Alt (m)']

            # Prepare pattern information for popup
            pattern_info = flight.get('Pattern', '-')
            pattern_confidence = flight.get('Pattern Confidence', '-')
            if pattern_confidence != '-' and pattern_confidence != 0.0:
                try:
                    if isinstance(pattern_confidence, (int, float)):
                        pattern_confidence_display = f"{int(round(pattern_confidence * 100))} %"
                    else:
                        pattern_confidence_display = str(pattern_confidence)
                except (ValueError, TypeError):
                    pattern_confidence_display = str(pattern_confidence)
            else:
                pattern_confidence_display = '-'
            
            # Prepare the popup content
            popup_content = f"""
            <style>
        /* Override the default Leaflet popup content wrapper */
        .leaflet-popup-content-wrapper {{
            background-color: {popup_bg_color} !important; /* Dark slate background with high opacity */
            color: #ECF0F1 !important;                            /* Light gray font color for readability */
            border-radius: 7px !important;                       /* Rounded corners */
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5) !important;
        }}

        /* Override the default Leaflet popup tip */
        .leaflet-popup-tip {{
            background-color: {popup_bg_color} !important; /* Match the popup background */
        }}

        /* Style specific elements within the popup */
        .custom-popup-content b {{
            color: {orange_color}; /* Specific color for bold labels */
        }}
        
        .custom-popup-content {{
            padding: 10px;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 14px;
        }}

        /* Style the popup close "×" button */
        .leaflet-popup-close-button {{
            color: #FFF !important;
            transform: translate(-3px, 3px); 
        }} 
            </style>

            <div class="custom-popup-content">

            <b>Callsign:</b>&nbsp; {flight['Callsign']}<br>
            <b>Tail No:</b>&nbsp; {tail_no_display}<br>
            <b>Flight No:</b>&nbsp; {flight_no_display}<br>
            <b>Airline:</b>&nbsp; {flight['Airline']}<br>
            <b>Aircraft:</b>&nbsp; {aircraft_code_display}<br>
            <b>Origin:</b>&nbsp; {flight['Origin']}<br>
            <b>Destin.:</b>&nbsp; {flight['Destination']}<br>
            <b>Altitude:</b>&nbsp; {plane_alt} m<br>
            <b>Speed:</b>&nbsp; {flight['Speed (km/h)']} km/h<br>
            <b>Location:</b>&nbsp; {flight['Location']}<br>
            <b>Heading:</b>&nbsp; {flight['Heading (°)']}°<br>
            <br>

            <b>{symbol_right_arrow} Flight Pattern</b><br>
            <b>Pattern:</b>&nbsp; {pattern_info}<br>
            <b>Confidence:</b>&nbsp; {pattern_confidence_display}<br>
            <br>

            <b>{symbol_right_arrow} Anomaly Detection</b><br>
            <b>Anomalies:</b>&nbsp; {"🚨 YES" if flight.get('anomalies_detected', False) else "✅ NO"}<br>
            <b>Types:</b>&nbsp; {f"⚠️ {flight.get('anomaly_types', '-')}" if flight.get('anomaly_types') and flight.get('anomaly_types') != "-" else "-"}<br>
            <br>

            <b>{symbol_right_arrow} Origin</b><br>

            <b>Distance:</b>&nbsp; {flight['Distance (km)']} km<br>
            <b>Flyby Chance:</b>&nbsp; {flyby_chance}<br>
            <b>Flyby Info:</b>&nbsp; {flyby_info}<br>
            <b>ETA:</b>&nbsp; {eta_time}<br>

            </div>
            """

            # Prepare labels
            labels = {
            'callsign': flight.get('Callsign'),
            'origin': flight.get('Origin Airport'),
            'destination': flight.get('Destination Airport')
            }

            # Create the rotated icon with labels and pattern-based color
            pattern_type = flight.get('Pattern') or flight.get('pattern_type', 'normal')
            pattern_color = get_pattern_color(pattern_type)
            has_anomaly = flight.get('anomalies_detected', False)
            icon = create_rotated_icon(plane_heading, labels=labels, altitude=plane_alt, pattern_color=pattern_color, has_anomaly=has_anomaly)

            # Create the popup
            popup = folium.Popup(popup_content, max_width=300)
            popup.options['offset'] = [0, -9]  # Move the popup

            # Add the marker to the cluster
            folium.Marker(
                location=plane_loc,
                popup=popup,
                icon=icon
            ).add_to(marker_cluster)

        # Add pattern legend to the map
        legend_html = f'''
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 200px; height: auto; 
                    background-color: {popup_bg_color}; color: #ECF0F1;
                    border: 2px solid {map_feat_color}; z-index:9999; 
                    border-radius: 10px; padding: 10px; font-size: 12px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.4);">
        <h4 style="color: {orange_color}; margin-top: 0;">Flight Patterns</h4>
        <p><span style="color: {pattern_colors['circular']};">●</span> Circular - Holding/loops</p>
        <p><span style="color: {pattern_colors['linear']};">●</span> Linear - Direct flight</p>
        <p><span style="color: {pattern_colors['erratic']};">●</span> Erratic - Irregular path</p>
        <p><span style="color: {pattern_colors['normal']};">●</span> Normal - Regular flight</p>
        <p><span style="color: {pattern_colors['maneuvering']};">●</span> Maneuvering - Course adjustments</p>
        <p><span style="color: {pattern_colors['climbing_descending']};">●</span> Altitude changes</p>
        <p><span style="color: {pattern_colors['precision_flight']};">●</span> Precision flight</p>
        <p><span style="color: {pattern_colors['unknown']};">●</span> Unknown pattern</p>
        <p style="margin-bottom: 0;"><span style="color: {pattern_colors['insufficient_data']};">●</span> Insufficient data</p>
        </div>
        '''
        plane_map.get_root().html.add_child(folium.Element(legend_html))
        
        # Inject the custom CSS into the map's HTML
        plane_map.get_root().header.add_child(folium.Element(Utils.get_css_custom_map(map_feat_color, popup_bg_color, orange_color)))   

        return plane_map

    @staticmethod
    def process_df_flight_data(df_flights, origin_radius_km):
        """
        Processes a DataFrame of flight data with transformations and filters.

        :param df_flights: The input DataFrame containing flight data.
        :param origin_radius_km: Radius (in km) to filter flights within.
        :return: Processed DataFrame.
        """

        # Convert tuple coordinates to "latitude, longitude" string format
        df_flights['Location Coords'] = df_flights['Location Coords'].apply(
            lambda x: ', '.join(map(str, x)) if isinstance(x, tuple) and x is not None else (x if x is not None else "-")
        )

        # Format "Flyby Chance" as %
        df_flights['Flyby Chance'] = df_flights['Flyby Chance'].apply(
            lambda x: f"{int(round(x * 100))} %" if pd.notna(x) and x != "-" else x
        )

        # Replace non-numeric values in the "Distance (km)" column with NaN
        df_flights['Distance (km)'] = pd.to_numeric(df_flights['Distance (km)'], errors='coerce')

        # Filter flights within the radius
        df_flights = df_flights[df_flights['Distance (km)'] <= origin_radius_km]

        # Sort by Distance (km) in ascending order, ignoring NaN values
        df_flights = df_flights.sort_values(by='Distance (km)', ascending=True)

        # Convert numeric distances to integers (after sorting, before filling NaNs)
        df_flights['Distance (km)'] = df_flights['Distance (km)'].astype('Int64')

        # Replace NaN values with '-'
        df_flights['Distance (km)'] = df_flights['Distance (km)'].fillna('-')

        # Set the index to start from 1
        df_flights.index = range(1, len(df_flights) + 1)

        return df_flights
    
    @staticmethod
    def prepare_terminal_dfs(df_flights_list_terminal):
        """
        Processes and prepares DataFrames for terminal list and schedule display.

        :param df_flights_list_terminal: DataFrame containing flight data.
        :return: Processed DataFrames: df_flights_list_terminal, df_flights_schedule_terminal
        """
        df_flights_list_terminal['Airline'] = df_flights_list_terminal['Airline'].apply(Utils.truncate_string)

        columns_to_remove_terminal = ['Flight No', 'Aircraft', 'Airline Code', 'Origin Airport', 'Origin City', 'Destination Airport', 'Destination Airport Location', 
                                      'Destination City', 'Location Coords', 'Timestamp', 'is_heading_towards_origin', 'will_pass_within_radius',
                                      'is_closer_to_airport_than_origin', 'latest_trail_data']
        df_flights_list_terminal = df_flights_list_terminal.drop(columns=columns_to_remove_terminal)

        df_flights_list_terminal.rename(columns={'Aircraft Code': 'Aircraft'}, inplace=True)

        df_flights_schedule_terminal = df_flights_list_terminal.copy() # Make a copy for the Flights Schedule terminal print

        # Format 'ETA' to show only 'HH:MM:SS' for display
        df_flights_list_terminal['ETA'] = df_flights_list_terminal['ETA'].apply(
            lambda x: x.strftime('%H:%M:%S') if isinstance(x, datetime) else x) # Update the 'ETA' to only show 'HH:MM:SS'

        df_flights_schedule_terminal = df_flights_schedule_terminal[df_flights_schedule_terminal['ETA'] != '-']

        if not df_flights_schedule_terminal.empty:
            df_flights_schedule_terminal = df_flights_schedule_terminal.sort_values(by='ETA')
            df_flights_schedule_terminal['ETA'] = df_flights_schedule_terminal['ETA'].apply(
                lambda x: x.strftime('%H:%M:%S') if isinstance(x, datetime) else x) # Update the 'ETA' to only show 'HH:MM:SS'
            df_flights_schedule_terminal.index = range(1, len(df_flights_schedule_terminal) + 1)
            cols_to_move_schedule = ['ETA', 'Flyby Chance', 'Flyby Info', 'Distance (km)'] # Columns to bring to the front
            df_flights_schedule_terminal = df_flights_schedule_terminal[cols_to_move_schedule + [col for col in df_flights_schedule_terminal.columns if col not in cols_to_move_schedule]] # Rearrange the columns

        return df_flights_list_terminal, df_flights_schedule_terminal

    @staticmethod
    def prepare_and_save_flights_csv(df_flights_csv, origin_location, maps_directory):
        """
        Processes the flights DataFrame for CSV export and saves it with a timestamped filename.

        :param df_flights_csv: DataFrame containing flight data.
        :param origin_location: String name of the origin location.
        :param maps_directory: Path object where the CSV file will be saved.
        :return: Full path of the saved CSV file.
        """
        columns_to_remove_csv = ['Aircraft Code', 'Origin Airport', 'Origin City', 'Destination Airport', 'Destination Airport Location', 'Destination City',
                                'Timestamp', 'is_heading_towards_origin', 'will_pass_within_radius', 'is_closer_to_airport_than_origin', 'latest_trail_data']
        df_filtered_csv = df_flights_csv.drop(columns=columns_to_remove_csv)

        current_datetime = datetime.now().strftime('%Y-%m-%d_%H.%M.%S')

        # Define the filename with the date and time
        flights_list_filename = f'flight_list_{origin_location}_{current_datetime}.csv'

        # Save it in the proper location
        flights_list_csv_full_path = maps_directory / flights_list_filename

        # Save the DataFrame to a CSV file
        df_filtered_csv.to_csv(flights_list_csv_full_path, index=True)

        return flights_list_csv_full_path
    
    @staticmethod
    def save_flights_html(flight_list, origin_location_coords, origin_radius_m, flyby_radius_m, origin_location, maps_directory, ignore_airport_proximity=False):
        """
        Generates a Folium map and saves it to an HTML file with a location-based filename.

        :param flight_list: List of flights to be displayed on the map.
        :param origin_location_coords: Tuple of (latitude, longitude) for the origin location.
        :param origin_radius_m: Radius around the origin location in meters.
        :param flyby_radius_m: Flyby radius in meters.
        :param origin_location: String name of the origin location.
        :param maps_directory: Pathlib Path object for the directory where the map will be saved.
        :param ignore_airport_proximity: When True, calculates flyby info even if plane is closer to airport than origin.
        :return: Full path of the saved HTML file.
        """
        # Generate the Folium map
        plane_map_folium = Utils.generate_folium_map(flight_list, origin_location_coords, origin_radius_m, flyby_radius_m, ignore_airport_proximity)

        current_datetime = datetime.now().strftime('%Y-%m-%d_%H.%M.%S')

        # Define the map filename
        flights_map_filename = f'flight_map_{origin_location}_{current_datetime}.html'
        flights_map_full_path = maps_directory / flights_map_filename

        # Save the map to an HTML file
        plane_map_folium.save(flights_map_full_path)

        # Return the full path of the saved file
        return flights_map_full_path
    
    @staticmethod
    def prepare_flight_list(flight_active_list_db_load, origin_location_coords, origin_radius_km, flyby_radius_km, ignore_airport_proximity, DEBUG_MODE, anomaly_config=None, db_path=None):
        """
        Prepare flight data by combining saved trail points (removing duplicates and sorting by recency), 
        updating with location info, converting units and calculating flyby predictions.

        :param flight_active_list_db_load: List of active flight data dicts from database
        :param origin_location_coords: Tuple of (latitude, longitude) for the origin location
        :param origin_radius_km: Radius of the origin area in kilometers
        :param flyby_radius_km: Radius for flyby detection in kilometers
        :param ignore_airport_proximity: When True, calculates flyby info even if plane is closer to airport than origin
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: List of processed flight dictionaries with standardized fields
        """
        prepared_flights = []
        
        for flight_data in flight_active_list_db_load:

            # Get trail data, ensuring we have lists even if values are None
            trail_data = flight_data.get('trail_data') or []
            trail_data_details = flight_data.get('trail_data_details') or []

            # Combine trail points
            all_trail_points = trail_data + trail_data_details

            # Remove duplicates
            seen_ts = set()
            unique_trail_points = [p for p in all_trail_points if p.get('ts') not in seen_ts and not seen_ts.add(p.get('ts'))]
            
            # Get current time in Unix format (seconds since epoch)
            current_unix_time = int(time.time())

            # Calculate the unix timestamp threshold for trail points (6 minutes ago)
            trail_age_unix_threshold = current_unix_time - (6 * 60)  # 6 minutes in seconds

            # Filter out points older than 6 minutes
            recent_trail_points = [point for point in unique_trail_points if point.get('ts', 0) >= trail_age_unix_threshold]

            # Sort after removing duplicates
            recent_unique_trail_points = sorted(recent_trail_points, key=lambda x: x.get('ts', 0), reverse=True)

            # Guard against empty trail points
            if not recent_unique_trail_points:
                # Create minimal record with defaults (keep flight_id for anomaly updates)
                prepared_flight_data = {k: v for k, v in flight_data.copy().items() if k not in ['trail_data', 'trail_data_details', 'last_fetch_timestamp', 'last_fetch_timestamp_details']}
                prepared_flight_data.update({
                    'pattern_type': 'insufficient_data',
                    'pattern_confidence': 0.0,
                    'altitude': 0,
                    'speed': 0,
                    'heading': 0,
                    'location_coords': None,
                    'location': 'Unknown',
                    'timestamp': datetime.now(),
                    'origin': '-',
                    'destination': '-',
                    'distance_from_origin': 0,
                    'latest_trail_data': [],
                    'flyby_chance': '-',
                    'flyby_info': '-',
                    'flyby_eta': '-',
                    'is_closer_to_airport_than_origin': False,
                    'is_heading_towards_origin': False,
                    'will_pass_within_radius': False
                })
                prepared_flights.append(prepared_flight_data)
                continue

            last_known_position = recent_unique_trail_points[0] # Extract the first trail point as the most recent position data
            relevant_trails = recent_unique_trail_points[:6] # Extract the first (most recent) 6 trails (1 current + 5 previous), if available

            altitude_feet = last_known_position.get('alt')
            altitude = Utils.feet_to_meters(altitude_feet) # api altitude = feet above sea level

            speed_knots = last_known_position.get('spd')
            speed = Utils.knots_to_kmph(speed_knots) # api ground_speed = knots (nautical miles per hour)

            latitude = last_known_position.get('lat')
            longitude = last_known_position.get('lng')
            location_coords = (latitude, longitude) if latitude and longitude else None
            location = reverse_geocode.get((latitude, longitude))["city"]
            distance = Utils.calculate_distance(origin_location_coords, (latitude, longitude))

            heading = last_known_position.get('hd')
        
            timestamp_unix = last_known_position.get('ts')
            utc_dt = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc) # Convert the Unix timestamp to a timezone-aware datetime in UTC
            timestamp = utc_dt.astimezone() # Convert UTC datetime to local timezone

            origin_code = flight_data.get('origin_airport_iata')
            origin_city = flight_data.get('origin_city')
            destination_code = flight_data.get('destination_airport_iata')
            destination_city = flight_data.get('destination_city')

            def format_location(city, code):
                if code:
                    return f"{city + ' ' if city else ''}({code})"
                return "-"

            origin = format_location(origin_city, origin_code)
            destination = format_location(destination_city, destination_code)

            # Create a copy of the original flight dict and remove old keys we don't need anymore (keep flight_id for anomaly updates)
            remove_keys = ['trail_data', 'trail_data_details', 'last_fetch_timestamp', 'last_fetch_timestamp_details']
            prepared_flight_data = {k: v for k, v in flight_data.copy().items() if k not in remove_keys}

            # Create the additional flight data
            additional_flight_data = {
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'location_coords': location_coords,
                'location': location,
                'timestamp': timestamp,
                'origin': origin,
                'destination': destination,
                'distance_from_origin': distance,
                'latest_trail_data': relevant_trails
            }

            prepared_flight_data.update(additional_flight_data) # Update the prepared flight with the additional data     

            # Calculate flyby data with the updated flight data
            flyby_info, flyby_chance, flyby_chance_debug, flyby_eta_datetime, is_closer_to_airport_than_origin, is_heading, will_pass = Utils._process_flyby_data(
                    prepared_flight_data, origin_location_coords, origin_radius_km, flyby_radius_km, ignore_airport_proximity, DEBUG_MODE)
            
            # Add the flyby data to the prepared flight
            prepared_flight_data.update({
                'flyby_chance': flyby_chance,
                'flyby_info': flyby_info,
                'flyby_eta': flyby_eta_datetime,
                'is_closer_to_airport_than_origin': is_closer_to_airport_than_origin,
                'is_heading_towards_origin': is_heading,
                'will_pass_within_radius': will_pass
            })
            
            # Pattern Detection Integration
            try:
                pattern_type, pattern_confidence = Utils.classify_basic_pattern(relevant_trails)
                prepared_flight_data.update({
                    'pattern_type': pattern_type,
                    'pattern_confidence': pattern_confidence
                })
            except Exception as e:
                # Gracefully handle pattern detection errors
                prepared_flight_data.update({
                    'pattern_type': 'unknown',
                    'pattern_confidence': 0.0
                })

            # Anomaly Detection Integration
            try:
                # Use provided anomaly config or default values
                if anomaly_config is None:
                    anomaly_config = {
                        'bearing_threshold': 30.0,
                        'altitude_threshold': 1000.0,
                        'timing_threshold': 3.0,
                        'auto_detection_enabled': True,
                        'detection_mode': 'auto'
                    }
                
                anomaly_results = Utils.detect_trajectory_anomalies(
                    prepared_flight_data, anomaly_config, origin_location_coords
                )
                prepared_flight_data.update({
                    'anomalies_detected': anomaly_results.get('anomalies_detected', False),
                    'anomaly_types': anomaly_results.get('anomaly_types', []),
                    'anomaly_details': anomaly_results.get('anomaly_details', {}),
                    'anomaly_timestamp': anomaly_results.get('anomaly_timestamp')
                })
            except Exception as e:
                # Gracefully handle anomaly detection errors
                prepared_flight_data.update({
                    'anomalies_detected': False,
                    'anomaly_types': [],
                    'anomaly_details': {},
                    'anomaly_timestamp': None
                })
                if DEBUG_MODE:
                    Utils.LOG_TS(f"Pattern detection error for {prepared_flight_data.get('callsign', '-')}: {e}")
            


            # Replace None values with "-" for display fields
            fields_to_check = ['callsign', 'tail_no', 'flight_no', 'aircraft_icao', 'aircraft', 'airline_icao', 'airline', 
                               'origin_airport_iata', 'origin_city', 'destination_airport_iata', 'destination_city']
            prepared_flight_data.update({k: "-" for k in fields_to_check if k in prepared_flight_data and prepared_flight_data[k] is None})

            prepared_flights.append(prepared_flight_data) # Append the updated flight dict to prepared_flights

        # Save anomaly detection results back to database if db_path is provided
        if db_path and prepared_flights:
            try:
                # Update anomaly fields for each flight using the new helper
                updated_count = 0
                for flight in prepared_flights:
                    if 'anomalies_detected' in flight and 'flight_id' in flight:
                        success = sql.DatabaseUtils.update_anomaly_fields(
                            db_path,
                            flight.get('flight_id'),
                            flight.get('anomalies_detected', False),
                            flight.get('anomaly_types', []),
                            flight.get('anomaly_details', {}),
                            flight.get('anomaly_timestamp')
                        )
                        if success:
                            updated_count += 1
                
                if DEBUG_MODE and updated_count > 0:
                    Utils.LOG_TS(f"Updated anomaly detection results for {updated_count} flights in database")
            except Exception as e:
                if DEBUG_MODE:
                    Utils.LOG_TS(f"Error saving anomaly results to database: {e}")

        return prepared_flights
    
    @staticmethod
    def standardize_flight_keys(prepared_flights):
        """
        Rename dictionary keys to a standardized format for DataFrame columns/display purposes.

        :param prepared_flights: List of flight dictionaries with processed data
        :return: List of flight dictionaries with renamed keys for presentation
        """
        key_mapping = {
            'callsign': 'Callsign',
            'tail_no': 'Tail No',
            'flight_no': 'Flight No',
            'aircraft_icao': 'Aircraft Code',
            'aircraft': 'Aircraft',
            'airline_icao': 'Airline Code',
            'airline': 'Airline',
            'origin_airport_iata': 'Origin Airport',
            'origin': 'Origin',
            'destination_airport_coords': 'Destination Airport Location',
            'destination_city': 'Destination City',
            'destination': 'Destination',
            'altitude': 'Alt (m)',
            'speed': 'Speed (km/h)',
            'heading': 'Heading (°)',
            'location_coords': 'Location Coords',
            'location': 'Location',
            'distance_from_origin': 'Distance (km)',
            'timestamp': 'Timestamp',
            'flyby_eta': 'ETA',
            'flyby_chance': 'Flyby Chance',
            'flyby_info': 'Flyby Info',
            'pattern_type': 'Pattern',
            'pattern_confidence': 'Pattern Confidence',
            'anomalies_detected': 'Anomalies Detected',
            'anomaly_types': 'Anomaly Types',
            'anomaly_details': 'Anomaly Details',
            'anomaly_timestamp': 'Anomaly Timestamp'
        }

        standardized_flights = [{key_mapping.get(k, k): v for k, v in flight.items()} for flight in prepared_flights]
        
        return standardized_flights
    
    @staticmethod
    def fetch_api_airport_data(fr_api):
        """
        Fetch airport data from FlightRadar24 API.

        :param fr_api: FlightRadar24API instance
        :return: List of airport dictionaries with data            
        """
        from FlightRadarAPI import Countries
        
        # Get airports from major countries to build comprehensive reference data
        # Using fewer countries to avoid rate limiting
        major_countries = [
            Countries.UNITED_STATES, Countries.CANADA, Countries.UNITED_KINGDOM,
            Countries.GERMANY, Countries.FRANCE, Countries.AUSTRALIA
        ]
        
        airport_data_api_objects = fr_api.get_airports(countries=major_countries)
        
        # List comprehension which converts the flightradar objects to dictionaries
        airport_data_list = [
            {
                'icao': airport.icao,
                'iata': getattr(airport, 'iata', ''),
                'name': airport.name,
                'lat': airport.latitude,
                'lng': airport.longitude,
                'country': getattr(airport, 'country', ''),
            } for airport in airport_data_api_objects
        ]

        return airport_data_list

    @staticmethod
    def fetch_api_airline_data(fr_api):
        """
        Fetch airline data from FlightRadar24 API.
        
        :param fr_api: FlightRadar24API instance
        :return: List of airline dictionaries with data
        """
        airline_data_api_list = fr_api.get_airlines()

        # List comprehension to convert to the format we need
        airline_data_list = [
            {
                'icao': airline['ICAO'],
                'name': airline['Name'],
            } for airline in airline_data_api_list if airline['ICAO']  # Skip entries with empty ICAO
        ]

        return airline_data_list

    @staticmethod    
    def refresh_reference_data(db_path, fr_api, DEBUG_MODE=False):
        """
        Check if reference data needs refreshing and performs the refresh if needed.
        
        :param db_path: Path to the SQLite database file
        :param fr_api: FlightRadar API client instance
        :param DEBUG_MODE: Enable debug mode for detailed logging to debug file.
        :return: bool: True if data was refreshed, False if refresh wasn't needed
        """
        # Check if reference data needs refreshing
        is_reference_data_refresh_needed = sql.DatabaseUtils.is_reference_data_refresh_needed(db_path)

        if is_reference_data_refresh_needed:

            Utils.LOG_RAW(f"\n{'-' * 60}") if DEBUG_MODE else None # DEBUG # Log Divider
            Utils.LOG_TS("Refreshing reference data - airport/airline info is missing or outdated.") if DEBUG_MODE else None # DEBUG

            # Fetch API airport data and save to DB
            airport_data_api_list = Utils.fetch_api_airport_data(fr_api)
            Utils.LOG_RAW(f"Found data for {len(airport_data_api_list)} airports from API") if DEBUG_MODE else None # DEBUG
            airports_saved_count = sql.DatabaseUtils.save_airport_data_to_db(db_path, airport_data_api_list)
            Utils.LOG_RAW(f"Saved {airports_saved_count} airports to database") if DEBUG_MODE else None # DEBUG
            
            # Fetch API airline data and save to DB
            airline_data_api_list = Utils.fetch_api_airline_data(fr_api)
            Utils.LOG_RAW(f"Found data for {len(airline_data_api_list)} airlines from API") if DEBUG_MODE else None # DEBUG
            airlines_saved_count = sql.DatabaseUtils.save_airline_data_to_db(db_path, airline_data_api_list)
            Utils.LOG_RAW(f"Saved {airlines_saved_count} airlines to database") if DEBUG_MODE else None # DEBUG
            
            # Fetch city data from airportsdata package for airports missing this info and save to DB
            airport_city_data = sql.DatabaseUtils.fetch_airport_city_data(db_path)
            Utils.LOG_RAW(f"Found city data for {len(airport_city_data)} airports") if DEBUG_MODE else None # DEBUG
            airport_data_updated_count = sql.DatabaseUtils.save_airport_city_data_to_db(db_path, airport_city_data)
            Utils.LOG_RAW(f"Updated {airport_data_updated_count} airports with city data") if DEBUG_MODE else None # DEBUG # DEBUG
    
            return True
        else:
            return False



if __name__ == '__main__':

    config_file = 'config.ini' # Config file location
    db_path = "sql_database.db" # Database location
    fr_api = FlightRadar24API()
    db_init_tables = sql.DatabaseUtils.db_tables # Initialize database tables
    maps_directory = Path('exports') # Directory for storing exports
    maps_directory.mkdir(parents=True, exist_ok=True) # Create the directory if it doesn't already exist

    Utils.print_main_header()

    try:
        origin_location_coords, origin_radius_m, _, ignore_airport_proximity, DEBUG_MODE, anomaly_config = Utils.load_and_validate_config(config_file) # Assign the validated config vars
        origin_radius_km = origin_radius_m / 1000
    except ValueError as e:
        print(f"\nError: {e}")
        input(f"\nPlease correct the Config file and restart the program. Press ENTER to exit: ")
        exit()
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        input(f"\nConfig file is missing. Please re-download config.ini. Press ENTER to exit: ")
        exit()

    # Checks if database exists - creates and initializes it if not
    try: 
        sql.execute(db_path, "SELECT * FROM flights LIMIT 1")
    except sqlite3.OperationalError:
        for query in db_init_tables:
            sql.execute(db_path, query)

    # Setup logging
    Utils.setup_logging("debug.log") if DEBUG_MODE else None # DEBUG

    flyby_radius_km = 10
    flyby_radius_m = flyby_radius_km * 1000

    # Get the closest known city to the origin coordinates
    origin_location = reverse_geocode.get(origin_location_coords)["city"]

    print("-" * 30)
    print(f"Origin: {origin_location}")
    print(f"Radius: {int(origin_radius_km)} km")
    print("-" * 30)

    # Convert the city name to lowercase
    origin_location = origin_location.lower()

    # Remove old flight data which is older than 1 week
    sql.DatabaseUtils.cleanup_old_flights(db_path)

    # Refresh airport/airline reference data if older than 1 month
    Utils.refresh_reference_data(db_path, fr_api, DEBUG_MODE=DEBUG_MODE)

    # Load existing flight IDs which already have recent detailed data (less than 6 minutes old)
    existing_flights_with_details = sql.DatabaseUtils.get_flights_with_details_fetched(db_path)

    # Fetch new flight data using the API asynchronously
    async def async_fetch_flight_data():
        flight_list = [flight_data async for flight_data, _, _ in Utils.fetch_api_flights(
                                                existing_flights_with_details, origin_location_coords, origin_radius_m, 
                                                run_detailed_api=True, fr_api=fr_api, DEBUG_MODE=DEBUG_MODE)]
        return flight_list
    
    flight_active_list = asyncio.run(async_fetch_flight_data()) # Run the async func in a synchronous context
    flight_active_list_ids = [flight.get('flight_id') for flight in flight_active_list] # Extract flight IDs for all active flights

    # Save flight data to DB - We'll use previous trail_data to update the new trail_data (6 most recent trails)
    sql.DatabaseUtils.save_flights_to_db(db_path, flight_active_list)

    # Enrich flight data with info from airport and airline tables in our database
    enriched_flight_list = sql.DatabaseUtils.enrich_missing_flight_data_from_db(db_path, flight_active_list)

    # Save the enriched data back to the database
    sql.DatabaseUtils.save_enriched_flights_to_db(db_path, enriched_flight_list)

    # Load complete flight data for active flights
    flight_active_list_db_load = sql.DatabaseUtils.load_flights_from_db(db_path, flight_active_list_ids)

    # Process flight data - combine trail points, update location info, convert units, calculate flyby predictions
    flight_active_list_prepared = Utils.prepare_flight_list(flight_active_list_db_load, origin_location_coords, origin_radius_km,
                                                flyby_radius_km, ignore_airport_proximity, DEBUG_MODE=DEBUG_MODE, anomaly_config=anomaly_config, db_path=db_path)

    # Persist pattern analysis results to database
    pattern_records = [
        {
            'flight_id': f.get('flight_id') or f.get('callsign', 'unknown'),
            'pattern_type': f.get('pattern_type'),
            'pattern_confidence': f.get('pattern_confidence'),
            'behavioral_features': Utils.extract_behavior_features(f.get('latest_trail_data', [])),
            'pattern_discovery_method': 'basic_classification'
        }
        for f in flight_active_list_prepared if f.get('pattern_type')
    ]
    if pattern_records:
        sql.DatabaseUtils.save_flight_patterns_to_db(db_path, pattern_records)

    # Standardize the keys - rename the dict keys, preparing it for dataframe/display
    flight_active_list_final = Utils.standardize_flight_keys(flight_active_list_prepared)


    if not flight_active_list_final:
        print(f"There are no flights in your area. Please try again later.")
        input(f"\nPress ENTER to exit: ")
        exit()

    else:

        # Create a DataFrame from the list of flight data dictionaries
        df_flights = pd.DataFrame(flight_active_list_final)

        # Process the DataFrame
        df_flights = Utils.process_df_flight_data(df_flights, origin_radius_km)


        # ========================   TERMINAL PRINT - Flights List

        df_flights_list_terminal = df_flights.copy()
        df_flights_list_terminal, df_flights_schedule_terminal = Utils.prepare_terminal_dfs(df_flights_list_terminal)

        print(f"Flight List\n------------------------")
        print(df_flights_list_terminal)

        # ========================   TERMINAL PRINT - Flights Schedule

        if not df_flights_schedule_terminal.empty:
            print()
            print(f"Flight Schedule\n------------------------")
            print(df_flights_schedule_terminal)

        # ========================   NORMALIZE CITY NAME

        origin_location_norm = unidecode(origin_location).replace(" ", "_") # Normalize chars & replace spaces for filename compatibility


        # ========================   SAVE TO CSV

        df_flights_csv = df_flights.copy()
        flights_csv_path = Utils.prepare_and_save_flights_csv(df_flights_csv, origin_location_norm, maps_directory)
        print(f"\nFlight List has been saved to {flights_csv_path}")
          
        # ========================   SAVE TO HTML

        # Save the map to an HTML file and generate it inside the function
        flights_map_path = Utils.save_flights_html(
            flight_list=flight_active_list_final,
            origin_location_coords=origin_location_coords,
            origin_radius_m=origin_radius_m,
            flyby_radius_m=flyby_radius_m,
            origin_location=origin_location_norm,
            maps_directory=maps_directory,
            ignore_airport_proximity=ignore_airport_proximity
        )
        print(f"Flight Map has been saved to {flights_map_path}\n")