import yaml
import re
import pandas as pd

class RulesEngine:
    def __init__(self, rules_path=None):
        import os
        if rules_path is None:
            default_path = "finance_data/rules.yaml" if os.path.exists("finance_data") else "rules.yaml"
            rules_path = os.getenv("RULES_PATH", default_path)
        self.rules_path = rules_path
        self.rules = self.load_rules()

    def load_rules(self):
        try:
            with open(self.rules_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {
                'categories': [],
                'tags': []
            }

    def save_rules(self, new_rules):
        with open(self.rules_path, 'w') as f:
            yaml.dump(new_rules, f)
        self.rules = new_rules

    def apply_rules(self, df):
        """Applies categorization and tagging rules to the dataframe."""
        if df.empty:
            return df

        # Default necessity
        if 'necessity' not in df.columns:
            df['necessity'] = 'Want' # Default to Want

        # Apply Category Rules
        # Rule format: { 'name': 'Groceries', 'match': ['coop', 'conad'] }
        if 'categories' in self.rules:
            for cat_rule in self.rules['categories']:
                cat_name = cat_rule.get('name')
                patterns = cat_rule.get('match', [])
                
                # Create a regex pattern
                full_regex = '|'.join(patterns)
                if full_regex:
                    mask = df['description'].str.contains(full_regex, case=False, na=False, regex=True)
                    df.loc[mask, 'category'] = cat_name
                    
                    # Apply necessity if defined
                    necessity = cat_rule.get('necessity')
                    if necessity:
                        df.loc[mask, 'necessity'] = necessity

        # Apply Tag Rules
        # Rule format: { 'tag': 'subscription', 'match': ['netflix', 'spotify'] }
        if 'tags' in self.rules:
            for tag_rule in self.rules['tags']:
                tag_name = tag_rule.get('tag')
                patterns = tag_rule.get('match', [])
                
                full_regex = '|'.join(patterns)
                if full_regex:
                    mask = df['description'].str.contains(full_regex, case=False, na=False, regex=True)
                    
                    # Append tag to list
                    # Handle possibility of row_tags being numpy array (from DuckDB) or list
                    def add_tag(row_tags):
                        if hasattr(row_tags, 'tolist'):
                            row_tags = row_tags.tolist()
                        if not isinstance(row_tags, list):
                            row_tags = list(row_tags) if row_tags is not None else []
                            
                        if tag_name not in row_tags:
                            row_tags.append(tag_name)
                        return row_tags

                    df.loc[mask, 'tags'] = df.loc[mask, 'tags'].apply(add_tag)

        return df

    def auto_tag_from_description(self, df):
        """Extracts common keywords as tags if not already present."""
        # Simple keyword extraction (naive)
        keywords = ['luce', 'gas', 'internet', 'taxi', 'uber', 'amazon']
        
        for kw in keywords:
            mask = df['description'].str.contains(kw, case=False, na=False)
            
            def add_kw_tag(row_tags):
                if hasattr(row_tags, 'tolist'):
                    row_tags = row_tags.tolist()
                if not isinstance(row_tags, list):
                    row_tags = list(row_tags) if row_tags is not None else []
                    
                if kw not in row_tags:
                    row_tags.append(kw)
                return row_tags
                
            df.loc[mask, 'tags'] = df.loc[mask, 'tags'].apply(add_kw_tag)
            
        return df

    def learn_from_history(self, history_df):
        """
        Builds a lookup dictionary from historical data to suggest categories.
        Returns a dict: {description_lower: category}
        """
        if history_df.empty:
            return {}
            
        # Group by description and find most frequent category
        # Using exact description match for now
        
        # Filter where category is not null
        valid_hist = history_df[history_df['category'].notna()].copy()
        valid_hist['desc_clean'] = valid_hist['description'].str.strip().str.lower()
        
        # Get mode category for each description
        lookup = {}
        # Iterate unique descriptions
        for desc in valid_hist['desc_clean'].unique():
            if not desc: continue
            
            # Find rows
            mask = valid_hist['desc_clean'] == desc
            cats = valid_hist.loc[mask, 'category']
            
            if not cats.empty:
                # Top frequent category
                top_cat = cats.mode().iloc[0]
                lookup[desc] = top_cat
                
        self.history_lookup = lookup
        return lookup

    def apply_history_rules(self, df):
        """Applies learned categories to rows with missing categories."""
        if not hasattr(self, 'history_lookup') or not self.history_lookup:
            return df
            
        if 'category' not in df.columns:
            df['category'] = None
            
        # Identify rows needing category
        mask = df['category'].isna() | (df['category'] == '')
        
        def lookup_cat(desc):
            if not isinstance(desc, str): return None
            return self.history_lookup.get(desc.strip().lower())
            
        # Apply lookup
        start_missing = mask.sum()
        if start_missing > 0:
            suggested = df.loc[mask, 'description'].apply(lookup_cat)
            
            # Fill where suggestion found
            found_mask = suggested.notna()
            # We need to map back to original indices
            # df.loc[mask & found_mask_aligned, 'category'] = ...
            # Easier: likely iterating or vectorizing carefully
            
            # Let's use fillna on the series
            df.loc[mask, 'category'] = suggested
            
        return df
