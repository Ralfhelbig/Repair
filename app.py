# app.py - Schema v8: Artikelnummer, ZIR Reference, Booking Edit, Part Type Edit
import sqlite3
import os
import sys
import datetime
from dateutil.relativedelta import relativedelta
from flask import (
    Flask, render_template, request, g, redirect, url_for, flash
)

# --- Configuration ---
DATABASE = 'inventory.db'
ALLOWED_ITEM_STATUSES = ['Available', 'Reserved', 'Installed', 'Broken', 'Returned']
PART_TYPES_CATEGORIES = ["Screen", "Battery", "Back Cover", "Charging Port", "Camera", "Adhesive", "Small Parts", "Tools", "Other"]
OLD_STOCK_THRESHOLD_MONTHS = 5
ALLOWED_BOOKING_STATUSES = ['Booked In', 'In Progress', 'Awaiting Part', 'Ready for Collection', 'Completed', 'Cancelled']
DB_SCHEMA_REQ = 8 # Required schema version for this app


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_dev_key_change_me')

# --- Database Connection Handling ---
def get_db():
    if 'db' not in g:
        try:
            g.db = sqlite3.connect(DATABASE)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as e:
            print(f"DB CONNECT ERROR: {e}", file=sys.stderr)
            g.db = None
            raise e
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except sqlite3.Error as e:
            print(f"ERROR CLOSING DB: {e}", file=sys.stderr)
    if error:
        print(f"Request teardown error: {error}", file=sys.stderr)

# --- Utility ---
def flash_errors(errors):
    for e in errors:
        flash(e, 'error')

# --- Routes ---

@app.route('/')
def index():
    items_processed = []
    brands, models, part_type_list = [], [], []
    show_old_stock_alert = False
    filter_brand = request.args.get('brand', '')
    filter_model = request.args.get('model', '')
    filter_type = request.args.get('type', '')
    filter_status = request.args.get('status', '')

    try:
        conn = get_db()
        cursor = conn.cursor()
        threshold_date_str = (datetime.datetime.now() - relativedelta(months=OLD_STOCK_THRESHOLD_MONTHS)).strftime('%Y-%m-%d %H:%M:%S')
        alert_query = """
            SELECT 1 FROM stock_orders so
            WHERE so.order_date < ? AND EXISTS (
                SELECT 1 FROM stock_order_lines sol
                JOIN inventory_items i ON sol.id = i.stock_order_line_id
                WHERE sol.stock_order_id = so.id AND i.status IN ('Available', 'Reserved')
            ) LIMIT 1;
        """
        cursor.execute(alert_query, (threshold_date_str,))
        if cursor.fetchone():
            show_old_stock_alert = True

        cursor.execute("SELECT DISTINCT brand FROM part_types WHERE brand IS NOT NULL AND brand != '' ORDER BY brand")
        brands = [row['brand'] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT model FROM part_types WHERE model IS NOT NULL AND model != '' ORDER BY model")
        models = [row['model'] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT part_type FROM part_types WHERE part_type IS NOT NULL AND part_type != '' ORDER BY part_type")
        part_type_list = [row['part_type'] for row in cursor.fetchall()]

        # Fetch order_number along with other item details
        query = """
            SELECT i.id, i.serial_number, i.status, i.current_location, i.notes, i.last_updated, i.date_received,
                   pt.part_name, pt.part_number, pt.artikelnummer, pt.brand, pt.model, pt.part_type, pt.storage_location,
                   so.order_number
            FROM inventory_items i 
            JOIN part_types pt ON i.part_type_id = pt.id
            LEFT JOIN stock_order_lines sol ON i.stock_order_line_id = sol.id
            LEFT JOIN stock_orders so ON sol.stock_order_id = so.id
            WHERE 1=1
        """
        params = []
        if filter_brand: query += " AND pt.brand = ?"; params.append(filter_brand)
        if filter_model: query += " AND pt.model = ?"; params.append(filter_model)
        if filter_type: query += " AND pt.part_type = ?"; params.append(filter_type)
        if filter_status: query += " AND i.status = ?"; params.append(filter_status)
        query += " ORDER BY pt.brand, pt.model, pt.part_name, i.id ASC"
        cursor.execute(query, params)
        items_raw = cursor.fetchall()

        now = datetime.datetime.now()
        for item_row in items_raw:
            item_dict = dict(item_row) # This will include 'order_number' if fetched
            days_in_system = 0
            date_received_str = item_dict.get('date_received')
            if date_received_str:
                try:
                    date_received_dt = datetime.datetime.strptime(date_received_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    days_in_system = (now - date_received_dt).days
                except (ValueError, TypeError) as e:
                    print(f"Warning: Could not parse date_received '{date_received_str}' for item ID {item_dict.get('id')}: {e}", file=sys.stderr)
            item_dict['days_in_system'] = days_in_system
            items_processed.append(item_dict)
    except sqlite3.Error as e:
        print(f"DB Error index: {e}", file=sys.stderr)
        flash(f"Error retrieving inventory items: {e}", "error")
    except Exception as e:
        print(f"Error index: {e}", file=sys.stderr)
        flash("An unexpected error occurred.", "error")

    return render_template('index.html',
                           items=items_processed,
                           brands=brands, models=models, part_type_list=part_type_list,
                           allowed_statuses=ALLOWED_ITEM_STATUSES,
                           current_filters={'brand': filter_brand, 'model': filter_model, 'type': filter_type, 'status': filter_status},
                           show_old_stock_alert=show_old_stock_alert,
                           OLD_STOCK_THRESHOLD_MONTHS=OLD_STOCK_THRESHOLD_MONTHS)

@app.route('/inventory/item/<int:item_id>/status', methods=['POST'])
def update_item_status(item_id):
    new_status = request.form.get('new_status')
    return_url = request.form.get('return_url', url_for('index'))
    if not new_status or new_status not in ALLOWED_ITEM_STATUSES:
        flash("Invalid status provided.", "error")
        return redirect(return_url)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE inventory_items SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?", (new_status, item_id))
        if cursor.rowcount == 0:
            flash(f"Inventory item ID {item_id} not found.", "error")
        else:
            conn.commit()
            flash(f"Status for item ID {item_id} updated to '{new_status}'.", "success")
    except sqlite3.Error as e:
        print(e, file=sys.stderr); flash(f"Database error updating status: {e}", "error")
        if conn: conn.rollback()
    except Exception as e:
        print(e, file=sys.stderr); flash(f"An unexpected error occurred: {e}", "error")
        if conn: conn.rollback()
    return redirect(return_url)

@app.route('/part_types/add', methods=['GET'])
def add_part_type_form():
    return render_template('add_part_type.html',
                           part_types_categories=PART_TYPES_CATEGORIES,
                           submitted_data={})

@app.route('/part_types/add', methods=['POST'])
def add_part_type():
    part_name = request.form.get('part_name')
    part_number = request.form.get('part_number') or None       # SKU / Manufacturer PN
    artikelnummer = request.form.get('artikelnummer') or None # Internal article number
    part_type_category = request.form.get('part_type') or None # From form field, maps to part_type in DB
    brand = request.form.get('brand') or None
    model = request.form.get('model') or None
    cost_price_str = request.form.get('cost_price')
    storage_location = request.form.get('storage_location') or None
    description = request.form.get('description') or None
    errors = []

    if not part_name: errors.append("Part Name is required.")
    cost_price = None
    if cost_price_str and cost_price_str.strip() != "":
        try:
            cost_price = float(cost_price_str)
            if cost_price < 0: errors.append("Cost price must be a non-negative number.")
        except ValueError: errors.append("Cost price must be a valid number.")
    else:
        cost_price = None


    if errors:
        flash_errors(errors)
        return render_template('add_part_type.html', part_types_categories=PART_TYPES_CATEGORIES, submitted_data=request.form), 400

    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = """INSERT INTO part_types
                 (part_name, part_number, artikelnummer, part_type, brand, model, cost_price, storage_location, description, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"""
        values = (part_name, part_number, artikelnummer, part_type_category, brand, model, cost_price, storage_location, description)
        cursor.execute(sql, values)
        conn.commit()
        flash(f"Part Type '{part_name}' added successfully!", 'success')
        return redirect(url_for('part_types_overview')) # Redirect to overview after add
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if 'part_number' in err_msg:
            flash(f"Error: Part Number (SKU/Fabrikant) '{part_number}' already exists.", 'error')
        elif 'artikelnummer' in err_msg:
             flash(f"Error: Artikelnummer '{artikelnummer}' already exists.", 'error')
        else:
            flash(f"Database integrity error: {e}", 'error')
        if conn: conn.rollback()
    except sqlite3.Error as e:
        flash(f"Database error adding part type: {e}", 'error'); print(e, file=sys.stderr)
        if conn: conn.rollback()
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", "error"); print(e, file=sys.stderr)
        if conn: conn.rollback()
    return render_template('add_part_type.html', part_types_categories=PART_TYPES_CATEGORIES, submitted_data=request.form), 500

# --- New Routes for Part Type Management ---
@app.route('/part_types/overview')
def part_types_overview():
    part_types_list = []
    try:
        conn = get_db()
        cursor = conn.cursor()
        # Fetch all relevant columns for the overview
        cursor.execute("""
            SELECT id, part_name, part_number, artikelnummer, brand, model, part_type
            FROM part_types
            ORDER BY brand, model, part_name ASC
        """)
        part_types_list = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"DB Error part_types_overview: {e}", file=sys.stderr)
        flash(f"Error retrieving part types: {e}", "error")
    except Exception as e:
        print(f"Error part_types_overview: {e}", file=sys.stderr)
        flash("An unexpected error occurred.", "error")
    return render_template('part_types_overview.html', part_types=part_types_list)

@app.route('/part_type/<int:part_type_id>/edit', methods=['GET'])
def edit_part_type_form(part_type_id):
    part_type_data = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, part_name, part_number, artikelnummer, part_type, brand, model,
                   cost_price, storage_location, description
            FROM part_types WHERE id = ?
        """, (part_type_id,))
        part_type_data = cursor.fetchone()

        if not part_type_data:
            flash(f"Part Type ID {part_type_id} not found.", "error")
            return redirect(url_for('part_types_overview'))

    except sqlite3.Error as e:
        flash(f"Error loading part type details: {e}", "error")
        return redirect(url_for('part_types_overview'))
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", "error")
        return redirect(url_for('part_types_overview'))

    return render_template('edit_part_type.html',
                           part_type=part_type_data,
                           part_types_categories=PART_TYPES_CATEGORIES)

@app.route('/part_type/<int:part_type_id>/edit', methods=['POST'])
def update_part_type(part_type_id):
    conn = get_db()
    # Fetch current part_type data to compare for uniqueness checks if needed
    try:
        cursor_check = conn.cursor()
        cursor_check.execute("SELECT part_number, artikelnummer FROM part_types WHERE id = ?", (part_type_id,))
        current_part_type = cursor_check.fetchone()
        if not current_part_type:
            flash(f"Part Type ID {part_type_id} not found for update.", "error")
            return redirect(url_for('part_types_overview'))
    except sqlite3.Error as e:
        flash(f"Database error fetching current part type: {e}", "error")
        return redirect(url_for('edit_part_type_form', part_type_id=part_type_id))


    part_name = request.form.get('part_name')
    part_number = request.form.get('part_number') or None
    artikelnummer = request.form.get('artikelnummer') or None
    part_type_category = request.form.get('part_type_category') or None # from edit_part_type.html form
    brand = request.form.get('brand') or None
    model = request.form.get('model') or None
    cost_price_str = request.form.get('cost_price')
    storage_location = request.form.get('storage_location') or None
    description = request.form.get('description') or None
    errors = []

    if not part_name:
        errors.append("Part Name is required.")

    cost_price = None
    if cost_price_str and cost_price_str.strip() != "": # Ensure it's not empty or just spaces
        try:
            cost_price = float(cost_price_str)
            if cost_price < 0:
                errors.append("Cost price must be a non-negative number.")
        except ValueError:
            errors.append("Cost price must be a valid number.")
    else: # If empty or None, set to None for DB
        cost_price = None


    if errors:
        flash_errors(errors)
        # Re-fetch part_type_data for the template if validation fails
        part_type_for_form = {**request.form, 'id': part_type_id, 'part_type': part_type_category}
        # We need to reconstruct a 'part_type' like object for the template
        # The original part_type_data might be better here, combined with request.form.
        # For simplicity, creating a dict from request.form and adding id.
        # Ensuring the 'part_type' field in the dict matches what the template expects for the dropdown.
        temp_part_type_data_for_form = {
            'id': part_type_id,
            'part_name': request.form.get('part_name'),
            'part_number': request.form.get('part_number'),
            'artikelnummer': request.form.get('artikelnummer'),
            'part_type': request.form.get('part_type_category'), # Use the form's select name
            'brand': request.form.get('brand'),
            'model': request.form.get('model'),
            'cost_price': request.form.get('cost_price'), # Will be string, template handles value attr
            'storage_location': request.form.get('storage_location'),
            'description': request.form.get('description')
        }
        return render_template('edit_part_type.html',
                               part_type=temp_part_type_data_for_form,
                               part_types_categories=PART_TYPES_CATEGORIES), 400

    try:
        cursor = conn.cursor()
        sql = """UPDATE part_types SET
                 part_name = ?, part_number = ?, artikelnummer = ?, part_type = ?,
                 brand = ?, model = ?, cost_price = ?, storage_location = ?, description = ?
                 WHERE id = ?"""
        values = (part_name, part_number, artikelnummer, part_type_category, brand, model,
                  cost_price, storage_location, description, part_type_id)
        cursor.execute(sql, values)
        conn.commit()
        flash(f"Part Type '{part_name}' (ID: {part_type_id}) updated successfully!", 'success')
        return redirect(url_for('part_types_overview'))
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        original_pn = current_part_type['part_number'] if current_part_type else None
        original_an = current_part_type['artikelnummer'] if current_part_type else None

        if 'part_number' in err_msg and (part_number != original_pn or original_pn is None):
            flash(f"Error: Part Number (SKU/Fabrikant) '{part_number}' already exists for another part type.", 'error')
        elif 'artikelnummer' in err_msg and (artikelnummer != original_an or original_an is None):
             flash(f"Error: Artikelnummer '{artikelnummer}' already exists for another part type.", 'error')
        else: # Other integrity error
            flash(f"Database integrity error: {e}", 'error')
        if conn:
            conn.rollback()
    except sqlite3.Error as e:
        flash(f"Database error updating part type: {e}", 'error')
        print(e, file=sys.stderr)
        if conn:
            conn.rollback()
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", "error")
        print(e, file=sys.stderr)
        if conn:
            conn.rollback()

    # If any error occurred, re-render the edit form with submitted values
    temp_part_type_data_for_form_error = {
        'id': part_type_id,
        'part_name': request.form.get('part_name'),
        'part_number': request.form.get('part_number'),
        'artikelnummer': request.form.get('artikelnummer'),
        'part_type': request.form.get('part_type_category'), # Use the form's select name
        'brand': request.form.get('brand'),
        'model': request.form.get('model'),
        'cost_price': request.form.get('cost_price'),
        'storage_location': request.form.get('storage_location'),
        'description': request.form.get('description')
    }
    return render_template('edit_part_type.html',
                           part_type=temp_part_type_data_for_form_error,
                           part_types_categories=PART_TYPES_CATEGORIES), 500
# --- End of New Part Type Management Routes ---


@app.route('/receive', methods=['GET'])
def receive_stock_form():
    part_types_list = []
    try:
        cursor = get_db().cursor()
        # Include artikelnummer
        cursor.execute("SELECT id, part_name, part_number, artikelnummer, brand, model FROM part_types ORDER BY brand, model, part_name ASC")
        part_types_list = cursor.fetchall()
    except sqlite3.Error as e: flash(f"Error loading part types: {e}", "error"); print(e, file=sys.stderr)
    except Exception as e: flash(f"An unexpected error occurred: {e}", "error"); print(e, file=sys.stderr)
    return render_template('receive_stock.html',
                           part_types_list=part_types_list,
                           submitted_order_number='',
                           submitted_order_date='', # Add this
                           submitted_notes='')

@app.route('/receive', methods=['POST'])
def receive_stock():
    conn = get_db()
    cursor = conn.cursor()
    items_created_count = 0
    errors = []
    lines_to_process = []
    order_number_ref = request.form.get('order_number') or None
    order_notes = request.form.get('order_notes') or None
    order_date_str = request.form.get('order_date') # Get the date string

    order_date_to_insert = None
    if order_date_str:
        try:
            # Ensure the date is in YY-MM-DD HH:MM:SS format for SQLite
            # If only date is provided, time will be 00:00:00
            dt_obj = datetime.datetime.strptime(order_date_str, '%Y-%m-%d')
            order_date_to_insert = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            errors.append("Invalid Order Date format. Please use YY-MM-DD.")
    # If order_date_str is empty, order_date_to_insert remains None, and DB will use CURRENT_TIMESTAMP

    for key, qty_received_str in request.form.items():
        if key.startswith('quantity_') and qty_received_str:
            try:
                part_type_id = int(key.split('_')[1])
                received_qty = int(qty_received_str)
                if received_qty < 0:
                    errors.append(f"Received quantity for Part Type ID {part_type_id} cannot be negative.")
                elif received_qty > 0:
                    lines_to_process.append({
                        'part_type_id': part_type_id,
                        'qty': received_qty
                    })
            except ValueError:
                errors.append(f"Invalid quantity for '{key}'.")

    if errors:
        flash_errors(errors)
        part_types_list = []
        try:
            cursor.execute("SELECT id, part_name, part_number, artikelnummer, brand, model FROM part_types ORDER BY brand, model, part_name ASC")
            part_types_list = cursor.fetchall()
        except sqlite3.Error as e_fetch:
            print(f"Error re-fetching part types for form: {e_fetch}", file=sys.stderr)
        return render_template('receive_stock.html',
                               part_types_list=part_types_list,
                               submitted_order_number=order_number_ref,
                               submitted_order_date=order_date_str, # Pass back to form
                               submitted_notes=order_notes), 400

    if not lines_to_process:
        flash("No positive stock quantities entered.", 'warning')
        return redirect(url_for('index'))

    try:
        cursor.execute("BEGIN TRANSACTION")
        # Modify SQL to use the provided date or default to CURRENT_TIMESTAMP
        if order_date_to_insert:
            cursor.execute("INSERT INTO stock_orders (order_number, notes, order_date) VALUES (?, ?, ?)",
                           (order_number_ref, order_notes, order_date_to_insert))
        else:
            cursor.execute("INSERT INTO stock_orders (order_number, notes, order_date) VALUES (?, ?, CURRENT_TIMESTAMP)",
                           (order_number_ref, order_notes))

        stock_order_id = cursor.lastrowid
        if not stock_order_id: raise sqlite3.Error("Failed to create stock order record.")

        for line in lines_to_process:
            part_type_id, qty_received = line['part_type_id'], line['qty']
            cursor.execute("INSERT INTO stock_order_lines (stock_order_id, part_id, quantity_received) VALUES (?, ?, ?)",
                           (stock_order_id, part_type_id, qty_received))
            line_id = cursor.lastrowid
            if not line_id: raise sqlite3.Error("Failed to create stock order line record.")
            for _ in range(qty_received):
                cursor.execute("""INSERT INTO inventory_items (part_type_id, status, stock_order_line_id, date_received, last_updated)
                                  VALUES (?, 'Available', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                               (part_type_id, line_id))
                items_created_count += 1
        conn.commit()
        flash(f"Stock received for order '{order_number_ref or '(No Ref)'}'. {items_created_count} item(s) added as 'Available'.", 'success')
        return redirect(url_for('orders_overview', search_order=order_number_ref or ''))
    except sqlite3.Error as e:
        conn.rollback(); print(e, file=sys.stderr); flash(f"Database error receiving stock: {e}", 'error')
    except Exception as e:
        conn.rollback(); print(e, file=sys.stderr); flash(f"Unexpected error receiving stock: {e}", 'error')

    part_types_list = []
    try:
        cursor.execute("SELECT id, part_name, part_number, artikelnummer, brand, model FROM part_types ORDER BY brand, model, part_name ASC")
        part_types_list = cursor.fetchall()
    except sqlite3.Error as e_fetch:
        print(f"Error re-fetching part types for form after exception: {e_fetch}", file=sys.stderr)
    return render_template('receive_stock.html',
                           part_types_list=part_types_list,
                           submitted_order_number=order_number_ref,
                           submitted_order_date=order_date_str, # Pass back to form
                           submitted_notes=order_notes), 500

import sys # Make sure sys is imported at the top of your app.py if not already

# ... (other imports and app setup) ...

@app.route('/orders')
def orders_overview():
    order_lines = []
    # Get the search term from the request and strip leading/trailing whitespace
    search_term = request.args.get('search_term', '').strip()
    
    print(f"--- Orders Overview Search ---", file=sys.stderr)
    print(f"Received search_term: '{search_term}'", file=sys.stderr)

    try:
        conn = get_db()
        cursor = conn.cursor()
        
        sql = """
            SELECT so.id as order_id, so.order_number, so.order_date,
                   sol.id as line_id, sol.quantity_received,
                   pt.id as part_type_id, pt.part_name, pt.part_number, pt.artikelnummer,
                   pt.brand, pt.model
            FROM stock_order_lines sol
            JOIN stock_orders so ON sol.stock_order_id = so.id
            JOIN part_types pt ON sol.part_id = pt.id
            WHERE 1=1 
        """
        params = []
        
        if search_term: # Only add search conditions if search_term is not empty
            search_like = f"%{search_term}%"
            # Using LOWER() for case-insensitive search on text fields
            sql_addition = """ AND (
                        LOWER(so.order_number) LIKE LOWER(?) OR
                        LOWER(pt.artikelnummer) LIKE LOWER(?) OR
                        LOWER(pt.part_number) LIKE LOWER(?)
                       )"""
            sql += sql_addition
            params.extend([search_like, search_like, search_like])
        
        sql += " ORDER BY so.order_date DESC, so.id DESC, sol.id ASC"
        
        print(f"Executing SQL: {sql}", file=sys.stderr)
        print(f"With params: {params}", file=sys.stderr)
        
        cursor.execute(sql, params)
        order_lines = cursor.fetchall()
        
        print(f"Found {len(order_lines)} order lines.", file=sys.stderr)
        print(f"------------------------------", file=sys.stderr)

    except sqlite3.Error as e:
        print(f"DB Error orders_overview: {e}", file=sys.stderr)
        flash(f"Error retrieving stock order data: {e}", "error")
    except Exception as e:
        print(f"Error orders_overview: {e}", file=sys.stderr)
        flash("An unexpected error occurred.", "error")
    
    return render_template('orders_overview.html', order_lines=order_lines, search_term=search_term)

@app.route('/bookings/add', methods=['GET'])
def add_booking_form():
    available_items = []
    try:
        conn = get_db()
        cursor = conn.cursor()
        # This query fetches all items that are currently 'Available'
        cursor.execute("""
            SELECT i.id, i.serial_number, pt.part_name, pt.part_number, pt.brand, pt.model
            FROM inventory_items i
            JOIN part_types pt ON i.part_type_id = pt.id
            WHERE i.status = 'Available' ORDER BY pt.brand, pt.model, pt.part_name, i.id
        """)
        available_items = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"DB Error fetching available items for add_booking_form: {e}", file=sys.stderr)
        flash("Error loading available inventory items.", "error")
    except Exception as e:
        print(f"Unexpected error in add_booking_form: {e}", file=sys.stderr)
        flash("An unexpected error occurred.", "error")
    
    return render_template('add_booking.html',
                           available_items=available_items,
                           submitted_data={}) # Pass submitted_data for form repopulation on errors

@app.route('/bookings/add', methods=['POST'])
def add_booking():
    conn = get_db(); cursor = conn.cursor()
    customer_name = request.form.get('customer_name')
    customer_phone = request.form.get('customer_phone') or None
    device_model = request.form.get('device_model')
    device_serial = request.form.get('device_serial') or None
    gpc_number = request.form.get('gpc_number') or None
    zir_reference = request.form.get('zir_reference') or None # Get ZIR reference
    reported_issue = request.form.get('reported_issue')
    notes = request.form.get('notes') or None
    booking_date_str = request.form.get('booking_date')
    selected_item_id_str = request.form.get('inventory_item_id')
    errors = []

    if not customer_name: errors.append("Customer Name required.")
    if not device_model: errors.append("Device Model required.")
    if not reported_issue: errors.append("Reported Issue required.")
    booking_date_to_insert = booking_date_str if booking_date_str else None
    selected_item_id = None
    if selected_item_id_str:
        try: selected_item_id = int(selected_item_id_str)
        except ValueError: errors.append("Invalid Inventory Item selected.")

    if errors:
        flash_errors(errors); available_items = []
        try:
            cursor.execute("""SELECT i.id, i.serial_number, pt.part_name FROM inventory_items i
                              JOIN part_types pt ON i.part_type_id = pt.id
                              WHERE i.status = 'Available' ORDER BY pt.part_name, i.id""")
            available_items = cursor.fetchall()
        except sqlite3.Error as e_fetch: print(f"Error re-fetching available items for form: {e_fetch}", file=sys.stderr)
        return render_template('add_booking.html', submitted_data=request.form, available_items=available_items), 400

    new_booking_id = None
    try:
        cursor.execute("BEGIN TRANSACTION")
        if booking_date_to_insert:
            sql_booking = """INSERT INTO bookings (customer_name, customer_phone, device_model, device_serial, gpc_number, zir_reference, reported_issue, notes, booking_date, last_updated)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"""
            values_booking = (customer_name, customer_phone, device_model, device_serial, gpc_number, zir_reference, reported_issue, notes, booking_date_to_insert)
        else:
            sql_booking = """INSERT INTO bookings (customer_name, customer_phone, device_model, device_serial, gpc_number, zir_reference, reported_issue, notes, last_updated)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"""
            values_booking = (customer_name, customer_phone, device_model, device_serial, gpc_number, zir_reference, reported_issue, notes)
        cursor.execute(sql_booking, values_booking)
        new_booking_id = cursor.lastrowid
        if not new_booking_id: raise sqlite3.Error("Failed to create booking record.")

        if selected_item_id:
            cursor.execute("SELECT status FROM inventory_items WHERE id = ?", (selected_item_id,))
            item_row = cursor.fetchone()
            if not item_row: raise ValueError(f"Selected Inventory Item ID {selected_item_id} not found.")
            if item_row['status'] != 'Available': raise ValueError(f"Item (ID: {selected_item_id}) not Available (Status: {item_row['status']}).")
            cursor.execute("INSERT INTO booking_parts_used (booking_id, inventory_item_id) VALUES (?, ?)", (new_booking_id, selected_item_id))
            cursor.execute("UPDATE inventory_items SET status = 'Reserved', last_updated = CURRENT_TIMESTAMP WHERE id = ?", (selected_item_id,))
            if cursor.rowcount == 0: raise sqlite3.Error(f"Failed to update status for Item ID {selected_item_id}.")
        conn.commit()
        flash(f"Booking added (ID: {new_booking_id}). {'Item assigned and Reserved.' if selected_item_id else ''}", 'success')
        return redirect(url_for('bookings_overview'))
    except ValueError as e: conn.rollback(); errors.append(str(e)); flash_errors(errors)
    except sqlite3.Error as e: conn.rollback(); print(e, file=sys.stderr); flash(f"Database error adding booking: {e}", 'error')
    except Exception as e: conn.rollback(); print(e, file=sys.stderr); flash(f"Unexpected error adding booking: {e}", 'error')

    available_items = []
    try:
        cursor.execute("""SELECT i.id, i.serial_number, pt.part_name FROM inventory_items i
                          JOIN part_types pt ON i.part_type_id = pt.id
                          WHERE i.status = 'Available' ORDER BY pt.part_name, i.id""")
        available_items = cursor.fetchall()
    except sqlite3.Error as e_fetch: print(f"Error re-fetching available items for form after exception: {e_fetch}", file=sys.stderr)
    status_code = 400 if errors else 500
    return render_template('add_booking.html', submitted_data=request.form, available_items=available_items), status_code

@app.route('/bookings')
def bookings_overview():
    bookings_processed = []
    search_term = request.args.get('search_booking', '')
    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "SELECT id, booking_date, customer_name, device_model, status, gpc_number, zir_reference, notes FROM bookings WHERE 1=1"
        params = []

        if search_term:
            search_pattern = f"%{search_term}%"
            sql += """ AND (
                        LOWER(customer_name) LIKE LOWER(?) OR
                        LOWER(device_model) LIKE LOWER(?) OR
                        CAST(id AS TEXT) LIKE ? OR
                        LOWER(gpc_number) LIKE LOWER(?) OR
                        LOWER(zir_reference) LIKE LOWER(?)
                       )"""
            params.extend([search_pattern] * 5)

        sql += " ORDER BY booking_date DESC"
        cursor.execute(sql, params)
        bookings_raw = cursor.fetchall()

        now = datetime.datetime.now()
        for booking_row in bookings_raw:
            booking_dict = dict(booking_row)
            months_in_system = 0
            booking_date_str = booking_dict.get('booking_date')
            if booking_date_str:
                try:
                    booking_date_dt = datetime.datetime.strptime(booking_date_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    delta = relativedelta(now, booking_date_dt)
                    months_in_system = delta.years * 12 + delta.months
                except (ValueError, TypeError) as e:
                    print(f"Warning: Could not parse booking_date '{booking_date_str}' for booking ID {booking_dict.get('id')}: {e}", file=sys.stderr)
            booking_dict['months_in_system'] = months_in_system
            bookings_processed.append(booking_dict)

    except sqlite3.Error as e:
        print(f"DB Error bookings_overview: {e}", file=sys.stderr)
        flash(f"Error retrieving bookings: {e}", "error")
    except Exception as e:
        print(f"Error bookings_overview: {e}", file=sys.stderr)
        flash("An unexpected error occurred.", "error")

    return render_template('bookings_overview.html',
                           bookings=bookings_processed,
                           search_term=search_term,
                           allowed_booking_statuses=ALLOWED_BOOKING_STATUSES)


@app.route('/booking/<int:booking_id>/edit', methods=['GET'])
def edit_booking_form(booking_id):
    booking = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""SELECT id, booking_date, customer_name, customer_phone,
                                 device_model, device_serial, gpc_number, zir_reference,
                                 reported_issue, status, notes
                          FROM bookings WHERE id = ?""", (booking_id,))
        booking = cursor.fetchone()
        if not booking:
            flash(f"Booking ID {booking_id} not found.", "error")
            return redirect(url_for('bookings_overview'))
    except sqlite3.Error as e:
        flash(f"Error loading booking details: {e}", "error")
        return redirect(url_for('bookings_overview'))
    return render_template('edit_booking.html',
                           booking=booking,
                           allowed_booking_statuses=ALLOWED_BOOKING_STATUSES)

@app.route('/receive_fast', methods=['GET'])
def receive_stock_fast_form():
    # For GET, just render the form.
    # 'submitted_data' can be used to repopulate form on validation errors if we redirect back.
    return render_template('receive_stock_fast.html', submitted_data={})

@app.route('/receive_fast', methods=['POST'])
def receive_stock_fast():
    conn = get_db()
    cursor = conn.cursor()
    items_created_count = 0
    errors = []
    line_item_errors = [] # To store errors for specific lines

    order_number_ref = request.form.get('order_number') or None
    order_notes = request.form.get('order_notes') or None
    order_date_str = request.form.get('order_date')

    part_identifiers = request.form.getlist('part_identifier[]')
    quantities_str = request.form.getlist('quantity[]')

    # Basic validation for order details
    order_date_to_insert = None
    if order_date_str:
        try:
            dt_obj = datetime.datetime.strptime(order_date_str, '%Y-%m-%d')
            order_date_to_insert = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            errors.append("Invalid Order Date format. Please use YY-MM-DD.")

    if not part_identifiers or not quantities_str or len(part_identifiers) != len(quantities_str):
        errors.append("Part identifier and quantity mismatch or missing.")
    
    if not any(pi.strip() for pi in part_identifiers): # Check if all identifiers are empty
        errors.append("At least one part must be entered.")

    lines_to_process = []
    submitted_items_for_repopulation = []

    for i, identifier in enumerate(part_identifiers):
        identifier = identifier.strip()
        quantity_str = quantities_str[i].strip()
        submitted_items_for_repopulation.append({'part_identifier': identifier, 'quantity': quantity_str})

        if not identifier:
            line_item_errors.append(f"Row {i+1}: Part identifier cannot be empty.")
            continue
        
        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                line_item_errors.append(f"Row {i+1}: Quantity for '{identifier}' must be positive.")
                continue
        except ValueError:
            line_item_errors.append(f"Row {i+1}: Invalid quantity for '{identifier}'.")
            continue

        # Look up part_type_id
        cursor.execute("""
            SELECT id, part_name FROM part_types 
            WHERE part_number = ? OR artikelnummer = ?
        """, (identifier, identifier))
        part_type_row = cursor.fetchone()

        if not part_type_row:
            line_item_errors.append(f"Row {i+1}: Part with identifier '{identifier}' not found.")
            continue
        
        lines_to_process.append({
            'part_type_id': part_type_row['id'],
            'part_name': part_type_row['part_name'], # For potential confirmation or logging
            'identifier_used': identifier,
            'qty': quantity
        })

    if errors or line_item_errors:
        for err in errors: flash(err, 'error')
        for err in line_item_errors: flash(err, 'error')
        
        # Repopulate form data
        submitted_data_repop = {
            'order_number': order_number_ref,
            'order_date': order_date_str,
            'order_notes': order_notes,
            'items': submitted_items_for_repopulation
        }
        return render_template('receive_stock_fast.html', submitted_data=submitted_data_repop), 400

    if not lines_to_process: # Should be caught by earlier checks but good to have
        flash("No valid stock items to process.", 'warning')
        return redirect(url_for('receive_stock_fast_form'))

    try:
        cursor.execute("BEGIN TRANSACTION")
        if order_date_to_insert:
            cursor.execute("INSERT INTO stock_orders (order_number, notes, order_date) VALUES (?, ?, ?)",
                           (order_number_ref, order_notes, order_date_to_insert))
        else:
            cursor.execute("INSERT INTO stock_orders (order_number, notes, order_date) VALUES (?, ?, CURRENT_TIMESTAMP)",
                           (order_number_ref, order_notes))
        
        stock_order_id = cursor.lastrowid
        if not stock_order_id: raise sqlite3.Error("Failed to create stock order record.")

        for line in lines_to_process:
            part_type_id, qty_received = line['part_type_id'], line['qty']
            # Here, you could potentially add 'cost_price_per_unit' if you fetch default from part_types
            cursor.execute("INSERT INTO stock_order_lines (stock_order_id, part_id, quantity_received) VALUES (?, ?, ?)",
                           (stock_order_id, part_type_id, qty_received))
            line_id = cursor.lastrowid
            if not line_id: raise sqlite3.Error(f"Failed to create stock order line for part ID {part_type_id}.")
            
            for _ in range(qty_received):
                cursor.execute("""INSERT INTO inventory_items (part_type_id, status, stock_order_line_id, date_received, last_updated)
                                  VALUES (?, 'Available', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                               (part_type_id, line_id))
                items_created_count += 1
        
        conn.commit()
        flash(f"Stock received successfully for order '{order_number_ref or '(No Ref)'}'. {items_created_count} item(s) added as 'Available'.", 'success')
        return redirect(url_for('orders_overview', search_order=order_number_ref or ''))

    except sqlite3.Error as e:
        conn.rollback()
        print(f"DB Error receive_stock_fast: {e}", file=sys.stderr)
        flash(f"Database error processing fast stock receive: {e}", 'error')
    except Exception as e:
        conn.rollback()
        print(f"Error receive_stock_fast: {e}", file=sys.stderr)
        flash(f"An unexpected error occurred: {e}", 'error')

    # If an error occurs during DB transaction, repopulate the form
    submitted_data_repop_error = {
        'order_number': order_number_ref,
        'order_date': order_date_str,
        'order_notes': order_notes,
        'items': submitted_items_for_repopulation # Use the initially parsed items
    }
    return render_template('receive_stock_fast.html', submitted_data=submitted_data_repop_error), 500

# This is the SINGLE, CORRECT version of the update_booking function for POST requests
@app.route('/booking/<int:booking_id>/edit', methods=['POST'])
def update_booking(booking_id):
    new_status = request.form.get('status') # Status is submitted from both overview and edit page

    conn = get_db()
    try:
        cursor = conn.cursor()

        # Check if the submission is from the full edit_booking.html page
        if 'submit_edit_booking' in request.form:
            new_notes = request.form.get('notes', '')
            new_gpc_number = request.form.get('gpc_number', '')
            new_zir_reference = request.form.get('zir_reference', '')

            if not new_status or new_status not in ALLOWED_BOOKING_STATUSES:
                flash("Invalid status provided.", "error")
                return redirect(url_for('edit_booking_form', booking_id=booking_id))

            sql = """
                UPDATE bookings
                SET status = ?, notes = ?, gpc_number = ?, zir_reference = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            params = (new_status, new_notes, new_gpc_number, new_zir_reference, booking_id)
            success_redirect_url = url_for('bookings_overview')
            error_redirect_url = url_for('edit_booking_form', booking_id=booking_id)

        else: # Submission is from bookings_overview.html (status change only, GPC/ZIR not submitted)
            # The overview form still submits 'notes' via a hidden field.
            # If notes should ONLY be editable on the edit_booking_page, this part would also change.
            # For now, respecting that notes are submitted from overview.
            new_notes_from_overview = request.form.get('notes', '')

            if not new_status or new_status not in ALLOWED_BOOKING_STATUSES:
                flash("Invalid status provided.", "error")
                return redirect(url_for('bookings_overview'))

            # Only update status and notes. GPC and ZIR are intentionally left out.
            sql = """
                UPDATE bookings
                SET status = ?, notes = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            params = (new_status, new_notes_from_overview, booking_id)
            success_redirect_url = url_for('bookings_overview')
            error_redirect_url = url_for('bookings_overview')


        cursor.execute(sql, params)

        if cursor.rowcount == 0:
            flash(f"Booking ID {booking_id} not found or no changes made.", "warning")
        else:
            conn.commit()
            flash(f"Booking ID {booking_id} updated successfully.", "success")
        
        return redirect(success_redirect_url)

    except sqlite3.Error as e:
        if conn: conn.rollback()
        flash(f"Database error updating booking: {e}", "error")
        # Determine redirect based on source if error_redirect_url was not set above for validation
        if 'submit_edit_booking' in request.form:
             return redirect(url_for('edit_booking_form', booking_id=booking_id))
        else:
             return redirect(url_for('bookings_overview'))
    except Exception as e:
        if conn: conn.rollback()
        flash(f"An unexpected error occurred: {e}", "error")
        if 'submit_edit_booking' in request.form:
            return redirect(url_for('edit_booking_form', booking_id=booking_id))
        else:
            return redirect(url_for('bookings_overview'))

def get_schema_version(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version FROM schema_version LIMIT 1")
        result = cursor.fetchone()
        return result['version'] if result else 0
    except sqlite3.Error:
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
            if not cursor.fetchone(): return 0
            print("Warning: schema_version table exists but could not query version.", file=sys.stderr)
            return 0
        except sqlite3.Error as e_check:
            print(f"Error checking schema_version table existence: {e_check}", file=sys.stderr)
            return 0

if __name__ == '__main__':
    try: from dateutil.relativedelta import relativedelta
    except ImportError: print("ERROR: 'python-dateutil' not found. pip install python-dateutil"); sys.exit(1)
    if not os.path.exists(DATABASE): print(f"WARNING: DB '{DATABASE}' not found. Run database_setup.py.", file=sys.stderr); sys.exit(1)

    try:
        with sqlite3.connect(DATABASE) as temp_conn:
            temp_conn.row_factory = sqlite3.Row
            current_ver = get_schema_version(temp_conn)
        # Check against the schema version this app code requires
        if current_ver < DB_SCHEMA_REQ:
             print(f"WARNING: DB schema version ({current_ver}) < required ({DB_SCHEMA_REQ}). Run database_setup.py.", file=sys.stderr)
             # sys.exit(1) # Optional: exit if schema is too old
        elif current_ver > DB_SCHEMA_REQ:
             print(f"WARNING: DB schema version ({current_ver}) > expected ({DB_SCHEMA_REQ}). App might malfunction.", file=sys.stderr)
    except Exception as e: print(f"Error checking DB version: {e}", file=sys.stderr)

    host = os.environ.get('IP', '0.0.0.0'); port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask server on http://{host}:{port}/ (or http://127.0.0.1:{port}/)")
    app.run(debug=True, host=host, port=port)