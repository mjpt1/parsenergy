"""Passenger entry point for cPanel "Setup Python App".

cPanel/Phusion Passenger imports the ``application`` callable from this file at
the application root. We simply hand off to Django's WSGI application.

If cPanel generated its own passenger_wsgi.py when you created the Python app,
replace its contents with this file.
"""
import os
import sys

# Make sure the application root (this directory, which contains manage.py and
# the inner ``solarops`` package) is importable.
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'solarops.settings')

from solarops.wsgi import application  # noqa: E402  (must come after sys.path/env setup)
