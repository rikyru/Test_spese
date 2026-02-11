import duckdb
import pandas as pd
import zipfile
import os
from .utils import clean_currency, normalize_tags
from .rules_engine import RulesEngine

class DataManager:
    def __init__(self, db_path=None):
        if db_path is None:
            # Check if finance_data folder exists, otherwise use root
            default_path = "finance_data/finance.duckdb" if os.path.exists("finance_data") else "finance.duckdb"
            db_path = os.getenv("DB_PATH", default_path)
        self.con = duckdb.connect(db_path)
        self.rules_engine = RulesEngine()
        self.setup_db()

    def setup_db(self):
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                date DATE,
                amount DOUBLE,
                currency VARCHAR,
                account VARCHAR,
                category VARCHAR,
                tags VARCHAR[],
                description VARCHAR,
                type VARCHAR,
                source_file VARCHAR,
                original_description VARCHAR,
                necessity VARCHAR,
                id VARCHAR DEFAULT uuid()
            )
        """)
        
        # Recurring Expenses Table
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id VARCHAR DEFAULT uuid(),
                name VARCHAR,
                amount DOUBLE,
                category VARCHAR,
                account VARCHAR,
                frequency VARCHAR, -- 'Monthly', 'Yearly', 'Weekly'
                next_date DATE,
                description VARCHAR,
                tags VARCHAR[],
                remaining_installments INTEGER,
                end_date DATE
            )
        """)
        
        # Migration: Ensure necessity/id column exists (for existing DBs)
        try:
            columns = self.con.execute("PRAGMA table_info(transactions)").fetchall()
            col_names = [c[1] for c in columns]
            
            if 'necessity' not in col_names:
                self.con.execute("ALTER TABLE transactions ADD COLUMN necessity VARCHAR")
                
            if 'id' not in col_names:
                self.con.execute("ALTER TABLE transactions ADD COLUMN id VARCHAR")
                self.con.execute("UPDATE transactions SET id = uuid() WHERE id IS NULL")
                
        except Exception as e:
            print(f"Migration error: {e}")

        # Migration: Ensure new recurring columns exist
        try:
            columns = self.con.execute("PRAGMA table_info(recurring_expenses)").fetchall()
            col_names = [c[1] for c in columns]
            
            if 'description' not in col_names:
                self.con.execute("ALTER TABLE recurring_expenses ADD COLUMN description VARCHAR")
            if 'tags' not in col_names:
                self.con.execute("ALTER TABLE recurring_expenses ADD COLUMN tags VARCHAR[]")
            if 'remaining_installments' not in col_names:
                self.con.execute("ALTER TABLE recurring_expenses ADD COLUMN remaining_installments INTEGER")
            if 'end_date' not in col_names:
                self.con.execute("ALTER TABLE recurring_expenses ADD COLUMN end_date DATE")
        except Exception as e:
            print(f"Recurring Migration error: {e}")

    # ... (ingest_zip and other methods remain)

    def add_recurring(self, name, amount, category, account, frequency, start_date, description, tags, installments=None, end_date=None):
        self.con.execute("""
            INSERT INTO recurring_expenses (name, amount, category, account, frequency, next_date, description, tags, remaining_installments, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [name, amount, category, account, frequency, start_date, description, tags, installments, end_date])

    def update_recurring(self, rec_id, **kwargs):
        """
        Updates a recurring expense. kwargs keys must match column names.
        """
        if not kwargs:
            return
            
        set_parts = []
        values = []
        
        valid_cols = {'name', 'amount', 'category', 'account', 'frequency', 'next_date', 'description', 'tags', 'remaining_installments', 'end_date'}
        
        for k, v in kwargs.items():
            if k in valid_cols:
                set_parts.append(f"{k} = ?")
                values.append(v)
                
        if not set_parts:
            return
            
        values.append(rec_id)
        q = f"UPDATE recurring_expenses SET {', '.join(set_parts)} WHERE id = ?"
        self.con.execute(q, values)

    def get_recurring(self):
        return self.con.execute("SELECT * FROM recurring_expenses ORDER BY next_date").df()

    def delete_recurring(self, rec_id):
        self.con.execute("DELETE FROM recurring_expenses WHERE id = ?", [rec_id])

    def process_recurring(self):
        """Checks for due expenses, inserts them, and updates next_date."""
        import datetime
        from dateutil.relativedelta import relativedelta
        
        today = datetime.date.today()
        due = self.con.execute("SELECT * FROM recurring_expenses WHERE next_date <= ?", [today]).df()
        
        count = 0
        for _, row in due.iterrows():
            # Get props, handle missing
            desc = row.get('description') if pd.notna(row.get('description')) else row['name']
            
            # Handle tags safely (DuckDB might return numpy array or list)
            raw_tags = row.get('tags')
            current_tags = []
            if isinstance(raw_tags, list):
                current_tags = raw_tags
            elif hasattr(raw_tags, 'tolist'):
                current_tags = raw_tags.tolist()
            elif pd.notna(raw_tags) and raw_tags: # String or other
                # Try to ensure it's a list
                current_tags = list(raw_tags) if not isinstance(raw_tags, str) else [raw_tags]
            
            # Add 'Recurring' tag if not present
            if 'Recurring' not in current_tags:
                current_tags.append('Recurring')
            
            # Insert Transaction
            self.con.execute("""
                INSERT INTO transactions (date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity, id)
                VALUES (?, ?, 'EUR', ?, ?, ?, ?, 'Expense', 'Recurring', ?, 'Need', uuid())
            """, [row['next_date'], row['amount'], row['account'], row['category'], current_tags, desc, row['name']])
            
            # Update next_date
            next_date = pd.to_datetime(row['next_date']).date()
            if row['frequency'] == 'Monthly':
                next_date += relativedelta(months=1)
            elif row['frequency'] == 'Yearly':
                next_date += relativedelta(years=1)
            elif row['frequency'] == 'Weekly':
                next_date += datetime.timedelta(weeks=1)
            
            self.con.execute("UPDATE recurring_expenses SET next_date = ? WHERE id = ?", [next_date, row['id']])
            
            # Handle Installments decrement
            if pd.notna(row['remaining_installments']):
                 new_installments = int(row['remaining_installments']) - 1
                 if new_installments <= 0:
                     self.delete_recurring(row['id']) # Finished
                 else:
                     self.con.execute("UPDATE recurring_expenses SET remaining_installments = ? WHERE id = ?", [new_installments, row['id']])
            
            # Handle End Date (if next_date is now beyond end_date, delete)
            if pd.notna(row['end_date']):
                e_date = pd.to_datetime(row['end_date']).date()
                if next_date > e_date:
                    self.delete_recurring(row['id'])

            count += 1
            
        return count

    def get_initial_balance(self):
        """
        Retrieves the initial balance transaction if it exists.
        Returns: dict with {date, amount} or None
        """
        try:
            # Look for strict match first
            res = self.con.execute("SELECT date, amount FROM transactions WHERE description = 'Saldo Iniziale' AND list_contains(tags, 'Initial') LIMIT 1").fetchone()
            if res:
                return {'date': res[0], 'amount': res[1]}
            
            # Fallback (maybe tag is missing or string)
            res = self.con.execute("SELECT date, amount FROM transactions WHERE description = 'Saldo Iniziale' LIMIT 1").fetchone()
            if res:
                 return {'date': res[0], 'amount': res[1]}
                 
            return None
        except Exception:
            return None

    def set_initial_balance(self, date, amount):
        """
        Sets or updates the initial balance.
        """
        # Check if exists
        existing = self.get_initial_balance()
        
        if existing:
            # Update
            self.con.execute("""
                UPDATE transactions 
                SET date = ?, amount = ?
                WHERE description = 'Saldo Iniziale'
            """, [date, amount])
        else:
            # Insert
            import datetime
            # Ensure date is date object
            if isinstance(date, str):
                date = pd.to_datetime(date).date()
                
            self.con.execute("""
                INSERT INTO transactions (id, date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity)
                VALUES (uuid(), ?, ?, 'EUR', 'Initial Assets', 'Initial Balance', ['Initial'], 'Saldo Iniziale', 'Income', 'manual_entry', 'Saldo Iniziale', 'Need')
            """, [date, amount])
            
        return True

    def get_projected_recurring(self, end_date):
        """
        Returns a list of projected occurrences of recurring expenses up to end_date.
        Does NOT insert them into DB.
        Returns: DataFrame columns [date, amount, name, account, category]
        """
        import datetime
        from dateutil.relativedelta import relativedelta
        
        # Ensure end_date is date
        if isinstance(end_date, datetime.datetime):
            end_date = end_date.date()
            
        active_rules = self.get_recurring()
        projections = []
        
        for _, rule in active_rules.iterrows():
            current_next = pd.to_datetime(rule['next_date']).date()
            
            # Limits
            rem_inst = rule['remaining_installments'] if pd.notna(rule['remaining_installments']) else None
            r_end_date = pd.to_datetime(rule['end_date']).date() if pd.notna(rule['end_date']) else None
            
            # Loop while next occurrence is before or on end_date
            while current_next <= end_date:
                # Check rule specific end limits
                if r_end_date and current_next > r_end_date:
                    break
                if rem_inst is not None and rem_inst <= 0:
                    break
                    
                projections.append({
                    'date': current_next,
                    'amount': rule['amount'],
                    'name': rule['name'],
                    'category': rule['category'],
                    'account': rule['account'],
                    'frequency': rule['frequency']
                })
                
                # Update loop trackers
                if rem_inst is not None:
                    rem_inst -= 1
                
                # Advance date
                if rule['frequency'] == 'Monthly':
                    current_next += relativedelta(months=1)
                elif rule['frequency'] == 'Yearly':
                    current_next += relativedelta(years=1)
                elif rule['frequency'] == 'Weekly':
                    current_next += datetime.timedelta(weeks=1)
                else:
                    break # Safer
                    
        return pd.DataFrame(projections)


    def export_backup_zip(self):
        """Creates a ZIP file containing CSVs of all data."""
        import io
        import zipfile
        
        # Get all data
        df = self.get_transactions()
        
        # Buffer for ZIP
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
            # Group by source_file to reconstruct structure
            # Handle source_file being None or empty
            df['source_file'] = df['source_file'].fillna('manual_export.csv')
            
            for source, group in df.groupby('source_file'):
                # Clean filename
                fname = str(source)
                if not fname.endswith('.csv'):
                    fname += '.csv'
                
                # Convert to CSV string
                csv_data = group.to_csv(index=False)
                z.writestr(fname, csv_data)
                
            # Also export recurring rules
            rec_df = self.get_recurring()
            if not rec_df.empty:
                z.writestr('recurring_rules.csv', rec_df.to_csv(index=False))
                
        return zip_buffer.getvalue()

    def ingest_zip(self, zip_path):
        """Reads all CSVs from ZIP and inserts into DuckDB."""
        try:
            # Get existing files to avoid duplicates
            try:
                existing_files = self.con.execute("SELECT DISTINCT source_file FROM transactions").fetchall()
                existing_files = set([r[0] for r in existing_files])
            except:
                existing_files = set()

            with zipfile.ZipFile(zip_path, 'r') as z:
                count = 0
                skipped = 0
                for filename in z.namelist():
                    if filename.endswith('.csv'):
                        # Check if already imported
                        if filename in existing_files:
                            skipped += 1
                            continue
                            
                        with z.open(filename) as f:
                            df = pd.read_csv(f)
                            self._process_and_insert(df, filename)
                            count += 1
                            
            return True, f"Imported {count} files. Skipped {skipped} duplicates."
        except Exception as e:
            return False, str(e)

    def _process_and_insert(self, df, filename):
        # Normalize columns based on known schema
        # Schema: Date, Wallet, Type, Category name, Amount, Currency, Note, Labels, Author
        
        # Renaissance mapping
        df = df.rename(columns={
            'Date': 'date',
            'Wallet': 'account',
            'Type': 'type',
            'Category name': 'category',
            'Amount': 'amount',
            'Currency': 'currency',
            'Note': 'description',
            'Labels': 'tags'
        })

        # Fill missing
        df['description'] = df['description'].fillna('')
        df['tags'] = df['tags'].fillna('')
        df['source_file'] = filename
        df['original_description'] = df['description'] # Keep original for debugging rules

        # Transform
        df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
        df['amount'] = df['amount'].apply(clean_currency)
        
        # Ensure Expenses are negative
        # Some apps export expenses as positive numbers with Type="Expense"
        df.loc[df['type'] == 'Expense', 'amount'] = -df.loc[df['type'] == 'Expense', 'amount'].abs()
        # Ensure Income is positive
        df.loc[df['type'] == 'Income', 'amount'] = df.loc[df['type'] == 'Income', 'amount'].abs()
        
        # Handle tags: "Labels" column might contain "#tag1 #tag2" or "#tag1, #tag2"
        # We convert to list of strings
        def handle_raw_tags(x):
            if not x: return []
            if isinstance(x, list):
                return normalize_tags(x)
            return normalize_tags([x])
            
        df['tags'] = df['tags'].apply(handle_raw_tags)
        
        with open("debug_log.txt", "a") as f:
            f.write(f"--- New Insert ---\nInput DF Tags:\n{df['tags'].tolist()}\n")

        # Apply Rules Engine
        df = self.rules_engine.apply_rules(df)
        df = self.rules_engine.auto_tag_from_description(df)

        # Insert into DuckDB
        # DuckDB can insert pandas DF directly
        # Note: Table schema must match DF columns order or use by name if supported, 
        # but safely: ensure DF has all columns.
        if 'necessity' not in df.columns:
            df['necessity'] = 'Want'
            
        if 'necessity' not in df.columns:
            df['necessity'] = 'Want'
            
        # Add ID for new rows
        # DuckDB uuid generation in SQL is best.
        # "INSERT INTO transactions SELECT ..., uuid() FROM df"
        # We need to list columns explicitly to match.
        
        self.con.execute("INSERT INTO transactions (date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity, id) SELECT date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity, uuid() FROM df")

    def get_transactions(self):
        return self.con.execute("SELECT * FROM transactions ORDER BY date DESC").df()

    def get_summary(self):
        return self.con.execute("""
            SELECT 
                YEAR(date) as year, 
                MONTH(date) as month, 
                type, 
                SUM(amount) as total 
            FROM transactions 
            GROUP BY 1, 2, 3 
            ORDER BY 1 DESC, 2 DESC
        """).df()

    def get_unique_categories(self):
        try:
            res = self.con.execute("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL ORDER BY 1").fetchall()
            return [r[0] for r in res if r[0]]
        except:
            return []

    def get_unique_tags(self):
        try:
            # Explode tags array (DuckDB specific unnest not always simple with list column in python-bound duckdb, 
            # but unnest(tags) works in SQL if tags is VARCHAR[])
            # Our tags column is stored as VARCHAR[] (list of strings) in DuckDB if inserted via pandas with object/list column.
            # Let's check type. If pandas inserted lists, proper type in DuckDB is usually VARCHAR[].
            res = self.con.execute("SELECT DISTINCT unnest(tags) FROM transactions").fetchall()
            return [r[0] for r in res if r[0]]
        except:
            return []

    def get_unique_accounts(self):
        try:
            res = self.con.execute("SELECT DISTINCT account FROM transactions WHERE account IS NOT NULL ORDER BY 1").fetchall()
            return [r[0] for r in res if r[0]]
        except:
            return []
