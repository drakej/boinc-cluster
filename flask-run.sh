#!/bin/bash

# You need to setup a virtual environment with Python3 in .env to make this script work correctly
source .env/bin/activate
export FLASK_APP=boinccluster.py
export FLASK_DEBUG=True

flask run --host=0.0.0.0 --port=8000
