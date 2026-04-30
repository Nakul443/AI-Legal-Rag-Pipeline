# will read the .yaml files from configs folder and convert them into python dictionaries for the scraper to use

import yaml
import os

def load_site_config(site_name: str):
    # path to the configs folder, relative to this file
    base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, "../configs", f"{site_name}.yaml")
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found for: {site_name} at {config_path}")
        
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)