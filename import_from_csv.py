import sqlite3
import csv

DATABASE_NAME = 'inventory.db'
CSV_FILE_NAME = 'Voorraad lijst - Sheet1.csv' # Make sure this file is in the same directory as the script

def import_part_types_from_csv(db_name, csv_file_path):
    conn = None
    inserted_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Try opening with 'windows-1252' encoding
        try:
            csvfile = open(csv_file_path, mode='r', encoding='windows-1252')
            print(f"Successfully opened '{csv_file_path}' with 'windows-1252' encoding.")
        except UnicodeDecodeError:
            # Fallback to 'latin-1' if 'windows-1252' also fails
            print(f"Opening with 'windows-1252' failed. Trying 'latin-1'.")
            csvfile.close() # Close the previous attempt
            csvfile = open(csv_file_path, mode='r', encoding='latin-1')
            print(f"Successfully opened '{csv_file_path}' with 'latin-1' encoding.")
        except Exception as e_open:
            # If other error occurs during open (like FileNotFoundError before encoding is an issue)
            print(f"Error opening file '{csv_file_path}': {e_open}")
            return


        with csvfile: # Ensures the file is closed automatically
            reader = csv.DictReader(csvfile)
            for row_number, row in enumerate(reader, 1):
                try:
                    artikelnummer = row.get('Artikelnummer', '').strip()
                    gpcid = row.get('GPCID', '').strip()
                    phone_type = row.get('Phone Type', '').strip()
                    # Aantal = row.get('Aantal', '').strip() # Ignored for part_types
                    soort = row.get('Soort', '').strip()
                    merk = row.get('Merk', '').strip()

                    # Validate essential fields
                    if not artikelnummer and not gpcid: # At least one unique ID should be present
                        print(f"Row {row_number}: Skipping row due to missing Artikelnummer and GPCID. Data: {row}")
                        failed_count += 1
                        continue
                    if not phone_type or not soort or not merk:
                        print(f"Row {row_number}: Skipping row due to missing Phone Type, Soort, or Merk. Data: {row}")
                        failed_count += 1
                        continue
                    
                    # Construct part_name
                    part_name = f"{merk} {phone_type} {soort}"

                    check_sql = "SELECT id FROM part_types WHERE "
                    check_params = []
                    conditions = []

                    if artikelnummer:
                        conditions.append("artikelnummer = ?")
                        check_params.append(artikelnummer)
                    if gpcid:
                        conditions.append("part_number = ?")
                        check_params.append(gpcid)
                    
                    if not conditions: 
                         print(f"Row {row_number}: Skipping due to no valid identifiers. Data: {row}")
                         failed_count += 1
                         continue

                    check_sql += " OR ".join(conditions)
                    
                    cursor.execute(check_sql, tuple(check_params))
                    existing_part = cursor.fetchone()

                    if existing_part:
                        print(f"Row {row_number}: Skipping duplicate. Artikelnummer '{artikelnummer}' or GPCID '{gpcid}' likely already exists.")
                        skipped_count += 1
                        continue

                    insert_sql = """
                    INSERT INTO part_types 
                    (part_name, part_number, artikelnummer, part_type, brand, model)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """
                    cursor.execute(insert_sql, (
                        part_name,
                        gpcid if gpcid else None,
                        artikelnummer if artikelnummer else None,
                        soort,
                        merk,
                        phone_type
                    ))
                    inserted_count += 1

                except Exception as e:
                    print(f"Row {row_number}: Failed to process row. Error: {e}. Data: {row}")
                    failed_count += 1
        
        conn.commit()
        print(f"\nImport from CSV complete.")
        print(f"Successfully inserted: {inserted_count} new part types.")
        print(f"Skipped (duplicates or existing): {skipped_count} part types.")
        print(f"Failed (errors or missing essential data): {failed_count} part types.")

    except sqlite3.Error as e:
        print(f"SQLite error during import: {e}")
        if conn:
            conn.rollback()
    except FileNotFoundError:
        print(f"Error: The file '{csv_file_path}' was not found.")
    except UnicodeDecodeError as ude:
        print(f"UnicodeDecodeError: Could not decode the file with 'windows-1252' or 'latin-1'. The file might be saved with a different encoding. Error: {ude}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print(f"Attempting to import part types from '{CSV_FILE_NAME}' into '{DATABASE_NAME}'...")
    # IMPORTANT: Backup your database (inventory.db) before running this script!
    import_part_types_from_csv(DATABASE_NAME, CSV_FILE_NAME)