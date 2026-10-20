import os

os.environ["TIMELAPSE_DISABLE_FILE_LOGGING"] = "1"
# A preset set on the machine running the tests (the web server) must not change expected commands.
os.environ.pop("TIMELAPSE_X264_PRESET", None)
