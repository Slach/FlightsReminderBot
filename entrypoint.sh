#!/bin/bash

if [ "$RUN_SCRIPT" = "app.py" ]; then
    exec python app.py
else
    exec python bot.py
fi 