# will read the .yaml files from configs folder and convert them into python dictionaries for the scraper to use

import yaml
import os

def load_site_config(site_name: str):
    # path to the configs folder, relative to this file
    # Current file: services/scraper/src/utils/config_loader.py
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    # 1. ../ goes to src
    # 2. ../../ goes to scraper
    # 3. ../../../ - This actually goes to 'services'. 
    # If your 'configs' folder is inside 'scraper', you only need TWO levels up.
    
    config_path = os.path.join(base_path, "../../configs", f"{site_name}.yaml")
    
    # Resolve the .. to a clean absolute path
    clean_path = os.path.abspath(config_path)
    
    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Config not found for: {site_name} at {clean_path}")
        
    with open(clean_path, 'r') as f:
        return yaml.safe_load(f)