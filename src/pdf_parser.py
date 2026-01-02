import pdfplumber
import re
import datetime
from src.utils import clean_currency

class PDFParser:
    def extract_bill_data(self, pdf_file):
        """
        Extracts bill data (date, amount, type) from a PDF file stream.
        """
        text = ""
        try:
            with pdfplumber.open(pdf_file) as pdf:
                # Usually bill summary is on first page
                if len(pdf.pages) > 0:
                    text = pdf.pages[0].extract_text()
        except Exception as e:
            return {"error": f"Failed to read PDF: {e}"}

        if not text:
            return {"error": "No text found in PDF"}

        text_lower = text.lower()
        
        # 1. Determine Type (Gas/Luce)
        bill_type = "Generic Bill"
        if "gas" in text_lower:
            bill_type = "Gas"
        elif "luce" in text_lower or "energia" in text_lower or "elettrica" in text_lower:
            bill_type = "Luce"
        elif "acqua" in text_lower or "idrico" in text_lower:
            bill_type = "Acqua"
        elif "internet" in text_lower or "telecom" in text_lower or "tim" in text_lower or "vodafone" in text_lower:
            bill_type = "Internet"

        # 2. Extract Date
        # patterns: "data emissione dd/mm/yyyy", "del dd/mm/yyyy"
        # date pattern: \d{2}/\d{2}/\d{4}
        date_pattern = r"(\d{2}[/-]\d{2}[/-]\d{4})"
        found_dates = re.findall(date_pattern, text)
        
        bill_date = datetime.date.today() # Default to today if not found
        if found_dates:
            # Usually the first date mentions validity or emission
            try:
                # Try simple parsing of first found date
                import pandas as pd
                bill_date = pd.to_datetime(found_dates[0], dayfirst=True).date()
            except:
                pass

        # 3. Extract Amount
        # Look for "Totale da pagare", "Importo totale" followed by currency
        # Or just find all currency-like patterns and take the max? (risky but often works for total)
        # Regex for Euro amount: \d+[.,]\d{2}
        
        # Strategy: Search specific keywords first
        amount = 0.0
        
        # Keywords window search could be better but let's try finding all numbers
        # that look like currency near keywords
        
        # Regex to capture 123,45 or 123.45 (European often uses comma)
        # We need to be careful not to capture dates or phone numbers
        # Look for "€" followed/preceded by number?
        
        # Simple heuristic: "Totale ... € XX,XX"
        
        # Regex for amounts: 1.234,56 or 1234,56
        amount_pattern = r"(\d{1,3}(?:\.\d{3})*,\d{2})|(\d+\.\d{2})"
        
        # Let's find all probable amounts
        amounts = []
        for match in re.finditer(amount_pattern, text):
            val_str = match.group(0)
            val = clean_currency(val_str)
            if val > 0 and val < 10000: # Sanity check
                amounts.append(val)
                
        # If keywords exist, limit search?
        # "Totale da pagare"
        keyword_amount = 0.0
        if "totale da pagare" in text_lower or "importo totale" in text_lower:
            # Try to grab the number immediately after?
            pass
            
        # Fallback: Take the largest amount found (often the total is the max value on page)
        if amounts:
            amount = max(amounts)
            
        return {
            "date": bill_date,
            "amount": -abs(amount), # Expense is negative
            "type": "Expense",
            "category": "Bills",
            "description": f"Bolletta {bill_type}",
            "tags": [bill_type.lower(), "bill"],
            "bill_type": bill_type 
        }
