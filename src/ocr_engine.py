import re
import datetime

class OCREngine:
    def __init__(self):
        self.reader = None

    def _get_reader(self):
        """Lazy load the reader to save RAM when not in use."""
        if self.reader is None:
            import easyocr
            # Initialize for Italian and English
            # gpu=False to be safe on generic hardware, or True if available (auto)
            # We'll let it auto-detect or force CPU if safe. 
            # safe assumption: use CPU or let library decide, but catch errors.
            print("Loading EasyOCR model... (this may take a moment)")
            self.reader = easyocr.Reader(['it', 'en']) 
        return self.reader

    def extract_transaction_data(self, image_bytes):
        """
        Parses an image and returns a list of proposed transactions.
        Returns: (transactions, raw_text_lines)
        """
        reader = self._get_reader()
        
        # detail=0 returns just text list
        # paragraph=False returns distinct lines which might be better for this split logic?
        # The user's output looks like distinct lines.
        # Let's stick to paragraph=True but rely on the list order.
        # If paragraph=True groups them weirdly, we might want detail=0. 
        # But let's trust the user's list implies sequential processing works.
        results = reader.readtext(image_bytes, paragraph=True) 
        
        transactions = []
        raw_text_lines = []
        
        current_date = datetime.date.today() 
        pending_desc = None
        
        # Regex tools
        # 1. Date: "7 feb", "ieri", "oggi"
        # 2. Time: "14:28", "12*35" (OCR noise)
        time_re = re.compile(r'\d{1,2}[:*.,]\d{2}\b')
        
        # 3. Amount: looks for number with comma/dot, maybe preceded by -, ~, or nothing
        # We allow "49,90", "~35,97", "-13,95"
        # We want to capture the number and the potential sign
        amount_re = re.compile(r'([~-]?)\s*(\d+[.,]\d{2})\s*€?')
        
        ignore_terms = ["transazioni", "totale", "spese", "entrate", "febbraio", "gennaio", "dicembre"]
        
        for (bbox, text) in results:
            text = text.strip()
            raw_text_lines.append(text)
            text_lower = text.lower()
            
            # --- 1. Cleanup Text ---
            # Remove "Transazioni", Month headers if standalone
            if text_lower in ignore_terms:
                continue
                
            # --- 2. Check for Date ---
            is_date = False
            if text_lower == "oggi":
                current_date = datetime.date.today()
                is_date = True
            elif text_lower == "ieri":
                current_date = datetime.date.today() - datetime.timedelta(days=1)
                is_date = True
            else:
                 # Try "7 feb"
                months = {
                    'gen': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mag': 5, 'giu': 6,
                    'lug': 7, 'ago': 8, 'set': 9, 'ott': 10, 'nov': 11, 'dic': 12
                }
                date_match = re.search(r'(\d{1,2})\s+([a-z]{3})', text_lower)
                if date_match:
                    try:
                        month_str = date_match.group(2)
                        if month_str in months:
                            day = int(date_match.group(1))
                            year = datetime.date.today().year
                            current_date = datetime.date(year, months[month_str], day)
                            is_date = True
                    except:
                        pass

            if is_date:
                # If we found a date, the previous "pending_desc" is invalid (orphan)
                pending_desc = None 
                continue

            # --- 3. Check for Amount ---
            # Look for amount strictly?
            # Clean text of spaces for regex check
            # "49,90 €" -> "49,90€"
            clean_text = text.replace(" ", "")
            amt_match = amount_re.search(clean_text) or amount_re.search(text)
            
            if amt_match:
                # It is an amount line!
                # Group 1: sign (~ or - or empty)
                # Group 2: digits
                
                sign_char = amt_match.group(1)
                val_str = amt_match.group(2).replace(',', '.')
                val = float(val_str)
                
                # Logic for sign
                # If explicit minus or tilde, it's negative
                if '-' in sign_char or '~' in sign_char:
                    val = -abs(val)
                else:
                    # If no sign, assume negative (Expense) for list
                    val = -abs(val)
                    
                # Is it a Daily Total?
                # Heuristic: If we don't have a pending description, 
                # OR if the line contains a Month Name (header), treat as header.
                # In the logs: "7 feb" (Date) -> "-73,69 €"
                if pending_desc is None:
                    # Likely a daily total or list header, skip
                    continue
                    
                # We have a Pair!
                # pending_desc is "Amazon 14:28"
                
                # Cleanup Description
                # Remove time "14:28"
                final_desc = time_re.sub('', pending_desc).strip()
                # Remove extra chars
                final_desc = final_desc.replace('*', '').strip()
                
                if len(final_desc) > 1:
                    transactions.append({
                        'date': current_date.isoformat(),
                        'description': final_desc,
                        'amount': val,
                        'source': 'ocr_screenshot',
                        'raw_text': f"{pending_desc} | {text}" 
                    })
                
                # Consume pending_desc
                pending_desc = None
                
            else:
                # --- 4. It's properly text (Description) ---
                # Check it's not just "Febbraio 2025" or something
                # We handled ignore_terms but complex headers?
                
                # Filter out pure months "dicembre 2025"
                if re.match(r'^[a-z]+ \d{4}$', text_lower):
                    continue
                    
                # Save as pending description
                pending_desc = text

        return transactions, raw_text_lines

