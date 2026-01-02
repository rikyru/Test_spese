import zipfile
import pandas as pd
import io

zip_path = "d:/Test_spese/riccardoyourexportisready (1).zip"

try:
    with zipfile.ZipFile(zip_path, 'r') as z:
        file_list = z.namelist()
        print(f"Files in ZIP: {file_list}")
        
        for filename in file_list:
            if filename.endswith('.csv'):
                print(f"\n--- Analyzing {filename} ---")
                with z.open(filename) as f:
                    # Read first few lines to guess separator and structure
                    head = [next(f).decode('utf-8') for _ in range(5)]
                    print("First 5 lines raw:")
                    for line in head:
                        print(line.strip())
                    
                    # Try to load with pandas
                    f.seek(0)
                    try:
                        df = pd.read_csv(f, nrows=5)
                        print("\nPandas inferred columns:")
                        print(df.columns.tolist())
                        print(df.head())
                    except Exception as e:
                        print(f"Pandas read error: {e}")

except Exception as e:
    print(f"Error opening ZIP: {e}")
