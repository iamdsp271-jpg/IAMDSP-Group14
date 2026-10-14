"""Basic settings for the IAMDSP system. Change values here if you need to."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "iamdsp.db")
SECRET_KEY = "iamdsp-group-fourteen-secret-key-change-me"

# Current academic term (marks are entered for this term only)
CURRENT_TERM = "2026/2027 Semester 1"
PASS_MARK = 50          # total mark (out of 100) needed to pass a course
CA_MAX = 40             # continuous assessment is marked out of 40
EXAM_MAX = 60           # examination is marked out of 60

# Group login (the group leader's system administrator account)
GROUP_USERNAME = "groupfourteen"
GROUP_PASSWORD = "IAMDSP_PASSCODE"
DEFAULT_PASSWORD = "Ipam@2026"   # password for every other demo account
