# passenger_wsgi.py - Required by cPanel Python App (Passenger)
import sys
import os

# Add the application directory to the path
INTERP = os.path.expanduser("~/virtualenv/kalstonelogistics/3.11/bin/python3")
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

sys.path.insert(0, os.path.dirname(__file__))

from app import app as application
