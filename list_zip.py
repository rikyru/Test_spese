import zipfile
zip_path = "d:/Test_spese/riccardoyourexportisready (1).zip"
with zipfile.ZipFile(zip_path, 'r') as z:
    print(z.namelist())
