import pandas as pd
import re

def clean_currency(amount_str):
    """Ensures amount is a float."""
    if isinstance(amount_str, (float, int)):
        return float(amount_str)
    try:
        return float(str(amount_str).replace(',', '.'))
    except:
        return 0.0

def extract_tags(text):
    """Extracts hashtags from a string."""
    if not isinstance(text, str):
        return []
    return re.findall(r"#(\w+)", text)

def normalize_tags(tags_list):
    """Cleans and deduplicates a list of tags."""
    if not tags_list:
        return []
    # Split comma separated strings if any
    final_tags = []
    for t in tags_list:
        if isinstance(t, str):
            # Remove # if present for storage, or keep it? 
            # User seems to like #, let's keep them normalized as strings without # internally for cleaner matching, 
            # or keep # for display. Let's strip # for processing and add back for display if needed.
            # Actually user input "anche i campi con # eh" implies the input has #.
            # Let's standardize: lowercase, no #, unique.
            parts = t.replace('#', '').replace(',', ' ').split()
            final_tags.extend([p.lower() for p in parts])
    return sorted(list(set(final_tags)))
