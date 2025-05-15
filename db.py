# db.py
import psycopg2
from config import config

def get_connection():
    params = config()
    conn = psycopg2.connect(**params)
    return conn
