from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from db import get_connection  # Your custom DB connection module

def read_from_firestore(collection):
    url = f"https://firestore.googleapis.com/v1/projects/dbms-56de1/databases/(default)/documents/{collection}"
    response = requests.get(url)
    if response.status_code != 200:
        return []
    documents = response.json().get("documents", [])
    results = []
    for doc in documents:
        fields = doc.get("fields", {})
        record = {}
        for key, value in fields.items():
            if "stringValue" in value:
                record[key] = value["stringValue"]
            elif "integerValue" in value:
                record[key] = int(value["integerValue"])
            elif "doubleValue" in value:
                record[key] = float(value["doubleValue"])
        results.append(record)
    return results


def push_to_firestore(collection, data_dict):
    import requests
    url = f"https://firestore.googleapis.com/v1/projects/dbms-56de1/databases/(default)/documents/{collection}"
    fields = {"fields": {}}
    for k, v in data_dict.items():
        if isinstance(v, int):
            fields["fields"][k] = {"integerValue": v}
        elif isinstance(v, float):
            fields["fields"][k] = {"doubleValue": v}
        else:
            fields["fields"][k] = {"stringValue": str(v)}
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=fields, headers=headers)
    print(f"[{collection}] Firestore status:", response.status_code)
    print(f"[{collection}] Firestore response:", response.text)


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Used for session management

@app.route('/')
def home():
    if 'loggedin' in session:
        return redirect(url_for('index'))
    return render_template('home.html')

@app.route('/users', methods=['GET'])
def get_users():
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, name, email, phone_number, address, user_type, loyalty_points
            FROM users
            ORDER BY user_id
        """)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        formatted_users = []
        for user in rows:
            formatted_user = {
                'id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'phone': user['phone_number'],
                'address': user['address'],
                'type': user['user_type'],
                'loyalty_points': user['loyalty_points']
            }
            formatted_users.append(formatted_user)

            # ✅ Firestore write
            push_to_firestore('users', {
                'user_id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'phone': user['phone_number'],
                'address': user['address'],
                'type': user['user_type'],
                'loyalty_points': user['loyalty_points']
            })

        # If the request is from a browser, render the HTML template
        if 'text/html' in request.headers.get('Accept', ''):
            return render_template('users.html', users=formatted_users)
        # Otherwise, return JSON (API)
        return jsonify(formatted_users)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            conn = cur = None
            try:
                conn = get_connection()
                cur = conn.cursor()
                plain_password = data['password']

                cur.execute("""
                    INSERT INTO users (name, email, password, phone_number, address, user_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    data['name'], data['email'], plain_password,
                    data['phone_number'], data['address'], data['user_type']
                ))
                
                # Log the user signup
                cur.execute("""
                    INSERT INTO Logged_Users (username, role, event_type)
                    VALUES (%s, %s, %s)
                """, (data['name'], 'user', 'signup'))
                
                conn.commit()
                push_to_firestore('users', {
                    'name': data['name'],
                    'email': data['email'],
                    'phone': data['phone_number'],
                    'address': data['address'],
                    'type': data['user_type']
                })
                return jsonify({"message": "Signup successful!"}), 201
            except Exception as e:
                return jsonify({"error": str(e)}), 400
            finally:
                if cur: cur.close()
                if conn: conn.close()
        else:
            return jsonify({"error": "Request must be JSON"}), 400
    return render_template('signup.html')

@app.route('/signup_admin', methods=['GET', 'POST'])
def signup_admin():
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT hotel_id, name FROM Hotels ORDER BY name")
        hotels = cur.fetchall()
    finally:
        if cur: cur.close()
        if conn: conn.close()

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            conn = cur = None
            try:
                conn = get_connection()
                cur = conn.cursor()
                plain_password = data['password']

                # Verify hotel exists
                cur.execute("SELECT hotel_id FROM Hotels WHERE hotel_id = %s", (data['hotel_id'],))
                hotel = cur.fetchone()

                if not hotel:
                    return jsonify({"error": "Hotel not found. Please register the hotel first."}), 400

                hotel_id = hotel[0]

                # ✅ Add RETURNING admin_id to this line
                cur.execute("""
                    INSERT INTO Admins (name, email, password, phone_number, role, hotel_id)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING admin_id
                """, (
                    data['name'], data['email'], plain_password,
                    data['phone_number'], data['role'], hotel_id
                ))

                admin_id = cur.fetchone()[0]  # ✅ Now this will work
                conn.commit()

                # ✅ Firestore push
                push_to_firestore('admins', {
                    'admin_id': admin_id,
                    'name': data['name'],
                    'email': data['email'],
                    'phone': data['phone_number'],
                    'role': data['role'],
                    'hotel_id': hotel_id
                })

                return jsonify({"message": "Admin signup successful!"}), 201

            except Exception as e:
                return jsonify({"error": str(e)}), 400
            finally:
                if cur: cur.close()
                if conn: conn.close()
        else:
            return jsonify({"error": "Request must be JSON"}), 400

    return render_template('signup_admin.html', hotels=hotels)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'loggedin' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            user_type = request.form.get('type', request.args.get('type', 'user'))

        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            
            if user_type == 'admin':
                # Check in Admins table ONLY
                cur.execute("SELECT admin_id, password, role FROM Admins WHERE name = %s", (username,))
                admin = cur.fetchone()
                if admin and admin[1] == password:
                    session['user_id'] = admin[0]
                    session['username'] = username
                    session['user_type'] = 'admin'
                    session['loggedin'] = True
                    
                    # Log the admin login
                    cur.execute("""
                        INSERT INTO Logged_Users (username, role, event_type)
                        VALUES (%s, %s, %s)
                    """, (username, 'admin', 'login'))
                    conn.commit()
                    
                    return redirect(url_for('index'))
            else:
                # Check in Users table ONLY
                cur.execute("SELECT user_id, password, user_type FROM Users WHERE name = %s", (username,))
                user = cur.fetchone()
                if user and user[1] == password:
                    session['user_id'] = user[0]
                    session['username'] = username
                    session['user_type'] = user[2]
                    session['loggedin'] = True
                    
                    # Log the user login
                    cur.execute("""
                        INSERT INTO Logged_Users (username, role, event_type)
                        VALUES (%s, %s, %s)
                    """, (username, 'user', 'login'))
                    conn.commit()
                    
                    return redirect(url_for('index'))

            flash('Invalid username or password')
            return redirect(url_for('login'))

        except Exception as e:
            flash(str(e))
            return redirect(url_for('login'))
        finally:
            if cur: cur.close()
            if conn: conn.close()
            
    return render_template('login.html')

@app.route('/menu', methods=['GET'])
def get_menu():
    hotel_search = request.args.get('hotel', '').lower()
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT m.item_id, h.name AS hotel_name, m.item_name, m.price
            FROM menu_items m
            JOIN hotels h ON m.hotel_id = h.hotel_id
            WHERE LOWER(h.name) LIKE %s
            ORDER BY h.name
        """, ('%' + hotel_search + '%',))
        rows = cur.fetchall()
        menu = []
        for r in rows:
            item = {
                "item_id": r[0],
                "hotel_name": r[1],
                "item_name": r[2],
                "price": float(r[3])
            }
            menu.append(item)

            # ✅ Firestore write
            push_to_firestore('menu', {
                'item_id': item['item_id'],
                'hotel_name': item['hotel_name'],
                'item_name': item['item_name'],
                'price': item['price']
            })

        return jsonify(menu)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.route('/track_order', methods=['GET', 'POST'])
def track_order():
    if 'user_id' not in session:
        flash('Login required to track orders.')
        return redirect(url_for('login'))

    order_details = None
    error_message = None

    if request.method == 'POST':
        order_id = request.form.get('order_id')

        if not order_id:
            error_message = 'Order ID is required.'
        else:
            conn = cur = None
            try:
                conn = get_connection()
                cur = conn.cursor()

                cur.execute("""
                    SELECT o.order_id, h.name AS hotel_name, o.order_status, d.status AS delivery_status,
                           o.order_time, o.total_amount
                    FROM Orders o
                    JOIN Hotels h ON o.hotel_id = h.hotel_id
                    LEFT JOIN Deliveries d ON o.order_id = d.order_id
                    WHERE o.order_id = %s AND o.user_id = %s
                """, (order_id, session['user_id']))
                order = cur.fetchone()

                if not order:
                    error_message = 'Order not found or does not belong to you.'
                else:
                    cur.execute("""
                        SELECT i.item_name, oi.quantity
                        FROM Order_Items oi
                        JOIN Menu i ON oi.menu_id = i.menu_id
                        WHERE oi.order_id = %s
                    """, (order_id,))
                    items = cur.fetchall()

                    item_list = [{'name': row[0], 'quantity': row[1]} for row in items]

                    order_details = {
                        'order_id': order[0],
                        'hotel_name': order[1],
                        'order_status': order[2],
                        'delivery_status': order[3],
                        'order_time': order[4],
                        'total_amount': order[5],
                        'items': item_list
                    }

            except Exception as e:
                error_message = str(e)
            finally:
                if cur: cur.close()
                if conn: conn.close()

    return render_template('track.html', order=order_details, error=error_message)

@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 401

    try:
        data = request.get_json()
        if not data or 'items' not in data or 'hotel_id' not in data or 'delivery_address' not in data:
            return jsonify({'error': 'Missing items, hotel, or address'}), 400

        conn = get_connection()
        cur = conn.cursor()

        # Check if all items are available and have sufficient quantity
        for item in data['items']:
            cur.execute("""
                SELECT quantity, item_name 
                FROM menu 
                WHERE menu_id = %s AND hotel_id = %s
            """, (item['menu_id'], data['hotel_id']))
            result = cur.fetchone()
            
            if not result:
                return jsonify({'error': f'Item {item["menu_id"]} not found'}), 404
            
            quantity, item_name = result
            if quantity < item['quantity']:
                return jsonify({
                    'error': f'Not enough quantity available for {item_name}. Available: {quantity}, Requested: {item["quantity"]}'
                }), 400

        # Calculate total amount
        total_amount = 0
        for item in data['items']:
            cur.execute("SELECT price FROM menu WHERE menu_id = %s", (item['menu_id'],))
            price = cur.fetchone()[0]
            total_amount += price * item['quantity']

        # Insert order
        cur.execute("""
            INSERT INTO orders (user_id, hotel_id, total_amount, delivery_address, order_status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING order_id
        """, (session['user_id'], data['hotel_id'], total_amount, data['delivery_address']))
        
        order_id = cur.fetchone()[0]

        # Insert order items
        for item in data['items']:
            cur.execute("""
                INSERT INTO order_items (order_id, menu_id, quantity)
                VALUES (%s, %s, %s)
            """, (order_id, item['menu_id'], item['quantity']))

        conn.commit()
        push_to_firestore('orders', {
            'order_id': order_id,
            'user_id': session['user_id'],
            'hotel_id': data['hotel_id'],
            'total_amount': total_amount,
            'delivery_address': data['delivery_address'],
            'order_status': 'pending'
        })
        return jsonify({'order_id': order_id})

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/admin/orders', methods=['GET', 'POST'])
def admin_orders():
    if 'user_id' not in session or session.get('user_type') != 'admin':
        flash('Admin login required to view hotel orders.')
        return redirect(url_for('login'))

    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT hotel_id FROM Admins WHERE admin_id = %s", (session['user_id'],))
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'Admin hotel not found'}), 404
        admin_hotel_id = result[0]

        if request.method == 'POST':
            data = request.get_json()
            order_id = data.get('order_id')
            new_status = data.get('new_status')

            if not order_id or not new_status:
                return jsonify({'error': 'Missing order_id or new_status'}), 400

            cur.execute("""
                UPDATE Orders
                SET order_status = %s
                WHERE order_id = %s AND hotel_id = %s
            """, (new_status, order_id, admin_hotel_id))

            if cur.rowcount == 0:
                return jsonify({'error': 'Order not found or not authorized'}), 403
            if new_status.lower() == 'out for delivery':
                cur.execute("SELECT 1 FROM Deliveries WHERE order_id = %s", (order_id,))
            if cur.fetchone():
                cur.execute("UPDATE Deliveries SET status = 'Picked' WHERE order_id = %s", (order_id,))
            else:
                cur.execute("INSERT INTO Deliveries (order_id, status) VALUES (%s, 'Picked')", (order_id,))

            conn.commit()
            return jsonify({'message': f'Order {order_id} status updated to {new_status}.'}), 200

        cur.execute("""
            SELECT o.order_id, u.name AS customer_name, o.delivery_address, o.order_status, o.order_time, o.total_amount
            FROM Orders o
            JOIN Users u ON o.user_id = u.user_id
            WHERE o.hotel_id = %s
            ORDER BY o.order_time DESC
        """, (admin_hotel_id,))
        rows = cur.fetchall()
        orders = []
        for row in rows:
            order_id = row[0]
            # Fetch items for this order
            cur.execute("""
                SELECT m.item_name, oi.quantity
                FROM order_items oi
                JOIN menu m ON oi.menu_id = m.menu_id
                WHERE oi.order_id = %s
            """, (order_id,))
            items = [{'name': item_row[0], 'quantity': item_row[1]} for item_row in cur.fetchall()]
            orders.append({
                "order_id": order_id,
                "customer_name": row[1],
                "delivery_address": row[2],
                "order_status": row[3],
                "order_time": row[4].strftime('%Y-%m-%d %H:%M:%S'),
                "total_amount": row[5],
                "items": items
            })
        print("Orders for admin:", orders)
        return render_template('admin_orders.html', orders=orders)  
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.route('/admin/add_menu', methods=['GET', 'POST'])
def add_menu():
    if 'user_id' not in session or session.get('user_type') != 'admin':
        flash('Admin login required to add menu items.', 'error')
        return redirect(url_for('login'))

    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Get hotel_id of the current admin
        cur.execute("SELECT hotel_id FROM Admins WHERE admin_id = %s", (session['user_id'],))
        result = cur.fetchone()
        if not result:
            flash('Associated hotel not found.', 'error')
            return redirect(url_for('index'))

        hotel_id = result[0]

        if request.method == 'POST':
            try:
                item_name = request.form['item_name']
                description = request.form['description']
                category = request.form['category']
                price = float(request.form['price'])
                quantity = int(request.form['quantity'])

                if quantity < 0:
                    flash('Quantity cannot be negative.', 'error')
                    return redirect(url_for('add_menu'))

                # Check if item already exists
                cur.execute("""
                    SELECT menu_id, quantity FROM menu 
                    WHERE item_name = %s AND hotel_id = %s
                """, (item_name, hotel_id))
                existing_item = cur.fetchone()

                if existing_item:
                    # Update existing item's quantity
                    new_quantity = existing_item[1] + quantity
                    cur.execute("""
                        UPDATE menu 
                        SET quantity = %s, 
                            price = %s, 
                            description = %s, 
                            category = %s,
                            availability = %s
                        WHERE menu_id = %s
                    """, (new_quantity, price, description, category, 
                          new_quantity > 0, existing_item[0]))
                    flash(f'Updated existing item "{item_name}" with {quantity} more units.', 'success')
                else:
                    # Insert new item
                    cur.execute("""
                        INSERT INTO menu (hotel_id, item_name, description, category, price, quantity)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (hotel_id, item_name, description, category, price, quantity))

                    # ✅ Push to Firestore
                    push_to_firestore('menu', {
                        'hotel_id': hotel_id,
                        'item_name': item_name,
                        'description': description,
                        'category': category,
                        'price': price,
                        'quantity': quantity
                    })

                    flash(f'Successfully added new item "{item_name}"!', 'success')

                conn.commit()
                return redirect(url_for('add_menu'))

            except ValueError as e:
                flash('Invalid price or quantity value.', 'error')
                return redirect(url_for('add_menu'))
            except Exception as e:
                flash(f'Error adding menu item: {str(e)}', 'error')
                return redirect(url_for('add_menu'))

        return render_template('add_menu.html')

    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('index'))
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.route('/index')
def index():
    if 'user_id' in session:
        user_type = session.get('user_type', 'User')
        username = session.get('username', 'User')

        if user_type == 'admin':
            return render_template("admin_index.html", username=username)
        else:
            msg = f"Welcome {user_type} {username} to the Index Page!"
            return render_template("index.html", msg=msg, user_type=user_type)
    else:
        flash("Please log in to access this page.")
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()  # This clears all session data
    flash('You have been logged out.')
    return redirect(url_for('login'))  # Redirect to login page (or use 'home' if preferred)

@app.route('/user_portal', methods=['GET', 'POST'])
def user_portal():
    if 'user_id' not in session or session.get('user_type') == 'admin':
        flash('Only users can access the student portal.')
        return redirect(url_for('login'))
    if request.method == 'POST':
        order_id = request.form.get('order_id')
        food_rating = request.form.get('food_rating')
        delivery_rating = request.form.get('delivery_rating')
        comments = request.form.get('comments')
        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO Ratings (order_id, food_rating, delivery_rating, comments) VALUES (%s, %s, %s, %s)",
                        (order_id, food_rating, delivery_rating, comments))
            conn.commit()
            push_to_firestore('ratings', {
                'order_id': order_id,
                'food_rating': food_rating,
                'delivery_rating': delivery_rating,
                'comments': comments
            })
            flash('Thank you for your feedback!')
        except Exception as e:
            flash(f'Error: {str(e)}')
        finally:
            if cur: cur.close()
            if conn: conn.close()
    return render_template('user_portal.html')

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        flash('Please login to view your cart.')
        return redirect(url_for('login'))
    return render_template('cart.html')

@app.route('/order', methods=['GET'])
def order():
    if 'user_id' not in session:
        flash('Please login to place an order.', 'error')
        return redirect(url_for('login'))

    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Get all hotels
        cur.execute("SELECT hotel_id, name FROM Hotels ORDER BY name")
        hotels = cur.fetchall()

        # Get menu items for selected hotel
        selected_hotel_id = request.args.get('hotel_id')
        menu_items = []
        
        if selected_hotel_id:
            cur.execute("""
                SELECT menu_id, item_name, description, price, category, availability, quantity
                FROM menu
                WHERE hotel_id = %s
                ORDER BY category, item_name
            """, (selected_hotel_id,))
            
            menu_items = [
                {
                    "menu_id": row[0],
                    "item_name": row[1],
                    "description": row[2],
                    "price": float(row[3]),
                    "category": row[4],
                    "availability": row[5],
                    "quantity": row[6]
                }
                for row in cur.fetchall()
            ]

        return render_template('order.html', 
                             hotels=hotels, 
                             menu=menu_items, 
                             selected_hotel_id=selected_hotel_id)

    except Exception as e:
        flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('index'))
    finally:
        if cur: cur.close()
        if conn: conn.close()

if __name__ == '__main__':
    app.run(debug=True)
