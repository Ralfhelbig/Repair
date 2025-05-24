# database_setup.py - Applying Schema v8 (Artikelnummer, ZIR Reference)
import sqlite3
import os
import sys

DATABASE = 'inventory.db'
DB_SCHEMA_VERSION = 8 # Target schema version

# --- Database Connection Function ---
def get_db_connection():
    """Establishes a connection to the database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

# --- Schema Version Functions ---
def get_schema_version(conn):
    """Gets the current schema version."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version FROM schema_version LIMIT 1")
        result = cursor.fetchone()
        return result['version'] if result else 0
    except sqlite3.Error: # Table 'schema_version' might not exist
        return 0

def set_schema_version(conn, version):
    """Sets the schema version."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS schema_version")
    cursor.execute("CREATE TABLE schema_version (version INTEGER)")
    cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()

# --- Helper to check if column exists ---
def column_exists(cursor, table_name, column_name):
    """Checks if a column exists in a table."""
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row['name'] for row in cursor.fetchall()]
        return column_name in columns
    except sqlite3.Error as e:
        print(f"Error checking column {column_name} in {table_name}: {e}")
        return False # Assume it doesn't exist on error


# --- Functions to apply each schema version ---

def apply_schema_v6(cursor, conn, current_version):
    """Applies changes for Serialized Inventory model (Schema v6)."""
    print("Applying schema version 6 (Serialized Inventory)...")
    # --- 1. Create/Recreate part_types (replaces parts table) ---
    try:
        print("Processing 'part_types' table (v6)...")
        old_table_name_to_migrate = None
        if current_version >= 2:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parts'")
            if cursor.fetchone(): old_table_name_to_migrate = 'parts'

        temp_table_name = None
        if old_table_name_to_migrate:
            temp_table_name = f"part_types_old_v{current_version}"
            print(f"Renaming '{old_table_name_to_migrate}' to '{temp_table_name}'...")
            cursor.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
            cursor.execute(f"ALTER TABLE {old_table_name_to_migrate} RENAME TO {temp_table_name}")

        cursor.execute("DROP TABLE IF EXISTS part_types")
        cursor.execute('''
        CREATE TABLE part_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT, part_name TEXT NOT NULL, part_number TEXT UNIQUE,
            part_type TEXT, brand TEXT, model TEXT, cost_price REAL, storage_location TEXT,
            description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        )''')

        if temp_table_name:
            print(f"Copying data from {temp_table_name} to new 'part_types' table...")
            v_old_columns = "id, part_name, part_number, part_type, brand, model, cost_price, storage_location"
            v_new_columns = "id, part_name, part_number, part_type, brand, model, cost_price, storage_location"
            try:
                 cursor.execute(f'INSERT INTO part_types ({v_new_columns}) SELECT {v_old_columns} FROM {temp_table_name}')
                 conn.commit()
                 cursor.execute(f"DROP TABLE {temp_table_name}")
                 print(f"Dropped temporary table {temp_table_name}.")
            except sqlite3.Error as copy_error:
                 print(f"!!! WARNING: Error copying data from {temp_table_name}: {copy_error}. Manual migration might be needed. {temp_table_name} kept.")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pt_name ON part_types (part_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pt_number ON part_types (part_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pt_brand_model ON part_types (brand, model);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pt_type ON part_types (part_type);")
        print("'part_types' table created/updated (v6).")
    except sqlite3.Error as e: print(f"Error with 'part_types' table (v6): {e}"); raise

    # --- 2. Create stock_orders table ---
    try:
        print("Creating 'stock_orders' table (v6)...")
        cursor.execute("DROP TABLE IF EXISTS stock_orders")
        cursor.execute('''CREATE TABLE stock_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, order_number TEXT, order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, notes TEXT )''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_order_number ON stock_orders (order_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_order_date ON stock_orders (order_date);")
        print("'stock_orders' table created.")
    except sqlite3.Error as e: print(f"Error creating 'stock_orders': {e}"); raise

    # --- 3. Create inventory_items table ---
    try:
        print("Creating 'inventory_items' table (v6)...")
        cursor.execute("DROP TABLE IF EXISTS inventory_items")
        cursor.execute('''
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, part_type_id INTEGER NOT NULL, serial_number TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'Available', stock_order_line_id INTEGER, current_location TEXT,
            date_received TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, notes TEXT,
            FOREIGN KEY (part_type_id) REFERENCES part_types (id) ON DELETE RESTRICT,
            FOREIGN KEY (stock_order_line_id) REFERENCES stock_order_lines (id) ON DELETE SET NULL )
        ''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitem_parttype_status ON inventory_items (part_type_id, status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitem_serial ON inventory_items (serial_number);")
        print("'inventory_items' table created.")
    except sqlite3.Error as e: print(f"Error creating 'inventory_items': {e}"); raise

    # --- 4. Create stock_order_lines table ---
    try:
        print("Creating 'stock_order_lines' table (v6)...")
        cursor.execute("DROP TABLE IF EXISTS stock_order_lines")
        cursor.execute('''
        CREATE TABLE stock_order_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, stock_order_id INTEGER NOT NULL, part_id INTEGER NOT NULL,
            quantity_received INTEGER NOT NULL, cost_price_per_unit REAL,
            FOREIGN KEY (stock_order_id) REFERENCES stock_orders (id) ON DELETE CASCADE,
            FOREIGN KEY (part_id) REFERENCES part_types (id) ON DELETE RESTRICT )
        ''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_line_order_part ON stock_order_lines (stock_order_id, part_id);")
        print("'stock_order_lines' table created.")
    except sqlite3.Error as e: print(f"Error creating 'stock_order_lines': {e}"); raise

    # --- 5. Create booking_parts_used table ---
    try:
        print("Creating 'booking_parts_used' table (v6)...")
        cursor.execute("DROP TABLE IF EXISTS booking_parts_used")
        cursor.execute('''
        CREATE TABLE booking_parts_used (
            id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL, inventory_item_id INTEGER NOT NULL,
            date_assigned TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE CASCADE,
            FOREIGN KEY (inventory_item_id) REFERENCES inventory_items (id) ON DELETE RESTRICT )
        ''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bpu_booking_item ON booking_parts_used (booking_id, inventory_item_id);")
        print("'booking_parts_used' table created.")
    except sqlite3.Error as e: print(f"Error creating 'booking_parts_used': {e}"); raise

    # --- 6. Ensure bookings table exists with gpc_number ---
    try:
        print("Ensuring 'bookings' table structure (v6)...")
        needs_bookings_update = True
        bookings_existed = False
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookings'")
        if cursor.fetchone():
            bookings_existed = True
            if column_exists(cursor, 'bookings', 'gpc_number'):
                print("'bookings' table already has 'gpc_number'. Skipping recreation for v6.")
                needs_bookings_update = False
            else:
                print("'bookings' table found but missing 'gpc_number'. Recreating for v6...")
        else:
            print("'bookings' table not found. Creating for v6...")

        if needs_bookings_update:
            if bookings_existed:
                 cursor.execute("DROP TABLE IF EXISTS bookings_old_v6_temp")
                 cursor.execute("ALTER TABLE bookings RENAME TO bookings_old_v6_temp")

            cursor.execute("DROP TABLE IF EXISTS bookings") # Drop just in case
            cursor.execute('''
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                customer_name TEXT NOT NULL, customer_phone TEXT, device_model TEXT NOT NULL,
                device_serial TEXT, gpc_number TEXT, reported_issue TEXT NOT NULL,
                status TEXT DEFAULT 'Booked In' NOT NULL, notes TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL )
            ''')
            if bookings_existed:
                 print("Copying data to new 'bookings' table (v6)...")
                 cols_to_copy = "id, booking_date, customer_name, customer_phone, device_model, device_serial, reported_issue, status, notes, last_updated"
                 try:
                     cursor.execute(f'INSERT INTO bookings ({cols_to_copy}) SELECT {cols_to_copy} FROM bookings_old_v6_temp')
                     cursor.execute("DROP TABLE bookings_old_v6_temp")
                     print("Data copied, old v6 table dropped.")
                 except sqlite3.Error as e_copy_book:
                     print(f"!!! Warning: Failed to copy bookings data during v6 upgrade: {e_copy_book}. Old table kept.")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_date ON bookings (booking_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_customer_name ON bookings (customer_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_status ON bookings (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_gpc_number ON bookings (gpc_number);")
            print("'bookings' table created/updated (v6).")
    except sqlite3.Error as e: print(f"Error ensuring bookings table structure (v6): {e}"); raise e

    set_schema_version(conn, 6)
    print("Schema version set to 6.")
    return 6


def apply_schema_v7(cursor, conn, current_version):
    """Applies changes for adding artikelnummer (Schema v7)."""
    print("Applying schema version 7 (Adding artikelnummer to part_types)...")
    try:
        if not column_exists(cursor, 'part_types', 'artikelnummer'):
            print("Adding 'artikelnummer' column to 'part_types' table...")
            cursor.execute("ALTER TABLE part_types ADD COLUMN artikelnummer TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pt_artikelnummer ON part_types (artikelnummer);")
            print("'artikelnummer' column and index added to 'part_types'.")
        else:
            print("'artikelnummer' column already exists in 'part_types'.")
    except sqlite3.Error as e:
        print(f"Error adding 'artikelnummer' to 'part_types': {e}")
        raise e
    set_schema_version(conn, 7)
    print("Schema version set to 7.")
    return 7


def apply_schema_v8(cursor, conn, current_version):
    """Applies changes for adding ZIR Reference (Schema v8)."""
    print("Applying schema version 8 (Adding ZIR Reference to Bookings)...")
    try:
        if not column_exists(cursor, 'bookings', 'zir_reference'):
            print("Adding 'zir_reference' column to 'bookings' table...")
            cursor.execute("ALTER TABLE bookings ADD COLUMN zir_reference TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_zir_reference ON bookings (zir_reference);")
            print("'zir_reference' column and index added to 'bookings'.")
        else:
            print("'zir_reference' column already exists in 'bookings'.")
    except sqlite3.Error as e:
        print(f"Error adding 'zir_reference' to 'bookings': {e}")
        raise e
    set_schema_version(conn, 8)
    print("Schema version set to 8.")
    return 8


# --- Main Initialization Function ---
def init_db():
    """Initializes or updates the database schema sequentially."""
    print(f"--- Database Setup Start (DB: {DATABASE}) ---")
    if not os.path.exists(DATABASE):
        print(f"Database file '{DATABASE}' not found, will be created.")

    conn = None
    try:
        conn = get_db_connection()
        current_version = get_schema_version(conn)
        print(f"Current DB schema version: {current_version}. Required: {DB_SCHEMA_VERSION}")

        if current_version >= DB_SCHEMA_VERSION:
            print("Database schema is already up to date or newer.")
            return

        cursor = conn.cursor()
        original_fk_setting = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
        if original_fk_setting == 1 : cursor.execute("PRAGMA foreign_keys = OFF")

        cursor.execute("BEGIN TRANSACTION")
        print("BEGIN schema migration transaction.")
        try:
            # --- Apply Necessary Schema Updates Sequentially ---
            if current_version < 6:
                print(f"Attempting upgrade from version {current_version} to 6...")
                current_version = apply_schema_v6(cursor, conn, current_version)

            if current_version == 6 and DB_SCHEMA_VERSION >= 7:
                 print(f"Attempting upgrade from version {current_version} to 7...")
                 current_version = apply_schema_v7(cursor, conn, current_version)

            if current_version == 7 and DB_SCHEMA_VERSION >= 8:
                 print(f"Attempting upgrade from version {current_version} to 8...")
                 current_version = apply_schema_v8(cursor, conn, current_version)

            # Add future 'if current_version < 9:' blocks here

            # --- Commit or Rollback ---
            if current_version == DB_SCHEMA_VERSION:
                cursor.execute("COMMIT")
                print("Schema migration transaction COMMITTED.")
            else:
                print(f"Migration did not reach target version ({DB_SCHEMA_VERSION}). Actual: {current_version}. Rolling back.")
                cursor.execute("ROLLBACK")

        except Exception as e:
            print(f"!!! Schema migration FAILED: {e}")
            print("!!! Rolling back schema changes.")
            cursor.execute("ROLLBACK")
            raise # Re-raise exception to signal failure

        finally:
             if original_fk_setting == 1 : cursor.execute("PRAGMA foreign_keys = ON") # Restore FK setting

        final_version = get_schema_version(conn) # Re-check version after operations
        if final_version == DB_SCHEMA_VERSION: print("Database schema successfully updated.")
        else: print(f"Error/Warning: Update process ended. Required: {DB_SCHEMA_VERSION}, Actual: {final_version}")

    except sqlite3.Error as e: print(f"Database connection or setup error: {e}")
    except Exception as e: print(f"An unexpected error occurred during init_db: {e}")
    finally:
        if conn: conn.close(); print("Database connection closed.")
    print(f"--- Database Setup End ---")

# --- Main execution ---
if __name__ == '__main__':
    print("Running database setup...")
    init_db()