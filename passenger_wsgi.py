# passenger_wsgi.py - cPanel/LiteSpeed WSGI entry point
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app import app as application
