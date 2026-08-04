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

            if 'notes' not in col_names:
                self.con.execute("ALTER TABLE transactions ADD COLUMN notes VARCHAR")

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

    def get_subscription_suggestions(self, min_payments=3):
        """
        Suggerisce possibili abbonamenti da aggiungere alle ricorrenti.

        Per ogni tag di servizio (Spotify, Drive, ...) non ancora configurato né
        ignorato, con almeno `min_payments` pagamenti:
          - rileva la FREQUENZA dalla cadenza recente (ultimi 4 intervalli):
            > 150gg = Yearly, < 12gg = Weekly, altrimenti Monthly;
          - stima l'IMPORTO dall'ultimo pagamento (prezzo attuale);
          - scarta gli abbonamenti INATTIVI, cioè senza pagamenti recenti rispetto
            all'ultima data presente nei dati (non a "oggi", così l'assenza di
            import recenti non falsa il calcolo).
        Ritorna dict {tag, frequency, amount, n, last, category, account}.
        """
        from .utils import SUBSCRIPTION_TAGS
        import statistics
        try:
            df = self.con.execute("""
                SELECT lower(unnest(tags)) AS tag, date, amount, category
                FROM transactions WHERE type = 'Expense'
            """).df()
        except Exception:
            return []
        if df.empty:
            return []
        df = df[df['tag'].isin(SUBSCRIPTION_TAGS)]
        if df.empty:
            return []
        df['date'] = pd.to_datetime(df['date'])

        # Riferimento = ultima data presente nei dati (freshness), non oggi
        try:
            ref = pd.to_datetime(self.con.execute("SELECT max(date) FROM transactions").fetchone()[0])
        except Exception:
            ref = df['date'].max()

        rec = self.get_recurring()
        rec_names = ' '.join(rec['name'].astype(str).str.lower().tolist()) if not rec.empty else ''
        ignored = set(str(t).lower() for t in
                      (self.rules_engine.rules.get('ignored_subscription_suggestions', []) or []))
        main_wallet = self.get_main_wallet() or 'Contanti'

        suggestions = []
        for tag, g in df.groupby('tag'):
            if tag in ignored:
                continue
            if tag and tag in rec_names:      # già configurato (match sottostringa)
                continue
            g = g.sort_values('date')
            if len(g) < min_payments:
                continue
            dates = list(g['date'])
            intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            recent = intervals[-4:]
            med = int(statistics.median(recent)) if recent else 30
            days_since = (ref - dates[-1]).days

            if med > 150:
                freq = 'Yearly'
            elif med < 12:
                freq = 'Weekly'
            else:
                freq = 'Monthly'
            period = {'Yearly': 365, 'Monthly': 30, 'Weekly': 7}[freq]
            if days_since > period * 1.6 + 25:      # nessun pagamento recente = inattivo
                continue

            cat_mode = g['category'].mode()
            category = cat_mode.iloc[0] if not cat_mode.empty else 'Intrattenimento'
            suggestions.append({
                'tag': tag,
                'frequency': freq,
                'amount': round(float(abs(g['amount'].iloc[-1])), 2),
                'n': int(len(g)),
                'last': str(dates[-1].date()),
                'category': category,
                'account': main_wallet,
            })
        return sorted(suggestions, key=lambda x: x['last'], reverse=True)

    def ignore_subscription_suggestion(self, tag):
        """Marca un tag come 'da non suggerire più' (persistito in rules.yaml)."""
        rules = self.rules_engine.rules
        lst = rules.get('ignored_subscription_suggestions', []) or []
        if tag not in lst:
            lst.append(tag)
        rules['ignored_subscription_suggestions'] = lst
        self.rules_engine.save_rules(rules)
        return True

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

    def ingest_zip(self, zip_path, respect_existing_category=True):
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
                            self._process_and_insert(df, filename,
                                                     respect_existing_category=respect_existing_category)
                            count += 1
                            
            return True, f"Imported {count} files. Skipped {skipped} duplicates."
        except Exception as e:
            return False, str(e)

    def _process_and_insert(self, df, filename, respect_existing_category=True):
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

        # Apply Rules Engine (di default rispetta le categorie già presenti nel file)
        df = self.rules_engine.apply_rules(df, respect_existing_category=respect_existing_category)
        
        # --- Smart Import: Learn from History ---
        try:
             # Fetch history efficiently (description and category)
             history_df = self.con.execute("SELECT description, category FROM transactions WHERE category IS NOT NULL").df()
             self.rules_engine.learn_from_history(history_df)
             df = self.rules_engine.apply_history_rules(df)
        except Exception as e:
             print(f"Smart Import Error: {e}")
             
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

    def get_tag_category_inconsistencies(self):
        """
        Per ogni tag (sulle spese) elenca le categorie in cui compare, con conteggio
        e totale. Utile a scovare spese categorizzate male (es. tag 'piscina' che
        compare sotto 'Trasporti').
        Ritorna un DataFrame [tag, category, n, tot].
        """
        try:
            return self.con.execute("""
                SELECT tag, category, COUNT(*) AS n, SUM(ABS(amount)) AS tot
                FROM (
                    SELECT unnest(tags) AS tag, category, amount
                    FROM transactions
                    WHERE type = 'Expense'
                ) t
                WHERE tag IS NOT NULL AND tag != ''
                GROUP BY tag, category
            """).df()
        except Exception:
            return pd.DataFrame(columns=['tag', 'category', 'n', 'tot'])

    def reassign_category_by_tag(self, tag, target_category, only_from_category=None):
        """
        Assegna `target_category` a tutte le transazioni che contengono `tag`
        (opzionalmente solo quelle attualmente in `only_from_category`).
        Aggiorna anche la necessità in base alla nuova categoria.
        Ritorna il numero di transazioni corrette.
        """
        if not tag or not target_category:
            return 0

        where = "list_contains(tags, ?)"
        where_params = [tag]
        if only_from_category:
            where += " AND category = ?"
            where_params.append(only_from_category)

        cnt = self.con.execute(
            f"SELECT count(*) FROM transactions WHERE {where}", where_params
        ).fetchone()[0]
        if cnt == 0:
            return 0

        self.con.execute(
            f"UPDATE transactions SET category = ? WHERE {where}",
            [target_category] + where_params
        )
        # Allinea la necessità alla nuova categoria (+ eventuale regola sul tag)
        nec = self._necessity_from_rules(target_category, [tag])
        self.con.execute(
            f"UPDATE transactions SET necessity = ? WHERE {where}",
            [nec] + where_params
        )
        return cnt

    def get_potential_duplicates(self):
        """
        Ritorna le transazioni che appartengono a gruppi con stessa data, importo e
        descrizione (probabili doppie importazioni). Colonne utili + id.
        """
        try:
            return self.con.execute("""
                WITH grp AS (
                    SELECT date, amount, description, COUNT(*) AS n
                    FROM transactions
                    GROUP BY date, amount, description
                    HAVING COUNT(*) > 1
                )
                SELECT t.id, t.date, t.amount, t.description, t.category,
                       t.account, array_to_string(t.tags, ', ') AS tags, t.source_file
                FROM transactions t
                JOIN grp g
                  ON t.date IS NOT DISTINCT FROM g.date
                 AND t.amount IS NOT DISTINCT FROM g.amount
                 AND t.description IS NOT DISTINCT FROM g.description
                ORDER BY t.date DESC, t.amount, t.description
            """).df()
        except Exception:
            return pd.DataFrame(columns=['id', 'date', 'amount', 'description',
                                         'category', 'account', 'tags', 'source_file'])

    def delete_transactions(self, ids):
        """Elimina le transazioni con gli id forniti. Ritorna il numero eliminato."""
        ids = [i for i in (ids or []) if i]
        if not ids:
            return 0
        placeholders = ','.join(['?'] * len(ids))
        self.con.execute(
            f"DELETE FROM transactions WHERE id IN ({placeholders})", ids
        )
        return len(ids)

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

    def get_frequent_combos(self, limit=8, half_life_days=30):
        """
        Combinazioni (categoria, tag) da usare come scorciatoie di inserimento rapido,
        dato che la maggior parte delle spese è identificata da categoria+tag più che
        dalla descrizione.

        Il ranking è DINAMICO e pesato sulla recency: ogni transazione conta
        0.5 ** (giorni_fa / half_life_days), quindi emergono le combinazioni usate
        di recente (es. il supermercato o il locale dove vai in questo periodo).
        L'importo tipico è la mediana degli ultimi utilizzi.
        Ritorna DataFrame [category, tag, n, amt, last, score].
        """
        try:
            df = self.con.execute("""
                SELECT category, unnest(tags) AS tag, date, abs(amount) AS amt
                FROM transactions
                WHERE type = 'Expense'
                  AND (source_file IS NULL OR source_file NOT IN ('Recurring', 'reconcile'))
            """).df()
        except Exception:
            return pd.DataFrame(columns=['category', 'tag', 'n', 'amt', 'last', 'score'])
        if df.empty:
            return pd.DataFrame(columns=['category', 'tag', 'n', 'amt', 'last', 'score'])

        # Esclude i tag tecnici delle ricorrenti/aggiustamenti
        _skip_tags = {'recurring', 'initial', 'adjustment'}
        df = df[df['tag'].notna() & (df['tag'].astype(str) != '') & df['category'].notna()]
        df = df[~df['tag'].astype(str).str.lower().isin(_skip_tags)]
        if df.empty:
            return pd.DataFrame(columns=['category', 'tag', 'n', 'amt', 'last', 'score'])

        df['date'] = pd.to_datetime(df['date'])
        ref = df['date'].max()
        age = (ref - df['date']).dt.days.clip(lower=0)
        df['w'] = 0.5 ** (age / float(half_life_days))

        # importo tipico = mediana degli ultimi ~5 utilizzi della combinazione
        def _recent_median(g):
            return g.sort_values('date').tail(5)['amt'].median()

        grp = df.groupby(['category', 'tag'])
        agg = grp.agg(score=('w', 'sum'), n=('w', 'size'), last=('date', 'max')).reset_index()
        med = grp.apply(_recent_median).reset_index(name='amt')
        out = agg.merge(med, on=['category', 'tag'], how='left')
        out = out.sort_values('score', ascending=False).head(limit).reset_index(drop=True)
        return out[['category', 'tag', 'n', 'amt', 'last', 'score']]

    def suggest_budgets(self):
        """
        Suggerisce un budget mensile per categoria = mediana della spesa mensile
        (arrotondata a 10€), escludendo movimenti interni. Ritorna {categoria: importo}.
        """
        try:
            df = self.con.execute("""
                SELECT category, date_trunc('month', date) AS m, SUM(abs(amount)) AS tot
                FROM transactions
                WHERE type = 'Expense' AND category IS NOT NULL
                GROUP BY category, m
            """).df()
        except Exception:
            return {}
        if df.empty:
            return {}
        skip = {'trasferimento', 'adjustment', 'initial balance', 'saldo iniziale'}
        out = {}
        for cat, g in df.groupby('category'):
            if str(cat).lower() in skip:
                continue
            med = g['tot'].median()
            if med and med > 0:
                out[cat] = int(round(med / 10) * 10)
        return out

    def get_unique_accounts(self):
        try:
            res = self.con.execute("SELECT DISTINCT account FROM transactions WHERE account IS NOT NULL ORDER BY 1").fetchall()
            return [r[0] for r in res if r[0]]
        except:
            return []

    # --- Main Wallet (Portafoglio Principale) ---
    def get_main_wallet(self):
        """
        Returns the configured main wallet. Falls back to the most-used account
        if none is set (or the saved one no longer exists).
        """
        accounts = self.get_unique_accounts()
        wallet = self.rules_engine.rules.get('main_wallet')
        if wallet and wallet in accounts:
            return wallet
        # Fallback: most frequently used account
        try:
            res = self.con.execute(
                "SELECT account FROM transactions WHERE account IS NOT NULL "
                "GROUP BY account ORDER BY COUNT(*) DESC LIMIT 1"
            ).fetchone()
            if res and res[0]:
                return res[0]
        except Exception:
            pass
        return accounts[0] if accounts else None

    def set_main_wallet(self, name):
        """Persists the main wallet choice into rules.yaml."""
        rules = self.rules_engine.rules
        rules['main_wallet'] = name
        self.rules_engine.save_rules(rules)
        return True

    def add_transaction(self, date, amount, ttype, category, account,
                        description='', tags=None, necessity=None,
                        currency='EUR', apply_rules=True):
        """
        Insert a single manual transaction.

        `amount` must be positive; the correct sign is applied based on `ttype`
        ('Expense' -> negative, otherwise positive).

        When `apply_rules` is True the categorization/necessity/auto-tag rules run
        to *enrich* the entry WITHOUT overriding explicit choices:
          - category: kept if provided; otherwise filled by description rules /
            learned history.
          - tags: user tags are kept and merged with rule/keyword tags.
          - necessity: if None ("Auto") it is derived from the final category and
            tags via the necessity rules; an explicit 'Need'/'Want' is kept.
        """
        if tags is None:
            tags = []
        tags = list(tags)
        amt = abs(float(amount))
        if ttype == 'Expense':
            amt = -amt

        user_category = category if (category and category != 'Generale') else None
        final_category = user_category
        final_tags = list(tags)
        final_necessity = necessity  # None => "Auto"

        if apply_rules:
            try:
                row = pd.DataFrame([{
                    'description': description or '',
                    'original_description': description or '',
                    'category': user_category,
                    'tags': list(tags),
                    'necessity': 'Want',
                    'type': ttype,
                    'amount': amt,
                }])
                enriched = self.rules_engine.apply_rules(row.copy())
                enriched = self.rules_engine.auto_tag_from_description(enriched)
                # History-based category suggestion for still-missing category
                try:
                    hist = self.con.execute(
                        "SELECT description, category FROM transactions WHERE category IS NOT NULL"
                    ).df()
                    self.rules_engine.learn_from_history(hist)
                    enriched = self.rules_engine.apply_history_rules(enriched)
                except Exception:
                    pass

                e = enriched.iloc[0]
                # Category: keep explicit user choice, else rule/history result
                if not final_category:
                    cat = e.get('category')
                    final_category = cat if (isinstance(cat, str) and cat) else None
                # Tags: merge user + rule/keyword tags, dedupe preserving order
                rule_tags = e.get('tags')
                if hasattr(rule_tags, 'tolist'):
                    rule_tags = rule_tags.tolist()
                if not isinstance(rule_tags, list):
                    rule_tags = []
                final_tags = list(dict.fromkeys(list(tags) + rule_tags))
            except Exception:
                pass

        if not final_category:
            final_category = 'Generale'

        # Necessity: explicit wins; otherwise derive from rules (category + tags)
        if final_necessity is None:
            final_necessity = self._necessity_from_rules(final_category, final_tags)

        self.con.execute("""
            INSERT INTO transactions
                (id, date, amount, currency, account, category, tags, description,
                 type, source_file, original_description, necessity)
            VALUES (uuid(), ?, ?, ?, ?, ?, ?, ?, ?, 'manual_entry', ?, ?)
        """, [date, amt, currency, account, final_category, final_tags, description,
              ttype, description, final_necessity])
        return True

    def _necessity_from_rules(self, category, tags):
        """Derives Need/Want from category & tag necessity rules (defaults to Want)."""
        rules = self.rules_engine.rules
        cat_nec_map = {
            r['name']: r['necessity']
            for r in rules.get('categories', []) if r.get('necessity')
        }
        cat_nec_map.update(rules.get('category_necessity', {}))
        necessity = cat_nec_map.get(category, 'Want')
        tag_nec_map = rules.get('tag_necessity', {})
        for t in (tags or []):
            if t in tag_nec_map:
                necessity = tag_nec_map[t]
        return necessity

    def merge_category(self, source, target, update_rules=True):
        """
        Sposta tutte le transazioni (e ricorrenti) dalla categoria `source` alla
        categoria `target`. La categoria `source` sparisce.

        Se `update_rules` è True ripunta anche la configurazione (rules.yaml):
          - la regola di categorizzazione per keyword viene rinominata su `target`
            (o le sue keyword unite a quelle di una regola `target` esistente),
            così i FUTURI import vanno nella categoria giusta;
          - la mappa necessità e gli eventuali budget vengono spostati su `target`.

        Ritorna il numero di transazioni spostate.
        """
        if not source or not target or source == target:
            return 0

        moved = self.con.execute(
            "SELECT count(*) FROM transactions WHERE category = ?", [source]
        ).fetchone()[0]
        self.con.execute(
            "UPDATE transactions SET category = ? WHERE category = ?", [target, source]
        )
        try:
            self.con.execute(
                "UPDATE recurring_expenses SET category = ? WHERE category = ?",
                [target, source]
            )
        except Exception:
            pass

        if update_rules:
            rules = self.rules_engine.rules or {}
            cats = rules.get('categories', []) or []
            src_rule = next((c for c in cats if c.get('name') == source), None)
            tgt_rule = next((c for c in cats if c.get('name') == target), None)
            if src_rule:
                if tgt_rule:
                    # Unisci le keyword nella regola destinazione (dedup, ordine preservato)
                    merged = list(dict.fromkeys(
                        (tgt_rule.get('match') or []) + (src_rule.get('match') or [])
                    ))
                    tgt_rule['match'] = merged
                    cats.remove(src_rule)
                else:
                    # Nessuna regola destinazione: rinomina quella di origine
                    src_rule['name'] = target
                rules['categories'] = cats

            cn = rules.get('category_necessity', {}) or {}
            if source in cn:
                cn.setdefault(target, cn.pop(source))
                rules['category_necessity'] = cn

            bud = rules.get('budgets', {}) or {}
            if source in bud:
                bud[target] = float(bud.get(target, 0) or 0) + float(bud.pop(source) or 0)
                rules['budgets'] = bud

            self.rules_engine.save_rules(rules)

        return moved

    def update_tag(self, old_tag, new_tag):
        """
        Updates a tag across all transactions.
        If new_tag is provided, replaces old_tag with new_tag.
        If new_tag is None or empty, removes old_tag.
        """
        try:
            # DuckDB list manipulation
            # We can use list_transform or similar, but simplified:
            # 1. Provide a User Defined Function (UDF) or use a complex update query.
            # DuckDB's list functions are powerful.
            # "UPDATE transactions SET tags = list_transform(tags, x -> CASE WHEN x = ? THEN ? ELSE x END) WHERE list_contains(tags, ?)"
            
            # Case 1: Rename (Replace)
            if new_tag:
                # Check if we are merging (i.e. if new_tag already exists in the list, we should remove array duplicates)
                # But simple replace is:
                q = """
                    UPDATE transactions 
                    SET tags = list_distinct(list_transform(tags, x -> CASE WHEN x = ? THEN ? ELSE x END))
                    WHERE list_contains(tags, ?)
                """
                self.con.execute(q, [old_tag, new_tag, old_tag])
                
                # Also update recurring expenses
                q_rec = """
                    UPDATE recurring_expenses 
                    SET tags = list_distinct(list_transform(tags, x -> CASE WHEN x = ? THEN ? ELSE x END))
                    WHERE list_contains(tags, ?)
                """
                self.con.execute(q_rec, [old_tag, new_tag, old_tag])
                
            # Case 2: Delete
            else:
                 q = """
                    UPDATE transactions
                    SET tags = list_filter(tags, x -> x != ?)
                    WHERE list_contains(tags, ?)
                 """
                 self.con.execute(q, [old_tag, old_tag])
                 
                 q_rec = """
                    UPDATE recurring_expenses
                    SET tags = list_filter(tags, x -> x != ?)
                    WHERE list_contains(tags, ?)
                 """
                 self.con.execute(q_rec, [old_tag, old_tag])
                 
            return True, f"Updated tag '{old_tag}' to '{new_tag}'"
        except Exception as e:
            return False, str(e)
